"""教务系统客户端：课表等数据接口（登录流程见 core/cas_login.py）。

仅用于查询当前账号自己的课表。
"""

from __future__ import annotations

import json
import time

import requests

from .cas_login import CasLoginMixin
from .errors import (  # noqa: F401  re-export，main.py 仍从这里取异常类型
    CaptchaChallenge,
    JwappError,
    LoginChallenge,
    LoginRequired,
    SmsChallenge,
)

from .endpoints import (  # noqa: F401  其余常量留给外部直接 import
    ALL_TERMS,
    APP_CONFIG,
    BASE,
    CURRENT_TERM,
    ENTRY,
    I18N,
    SCHEDULE_APP,
    TERM_SCHEDULE,
    UA,
    WEEK_DATES,
    WEEK_OFFSET,
)


class JwappClient(CasLoginMixin):
    """教务接口客户端；登录流程见 core/cas_login.py。"""

    # 教务高峰期常见的临时故障码，值得重试
    RETRY_STATUS = (429, 500, 502, 503, 504)

    def __init__(self, timeout: float = 25.0, connect_timeout: float = 10.0, retries: int = 2):
        self.timeout = (connect_timeout, timeout)
        self.retries = max(0, int(retries))
        self.s = requests.Session()
        self._pending = None
        self._pending_sms = None
        self.s.headers.update(
            {
                "User-Agent": UA,
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )

    # ------------------------------------------------------------- cookie
    def cookie_data(self) -> list[dict]:
        return [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self.s.cookies
        ]

    def load_cookies(self, data) -> None:
        for item in data or []:
            try:
                self.s.cookies.set(
                    item["name"], item["value"], domain=item.get("domain", ""), path=item.get("path", "/")
                )
            except Exception:
                continue

    # --------------------------------------------------------------- http
    def _req(self, method: str, url: str, *, retry: bool | None = None, **kwargs):
        """带重试的请求。

        只有 GET 默认重试（幂等）；POST 一律不重试，避免短信验证码被重复发送。
        需要重试 POST 时显式传 ``retry=True``。
        """
        if not url.startswith("http"):
            url = BASE + url
        attempts = self.retries if (retry if retry is not None else method.upper() == "GET") else 0
        last_error: JwappError | None = None

        for attempt in range(attempts + 1):
            try:
                resp = self.s.request(method, url, timeout=self.timeout, **kwargs)
            except requests.Timeout:
                last_error = JwappError("请求教务超时，稍后再试（网络或教务繁忙）")
            except requests.RequestException as exc:
                last_error = JwappError(f"网络请求失败：{exc}")
            else:
                if resp.status_code not in self.RETRY_STATUS or attempt >= attempts:
                    return resp
                last_error = JwappError(f"教务返回 HTTP {resp.status_code}，稍后再试")
            if attempt < attempts:
                time.sleep(min(0.5 * (2 ** attempt), 4))
        raise last_error or JwappError("请求失败")

    def get(self, path: str, **kwargs):
        resp = self._req("GET", path, **kwargs)
        if "/auth-protocol-core/login" in (resp.url or "") or "cas/login" in (resp.url or ""):
            raise LoginRequired("教务会话已失效，请重新登录")
        if resp.status_code >= 400:
            raise JwappError(f"请求失败：HTTP {resp.status_code}")
        return resp

    def post_form(self, path: str, data: dict, **kwargs):
        headers = {"X-Requested-With": "XMLHttpRequest", "Referer": BASE + SCHEDULE_APP}
        headers.update(kwargs.pop("headers", {}) or {})
        resp = self._req("POST", path, data=data, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise JwappError(f"请求失败：HTTP {resp.status_code}")
        return resp

    def _json(self, resp) -> dict:
        try:
            return resp.json()
        except ValueError:
            raise JwappError("教务接口返回的不是 JSON（可能登录态失效）")

    # ------------------------------------------------------------ 课表数据
    def verify(self) -> bool:
        try:
            resp = self._req("GET", ENTRY, allow_redirects=True)
        except JwappError:
            return False
        if "/auth-protocol-core/login" in (resp.url or "") or "cas/login" in (resp.url or ""):
            return False
        text = resp.text or ""
        return "jwapp" in text or "wdkbby" in text

    def bootstrap(self) -> None:
        self.get(SCHEDULE_APP)
        self.get(APP_CONFIG)
        try:
            self.get(I18N)
        except JwappError:
            pass

    def current_term(self) -> dict:
        data = self._json(self.get(CURRENT_TERM))
        rows = _dig(data, "datas", "dqxnxq", "rows") or []
        if not rows:
            raise JwappError("拿不到当前学期")
        return {"dm": rows[0].get("DM"), "mc": rows[0].get("MC")}

    def terms(self) -> list[dict]:
        data = self._json(self.get(ALL_TERMS))
        rows = _dig(data, "datas", "xnxqcx", "rows") or []
        return [{"dm": r.get("DM"), "mc": r.get("MC"), "sfsy": r.get("SFSY")} for r in rows if r.get("DM")]

    def schedule_rows(self, term: str) -> list[dict]:
        data = self._json(self.post_form(TERM_SCHEDULE, {"XNXQDM": term}))
        rows = _dig(data, "datas", "cxxszhxqkb", "rows")
        if rows is None:
            message = _dig(data, "datas", "cxxszhxqkb", "extParams", "msg") or "返回结构异常"
            raise JwappError(f"课表查询失败：{message}")
        return rows

    def week_dates(self, term: str, week: int = 1) -> list[dict]:
        payload = json.dumps({"XNXQDM": term, "ZC": str(week)}, ensure_ascii=False)
        data = self._json(self.post_form(WEEK_DATES, {"requestParamStr": payload}))
        return data.get("data") or []

    def week_offset(self, term: str) -> int:
        """教学周相对校历周的偏移（教务课表页面里的 KBXSTQZC / BITKBXSTQJZ）。"""
        try:
            data = self._json(self.post_form(WEEK_OFFSET, {"XNXQDM": term}))
        except JwappError:
            return 0
        rows = _dig(data, "datas", "cxtqzc", "rows") or []
        try:
            return int(str(rows[0].get("BITKBXSTQJZ") or 0)) if rows else 0
        except (TypeError, ValueError):
            return 0


def _dig(data, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
