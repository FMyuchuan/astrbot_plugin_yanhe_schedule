# -*- coding: utf-8 -*-
"""插件里与 AstrBot 无关的纯函数：参数解析、文本格式化。

单独放一份，方便离线单测（不依赖 astrbot 包）。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

VIEW_ALIASES = {
    "表格": "grid",
    "grid": "grid",
    "列表": "list",
    "list": "list",
    "json": "json",
}

HELP_TEXT = (
    "课表查询用法：\n"
    "  /schedule                    本周\n"
    "  /schedule 9                  第 9 周\n"
    "  /schedule 9 表格             表格样式（grid / json / list 也认）\n"
    "  /schedule 今天 / 明天        今天 / 明天（today / tomorrow 同义）\n"
    "  /schedule 刷新               忽略缓存重新拉取\n"
    "  /schedule 学期               列出所有学期\n"
    "  /schedule 学期 2026-2027-1   切换到指定学期\n"
    "  /next                        最近的一节课\n"
    "  /today  /tomorrow            今天 / 明天\n"
    "  /status                      学期、教学第一周、缓存状态\n"
    "  /export                      整学期导出 .ics 日历文件\n"
    "  /login                       登录教务（需要短信/图形验证码时按提示继续）\n"
    "  /code 123456                 提交短信或图形验证码\n"
    "  /cancel_login                放弃当前登录\n"
    "  /calibrate 5                 把本周校准为第 5 周（管理员）"
)


def parse_schedule_args(text: str) -> dict:
    """解析 /schedule 后面的参数。

    返回 {week, view, refresh, action, term, help}
    action: "" | "today" | "tomorrow" | "terms" | "set_term" | "help"
    """
    result = {
        "week": None,
        "view": None,
        "refresh": False,
        "action": "",
        "term": "",
        "help": False,
    }
    tokens = (text or "").replace("/", " ").split()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        lower = token.lower()
        if token in ("帮助", "help") or lower in ("-h", "--help", "?"):
            result["help"] = True
        elif token in VIEW_ALIASES:
            result["view"] = VIEW_ALIASES[token]
        elif token in ("刷新", "--refresh", "-r") or lower == "refresh":
            result["refresh"] = True
        elif token in ("今天", "今日") or lower == "today":
            result["action"] = "today"
        elif token in ("明天", "明日") or lower == "tomorrow":
            result["action"] = "tomorrow"
        elif token in ("学期", "terms") or lower == "terms":
            nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
            if re.match(r"^\d{4}-\d{4}-\d$", nxt):
                result["action"] = "set_term"
                result["term"] = nxt
                index += 1
            elif nxt in ("默认", "自动", "auto"):
                result["action"] = "set_term"
                result["term"] = ""
                index += 1
            else:
                result["action"] = "terms"
        elif token.isdigit():
            result["week"] = int(token)
        elif token.startswith("第") and token.endswith("周"):
            digits = re.sub(r"\D", "", token)
            if digits:
                result["week"] = int(digits)
        index += 1
    return result


def format_day(events, day: date) -> str:
    """把一个日期下的课程排成一段文字。"""
    daily = sorted([o for o in events if o.start.date() == day], key=lambda o: o.start)
    title = f"{day.strftime('%m-%d')} {WEEKDAY_NAMES[day.weekday()]}"
    if not daily:
        return f"{title}：没有课，休息一下。"
    lines = [title]
    for occurrence in daily:
        parts = [
            f"{occurrence.start.strftime('%H:%M')}-{occurrence.end.strftime('%H:%M')}",
            occurrence.summary,
        ]
        if getattr(occurrence, "location", ""):
            parts.append(f"@{occurrence.location}")
        if getattr(occurrence, "teacher", ""):
            parts.append(occurrence.teacher)
        lines.append("  " + "  ".join(parts))
    return "\n".join(lines)


def next_class(events, now: datetime):
    """返回下一节课（含正在上的），没有则 None。"""
    upcoming = [
        o
        for o in events
        if o.end > now and o.start.date() <= (now + timedelta(days=14)).date()
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda o: o.start)


def format_next(events, now: datetime) -> str:
    occurrence = next_class(events, now)
    if occurrence is None:
        return "最近两周没有课。"
    delta = occurrence.start - now
    if occurrence.start <= now <= occurrence.end:
        head = "正在上："
    else:
        hours = delta.total_seconds() / 3600
        if hours < 1:
            head = f"{int(delta.total_seconds() // 60)} 分钟后："
        elif hours < 24:
            head = f"{hours:.1f} 小时后："
        else:
            head = f"{occurrence.start.strftime('%m-%d')}："
    where = f"@{occurrence.location}" if occurrence.location else ""
    teacher = f"  {occurrence.teacher}" if occurrence.teacher else ""
    return (
        f"{head}{occurrence.start.strftime('%m-%d %H:%M')}-"
        f"{occurrence.end.strftime('%H:%M')}  {occurrence.summary} {where}{teacher}"
    ).replace("  ", " ")


def format_terms(rows, current: str) -> str:
    if not rows:
        return "没拿到学期列表。"
    lines = ["可选学期："]
    for row in rows:
        mark = " ← 当前" if row.get("dm") == current else ""
        lines.append(f"  {row['dm']}  {row.get('mc', '')}{mark}")
    lines.append("切换：/schedule 学期 2026-2027-1")
    return "\n".join(lines)
