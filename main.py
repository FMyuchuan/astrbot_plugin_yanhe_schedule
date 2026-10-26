# -*- coding: utf-8 -*-
"""延河课表 AstrBot 插件。

在聊天里查询课表：本周、指定周、今日/tomorrow、下节课、学期切换、周次校准。
仅用于查询当前账号自己的课表。
"""

import asyncio
import json
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star

from .core.campus import rows_to_occurrences
from .core.format import (
    HELP_TEXT,
    format_day,
    format_next,
    format_terms,
    parse_schedule_args,
)
from .core.jwapp import (
    CaptchaChallenge,
    JwappClient,
    JwappError,
    LoginChallenge,
    SmsChallenge,
)
from .core.render import render_grid, render_ics, render_json, render_list
from .core.schedule import Timetable

PLUGIN_NAME = "astrbot_plugin_yanhe_schedule"


def _safe_name(text: str) -> str:
    """把学期名之类的标签压成安全的文件名片段。"""
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]", "_", text or "")
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned or "schedule"


def _strip_command(text: str, *names: str) -> str:
    """剥掉消息开头的指令词，返回后面的参数。

    指令名只认英文，不做中文兼容；参数里的中文照旧（如 /schedule 第9周）。
    """
    raw = (text or "").strip().lstrip("/!！").strip()
    lowered = raw.lower()
    for name in names:
        if lowered.startswith(name.lower()):
            return raw[len(name):].strip()
    return raw




def _data_dir() -> Path:
    """持久化目录：优先 AstrBot 的 data/plugin_data，失败则用插件目录。"""
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        base = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
    except Exception:
        base = Path(__file__).resolve().parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


DATA_DIR = _data_dir()
SESSION_FILE = DATA_DIR / "session.json"
CACHE_DIR = DATA_DIR / "cache"


class YanheSchedulePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._client: JwappClient | None = None
        self._pending_client: JwappClient | None = None
        self._thread_lock = threading.Lock()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ 基础
    def _load_state(self) -> dict:
        try:
            return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        try:
            SESSION_FILE.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            # 会话里有登录 cookie，只给进程属主读
            SESSION_FILE.chmod(0o600)
        except OSError as exc:
            logger.warning(f"[课表] 保存会话失败：{exc}")

    def _allowed(self, event: AstrMessageEvent) -> bool:
        allow = [str(x) for x in (self.config.get("allowed_users") or [])]
        if not allow:
            return True
        try:
            return str(event.get_sender_id()) in allow
        except Exception:
            return False

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        admins = [str(x) for x in (self.config.get("admin_users") or [])]
        if not admins:
            return True
        try:
            return str(event.get_sender_id()) in admins
        except Exception:
            return False

    def _can_manage_login(self, event: AstrMessageEvent) -> bool:
        """登录类命令的权限：会发真实短信、改写全局会话，比查询更敏感。

        优先看 ``admin_users``；没配时退回 ``allowed_users``；
        两者都空（单用户部署）才允许所有人。
        """
        admins = [str(x) for x in (self.config.get("admin_users") or [])]
        if admins:
            return self._is_admin(event)
        return self._allowed(event)


    def _cfg(self, key: str, default=None):
        value = self.config.get(key, default)
        return default if value in (None, "") else value

    # ------------------------------------------------------------ 缓存
    def _term_cache_file(self, term: str) -> Path:
        safe = re.sub(r"[^0-9A-Za-z._-]", "_", term)
        return CACHE_DIR / f"term-{safe}.json"

    def _load_term_cache(self, term: str):
        try:
            ttl = int(float(self._cfg("cache_hours", 6))) * 3600
        except (TypeError, ValueError):
            ttl = 6 * 3600
        if ttl <= 0:
            return None
        path = self._term_cache_file(term)
        try:
            if datetime.now().timestamp() - path.stat().st_mtime > ttl:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        # 字段不全的缓存直接当没有，别让它带着 KeyError 往下走
        if not isinstance(payload, dict) or not {"term_start", "rows"} <= payload.keys():
            return None
        return payload


    def _save_term_cache(self, term: str, payload: dict) -> None:
        try:
            self._term_cache_file(term).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    # ------------------------------------------------------------ 数据
    def _ensure_client(self) -> JwappClient:
        client = JwappClient()
        client.load_cookies(self._state.get("jwapp_cookies"))
        if client.verify():
            self._client = client
            return client

        sid = str(self._cfg("sid", ""))
        password = str(self._cfg("password", ""))
        if not sid or not password:
            raise JwappError("插件还没配置学号和密码，请到插件配置里填写")
        try:
            client.login(sid, password)
        except LoginChallenge as exc:
            self._pending_client = client
            raise JwappError(
                f"{exc}：请在聊天里发送 /login 完成验证（验证码用 /code 123456 发送）"
            ) from exc
        self._state["jwapp_cookies"] = client.cookie_data()
        self._state["sid"] = sid
        self._save_state()
        self._client = client
        return client

    # ------------------------------------------------------- 人工登录
    def _save_client_session(self, client: JwappClient) -> None:
        self._state["jwapp_cookies"] = client.cookie_data()
        self._state["sid"] = str(self._cfg("sid", ""))
        self._save_state()
        self._client = client
        self._pending_client = None

    def _format_challenge(self, challenge: LoginChallenge) -> list[tuple[str, str]]:
        """把登录挑战整理成要发出去的消息：[(kind, payload)]。"""
        if isinstance(challenge, CaptchaChallenge):
            path = DATA_DIR / "captcha.png"
            try:
                path.write_bytes(challenge.image)
            except OSError:
                path = None
            text = "登录需要图形验证码，请输入图片里的字符：发送 /code 字符"
            if challenge.purpose == "sms":
                text = "发送短信前需要图形验证码，请输入图片里的字符：发送 /code 字符"
            out: list[tuple[str, str]] = []
            if path:
                out.append(("image", str(path)))
            out.append(("text", text))
            return out
        if isinstance(challenge, SmsChallenge):
            tail = challenge.phone[-4:] if challenge.phone else "****"
            return [
                (
                    "text",
                    f"短信验证码已发到尾号 {tail} 的手机，发送 /code 123456 完成登录。",
                )
            ]
        return [("text", str(challenge))]

    def _do_login(self) -> dict:
        """完整走一次登录（含 bootstrap），返回当前学期信息。"""
        sid = str(self._cfg("sid", ""))
        password = str(self._cfg("password", ""))
        if not sid or not password:
            raise JwappError("插件还没配置学号和密码，请到插件配置里填写")
        # 和抓课表共用一把锁：登录会改写整个 requests.Session，
        # 与正在进行的查询并发会互相踩 cookie。
        with self._thread_lock:
            client = JwappClient()
            try:
                client.login(sid, password)
            except LoginChallenge:
                # 记住这个 client，/code 要在同一个会话里续跑
                self._pending_client = client
                raise
            self._save_client_session(client)
            client.bootstrap()
            return client.current_term()

    def _do_code(self, code: str) -> dict:
        """用验证码续跑登录，返回当前学期信息。"""
        client = self._pending_client
        if client is None:
            raise JwappError("当前没有等待验证码的登录，请先发送 /login")
        with self._thread_lock:
            if client.pending_kind() in ("login_captcha", "sms_captcha"):
                client.resume_captcha(code)
            else:
                client.resume_sms(code)
            self._save_client_session(client)
            client.bootstrap()
            return client.current_term()



    @filter.command("login")
    async def cmd_login(self, event: AstrMessageEvent):
        if not self._can_manage_login(event):
            yield event.plain_result("只有管理员能发起登录。")
            return
        try:
            info = await asyncio.to_thread(self._do_login)
            yield event.plain_result(
                f"登录成功，已保存会话。\n当前学期：{info['mc']}（{info['dm']}）\n"
                "发送 /schedule 查看课表。"
            )
        except LoginChallenge as challenge:
            for kind, payload in self._format_challenge(challenge):
                if kind == "image":
                    yield event.image_result(payload)
                else:
                    yield event.plain_result(payload)
        except JwappError as exc:
            yield event.plain_result(f"登录失败：{exc}")

    @filter.command("code")
    async def cmd_code(self, event: AstrMessageEvent):
        if not self._can_manage_login(event):
            yield event.plain_result("只有管理员能完成登录验证。")
            return
        code = _strip_command(event.message_str, "code")
        code = re.sub(r"\s+", "", code)
        if not code:
            yield event.plain_result("用法：/code 123456 或 /code abcd")
            return
        try:
            info = await asyncio.to_thread(self._do_code, code)
            yield event.plain_result(
                f"验证通过，登录成功。\n当前学期：{info['mc']}（{info['dm']}）"
            )
        except LoginChallenge as challenge:
            for kind, payload in self._format_challenge(challenge):
                if kind == "image":
                    yield event.image_result(payload)
                else:
                    yield event.plain_result(payload)
        except JwappError as exc:
            yield event.plain_result(f"验证失败：{exc}")

    @filter.command("cancel_login")
    async def cmd_login_cancel(self, event: AstrMessageEvent):
        if not self._can_manage_login(event):
            yield event.plain_result("只有管理员能取消登录。")
            return
        self._pending_client = None
        yield event.plain_result("已取消待验证的登录。")


    def _resolve_term_start(self, client: JwappClient, term: str) -> date:
        saved = (self._state.get("term_starts") or {}).get(term)
        if saved:
            try:
                return date.fromisoformat(saved)
            except ValueError:
                pass
        configured = str(self._cfg("term_start", ""))
        if configured:
            try:
                return date.fromisoformat(configured)
            except ValueError:
                pass
        offset = client.week_offset(term)
        week_dates = client.week_dates(term, 1 + offset)
        for item in week_dates:
            if str(item.get("XQ")) == "1" and item.get("RQ"):
                return date.fromisoformat(str(item["RQ"]))
        if week_dates:
            return date.fromisoformat(str(week_dates[0]["RQ"]))
        raise JwappError("拿不到第一周日期，请用 /calibrate N 指定当前周次")

    def _current_term(self) -> str:
        return str(self._state.get("term") or self._cfg("term", ""))

    def _fetch_timetable(self, *, refresh: bool = False):
        """同步抓取课表（在线程里跑）。返回 (Timetable, 学期名)。"""
        with self._thread_lock:
            client = self._ensure_client()
            client.bootstrap()

            term = self._current_term()
            if term:
                label = term
            else:
                info = client.current_term()
                term, label = info["dm"], info["mc"] or info["dm"]

            payload = None if refresh else self._load_term_cache(term)
            if payload:
                term_start = date.fromisoformat(payload["term_start"])
                rows = payload["rows"]
                label = payload.get("label") or label
            else:
                term_start = self._resolve_term_start(client, term)
                rows = client.schedule_rows(term)
                if label == term:
                    # 手动指定学期时代码里没有中文名，顺手取一次学期列表补上
                    try:
                        for row in client.terms():
                            if str(row.get("dm")) == term:
                                label = row.get("mc") or term
                                break
                    except JwappError:
                        pass
                self._save_term_cache(
                    term,
                    {
                        "term": term,
                        "label": label,
                        "term_start": term_start.isoformat(),
                        "rows": rows,
                        "fetched_at": datetime.now().isoformat(timespec="seconds"),
                    },
                )

            occurrences = rows_to_occurrences(rows, term_start)
            timetable = Timetable(
                occurrences,
                term_start=term_start,
                weeks=int(self._cfg("max_weeks", 16)),
            )
            if self._state.get("term_key") != term or self._state.get("last_term") != label:
                self._state["term_key"] = term
                self._state["last_term"] = label
                self._save_state()
            return timetable, label

    async def _timetable(self, *, refresh: bool = False):
        return await asyncio.to_thread(self._fetch_timetable, refresh=refresh)

    def _header(self, tt: Timetable, week: int) -> str:
        dates = tt.week_dates(week)
        return f"{dates[0].strftime('%m-%d')} ~ {dates[-1].strftime('%m-%d')} · 第 {week} 周"

    # ------------------------------------------------------------ 命令
    @filter.command("schedule")
    async def cmd_schedule(self, event: AstrMessageEvent):
        if not self._allowed(event):
            yield event.plain_result("没有权限查询课表。")
            return

        args = parse_schedule_args(event.message_str or "")
        if args["help"]:
            yield event.plain_result(HELP_TEXT)
            return

        action = args["action"]
        if action == "terms":
            try:
                client = self._ensure_client()
                client.bootstrap()
                rows = client.terms()
                yield event.plain_result(
                    format_terms(rows, self._current_term() or (self._state.get("term_key") or ""))
                )
            except JwappError as exc:
                yield event.plain_result(f"学期列表获取失败：{exc}")
            return

        if action == "set_term":
            term = args["term"]
            self._state["term"] = term
            self._save_state()
            try:
                async with self._lock:
                    tt, label = await self._timetable(refresh=True)
                yield event.plain_result(
                    f"已切换到 {label}\n本周：第 {tt.current_week()} 周（{self._header(tt, tt.current_week())}）\n"
                    "发送 /schedule 查看，或 /schedule 学期 默认 切回自动。"
                )
            except JwappError as exc:
                yield event.plain_result(f"切换学期失败：{exc}")
            return

        if action in ("today", "tomorrow"):
            day = date.today() if action == "today" else date.today() + timedelta(days=1)
            try:
                async with self._lock:
                    tt, label = await self._timetable()
                yield event.plain_result(f"{label}\n{format_day(tt.occurrences, day)}")
            except JwappError as exc:
                yield event.plain_result(f"查询失败：{exc}")
            return

        view = args["view"] or str(self._cfg("default_view", "list"))
        try:
            async with self._lock:
                tt, label = await self._timetable(refresh=args["refresh"])
            week = args["week"] or tt.current_week()
            week = max(1, min(week, max(tt.weeks, 1)))
            if view == "grid":
                body = render_grid(tt, week)
            elif view == "json":
                body = render_json(tt, week)
            else:
                body = render_list(tt, week)
            yield event.plain_result(f"{label}\n\n{body}")
        except JwappError as exc:
            yield event.plain_result(f"课表查询失败：{exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("[课表] 查询异常")
            yield event.plain_result(f"课表查询出错：{type(exc).__name__}: {exc}")

    @filter.command("next")
    async def cmd_next(self, event: AstrMessageEvent):
        if not self._allowed(event):
            yield event.plain_result("没有权限查询课表。")
            return
        try:
            async with self._lock:
                tt, label = await self._timetable()
            yield event.plain_result(f"{label}\n{format_next(tt.occurrences, datetime.now())}")
        except JwappError as exc:
            yield event.plain_result(f"查询失败：{exc}")

    @filter.command("today")
    async def cmd_today(self, event: AstrMessageEvent):
        if not self._allowed(event):
            yield event.plain_result("没有权限查询课表。")
            return
        try:
            async with self._lock:
                tt, label = await self._timetable()
            yield event.plain_result(f"{label}\n{format_day(tt.occurrences, date.today())}")
        except JwappError as exc:
            yield event.plain_result(f"查询失败：{exc}")

    @filter.command("tomorrow")
    async def cmd_tomorrow(self, event: AstrMessageEvent):
        if not self._allowed(event):
            yield event.plain_result("没有权限查询课表。")
            return
        try:
            async with self._lock:
                tt, label = await self._timetable()
            yield event.plain_result(
                f"{label}\n{format_day(tt.occurrences, date.today() + timedelta(days=1))}"
            )
        except JwappError as exc:
            yield event.plain_result(f"查询失败：{exc}")

    @filter.command("calibrate")
    async def cmd_calibrate(self, event: AstrMessageEvent):
        if not self._is_admin(event):
            yield event.plain_result("只有管理员能校准周次。")
            return
        args = _strip_command(event.message_str, "calibrate")
        digits = re.sub(r"\D", "", args)
        if not digits:
            yield event.plain_result("用法：/calibrate 5（把本周校准为第 5 周）")
            return
        week = int(digits)
        if not 1 <= week <= 40:
            yield event.plain_result("周次看起来不太对，给个 1~40 的数字吧。")
            return
        try:
            async with self._lock:
                await self._timetable()
            monday = date.today() - timedelta(days=date.today().weekday())
            start = monday - timedelta(weeks=week - 1)
            term_key = self._current_term() or str(self._state.get("term_key", ""))
            if not term_key:
                raise JwappError("还没拿到学期信息，先发一次 /schedule 再校准")
            starts = dict(self._state.get("term_starts") or {})
            starts[term_key] = start.isoformat()
            self._state["term_starts"] = starts
            self._save_state()
            try:
                self._term_cache_file(term_key).unlink()
            except OSError:
                pass
            yield event.plain_result(
                f"已校准：本周为第 {week} 周，教学第一周周一 = {start.isoformat()}。\n"
                f"学期：{term_key}\n之后的查询会按这个来。"
            )
        except JwappError as exc:
            yield event.plain_result(f"校准失败：{exc}")

    @filter.command("status")
    async def cmd_status(self, event: AstrMessageEvent):
        if not self._allowed(event):
            yield event.plain_result("没有权限。")
            return
        try:
            async with self._lock:
                tt, label = await self._timetable()
            week = tt.current_week()
            starts = self._state.get("term_starts") or {}
            term_mode = self._state.get("term") or "自动"
            yield event.plain_result(
                f"学期：{label}（{term_mode}）\n"
                f"教学第一周：{tt.term_start.isoformat()}\n"
                f"本周：第 {week} 周（{self._header(tt, week)}）\n"
                f"课程实例：{len(tt.occurrences)} 条\n"
                f"下节课：{format_next(tt.occurrences, datetime.now())}\n"
                f"校准记录：{starts or '无'}"
            )
        except JwappError as exc:
            yield event.plain_result(f"状态查询失败：{exc}")

    @filter.command("export")
    async def cmd_export(self, event: AstrMessageEvent):
        """把整学期课表导出成 .ics 日历文件（导入手机日历即可）。"""
        if not self._allowed(event):
            yield event.plain_result("没有权限查询课表。")
            return
        try:
            async with self._lock:
                tt, label = await self._timetable()
        except JwappError as exc:
            yield event.plain_result(f"导出失败：{exc}")
            return
        if not tt.occurrences:
            yield event.plain_result(f"{label}\n课表里还没有课程，先 /schedule 刷新 试试。")
            return
        path = DATA_DIR / f"yanhe-{_safe_name(label)}.ics"
        try:
            path.write_text(render_ics(tt, calendar_name=label), encoding="utf-8")
        except OSError as exc:
            yield event.plain_result(f"导出失败：写文件出错（{exc}）")
            return
        yield event.plain_result(
            f"{label}：共 {len(tt.occurrences)} 节课，已生成 .ics 日历文件。"
        )
        yield event.chain_result([File(name=path.name, file=str(path))])

    # ---------------------------------------------------- Agent 函数工具
    async def _tool_week(self, event, week: int = 0, view: str = "list") -> str:
        if not self._allowed(event):
            return "没有权限查询课表。"
        try:
            async with self._lock:
                tt, label = await self._timetable()
            target = week if week and week > 0 else tt.current_week()
            target = max(1, min(target, max(tt.weeks, 1)))
            if view == "grid":
                body = render_grid(tt, target)
            elif view == "json":
                body = render_json(tt, target)
            else:
                body = render_list(tt, target)
            return f"{label}\n\n{body}"
        except JwappError as exc:
            return f"课表查询失败：{exc}"

    @filter.llm_tool(name="yanhe_get_schedule")
    async def tool_get_schedule(
        self, event: AstrMessageEvent, week: int = 0, view: str = "list"
    ):
        """查询延河课表，返回某一周的课程（星期、时间、教室、教师）。

        Args:
            week(number): 教学周次，0 表示本周（默认 0）
            view(string): 输出形式，list=按天清单（默认），grid=课程表表格，json=结构化数据
        """
        return await self._tool_week(event, week=week or 0, view=(view or "list").lower())

    @filter.llm_tool(name="yanhe_get_day_schedule")
    async def tool_get_day(self, event: AstrMessageEvent, day: str = "today"):
        """查询某一天的课程安排。

        Args:
            day(string): today=今天（默认），tomorrow=明天，或具体日期 YYYY-MM-DD
        """
        if not self._allowed(event):
            return "没有权限查询课表。"
        token = (day or "today").strip().lower()
        if token in ("today", "今天", "今日"):
            target = date.today()
        elif token in ("tomorrow", "明天", "明日"):
            target = date.today() + timedelta(days=1)
        else:
            try:
                target = date.fromisoformat(token)
            except ValueError:
                return "日期格式不对，请用 today / tomorrow / YYYY-MM-DD。"
        try:
            async with self._lock:
                tt, label = await self._timetable()
            return f"{label}\n{format_day(tt.occurrences, target)}"
        except JwappError as exc:
            return f"查询失败：{exc}"

    @filter.llm_tool(name="yanhe_next_class")
    async def tool_next_class(self, event: AstrMessageEvent):
        """查询最近的一节课（包括正在上的课），返回课程名、时间、教室、教师。"""
        if not self._allowed(event):
            return "没有权限查询课表。"
        try:
            async with self._lock:
                tt, _label = await self._timetable()
            return format_next(tt.occurrences, datetime.now())
        except JwappError as exc:
            return f"查询失败：{exc}"

    @filter.llm_tool(name="yanhe_list_terms")
    async def tool_list_terms(self, event: AstrMessageEvent):
        """列出教务系统里的所有学期，并标出当前学期。"""
        if not self._allowed(event):
            return "没有权限查询课表。"
        try:
            client = self._ensure_client()
            client.bootstrap()
            rows = client.terms()
            return format_terms(rows, self._current_term() or (self._state.get("term_key") or ""))
        except JwappError as exc:
            return f"学期列表获取失败：{exc}"

    @filter.llm_tool(name="yanhe_switch_term")
    async def tool_switch_term(self, event: AstrMessageEvent, term: str):
        """切换要查询的学期；传空字符串表示恢复自动（跟随教务当前学期）。

        Args:
            term(string): 学期代码，如 2026-2027-1；传 "" 表示自动
        """
        if not self._allowed(event):
            return "没有权限。"
        self._state["term"] = (term or "").strip()
        self._save_state()
        try:
            async with self._lock:
                tt, label = await self._timetable(refresh=True)
        except JwappError as exc:
            return f"切换学期失败：{exc}"
        return f"已切换到 {label}，本周第 {tt.current_week()} 周。"

    @filter.llm_tool(name="yanhe_calibrate_week")
    async def tool_calibrate(self, event: AstrMessageEvent, week: int):
        """把「本周」校准为指定教学周次，用于教务偏移数据不准时修正。仅管理员可用。

        Args:
            week(number): 本周实际是第几周，例如 5
        """
        if not self._is_admin(event):
            return "只有管理员能校准周次。"
        try:
            week = int(week)
        except (TypeError, ValueError):
            return "周次需要是数字。"
        if not 1 <= week <= 40:
            return "周次看起来不太对，给个 1~40 的数字。"
        try:
            async with self._lock:
                await self._timetable()
            monday = date.today() - timedelta(days=date.today().weekday())
            start = monday - timedelta(weeks=week - 1)
            term_key = self._current_term() or str(self._state.get("term_key", ""))
            if not term_key:
                return "还没拿到学期信息，先查询一次课表再校准。"
            starts = dict(self._state.get("term_starts") or {})
            starts[term_key] = start.isoformat()
            self._state["term_starts"] = starts
            self._save_state()
            try:
                self._term_cache_file(term_key).unlink()
            except OSError:
                pass
            return f"已校准：本周为第 {week} 周，教学第一周周一 = {start.isoformat()}。"
        except JwappError as exc:
            return f"校准失败：{exc}"
