"""CAS 统一身份认证的登录流程：密码 / 图形验证码 / 短信二次验证。

从 jwapp.py 拆出来：这里只管「怎么登进教务」，
HTTP 会话与课表接口留在 jwapp.py。两者通过 JwappClient 的 ``_req`` 组合。
"""

from __future__ import annotations

import sys
from urllib.parse import urljoin

from . import crypto
from .cas import SSO_BASE, _csrf_headers, _inner_text, _login_error
from .endpoints import ENTRY
from .errors import CaptchaChallenge, JwappError, SmsChallenge

SMS_SEND_API = SSO_BASE + "/cas/api/protected/sms/publicNoToken/sendSmsCode"

SMS_SEND_API_FALLBACK = SSO_BASE + "/gate/api/protected/sms/publicNoToken/sendSmsCode"

CAPTCHA_API = SSO_BASE + "/cas/api/protected/captcha/generate/DEFAULT"

CAPTCHA_VALIDATE_API = SSO_BASE + "/cas/api/protected/captcha/validate"


class CasLoginMixin:
    """登录相关方法，由 JwappClient 混入使用。"""

    # ---------------------------------------------------------------- 登录
    def _cas_login_url(self) -> str:
        """跟着未登录跳转，拿到带 service 的 CAS 登录页地址。"""
        resp = self._req("GET", ENTRY, allow_redirects=False)
        loc = resp.headers.get("Location") or ""
        if not loc:
            return ""
        first = urljoin(ENTRY, loc)
        resp2 = self._req("GET", first, allow_redirects=False)
        loc2 = resp2.headers.get("Location") or ""
        if not loc2:
            return ""
        return urljoin(first, loc2)

    def login(
        self,
        sid: str,
        password: str,
        sms_code: str = "",
        sms_solver=None,
        captcha_solver=None,
        debug: bool = False,
    ) -> None:
        def log(message: str) -> None:
            if debug:
                print(f"[login] {message}", file=sys.stderr)

        if self.verify():
            log("已有有效教务会话，跳过登录")
            return

        login_url = self._cas_login_url()
        if not login_url:
            raise JwappError("拿不到 CAS 登录地址（教务入口可能改版）")
        log(f"CAS 登录页 → {login_url[:110]}")

        page = self._req("GET", login_url, allow_redirects=True)
        html = page.text or ""
        if "login-croypto" not in html:
            raise JwappError("没有拿到统一身份认证登录页")
        croypto = _inner_text(html, "login-croypto")
        flowkey = _inner_text(html, "login-page-flowkey")

        form = {
            "type": "UsernamePassword",
            "_eventId": "submit",
            "geolocation": "",
            "execution": flowkey,
            "croypto": croypto,
            "username": sid,
            "password": crypto.encrypt_cas_password(password, croypto),
        }

        captcha_url = _inner_text(html, "captcha-url")
        if captcha_url:
            image = self._req("GET", SSO_BASE + captcha_url)
            if captcha_solver is None:
                self._pending = {
                    "kind": "login_captcha",
                    "page_url": page.url,
                    "croypto": croypto,
                    "flowkey": flowkey,
                    "sid": sid,
                    "password": password,
                }
                raise CaptchaChallenge(image.content or b"", "login")
            form["captcha"] = captcha_solver(image.content or b"") or ""

        result = self._req(
            "POST",
            page.url,
            data=form,
            headers={"Referer": page.url, "Origin": SSO_BASE},
            allow_redirects=False,
        )
        log(f"POST 密码 → {result.status_code}")

        self._handle_login_result(
            result,
            sid,
            sms_code=sms_code,
            sms_solver=sms_solver,
            captcha_solver=captcha_solver,
            log=log,
        )
        log("登录成功，教务 cookie 已获取")

    def _handle_login_result(
        self,
        result,
        sid: str,
        *,
        sms_code: str = "",
        sms_solver=None,
        captcha_solver=None,
        log=None,
    ) -> None:
        login_type = _inner_text(result.text or "", "current-login-type")
        if login_type == "smsLogin":
            text = result.text or ""
            phone = _inner_text(text, "phone-number")
            user = _inner_text(text, "second-auth-user-id") or sid
            self._pending_sms = {
                "page_url": result.url,
                "flowkey": _inner_text(text, "login-page-flowkey"),
                "user": user,
                "phone": phone,
                "sid": sid,
            }

            if sms_solver is None and not sms_code:
                if not self._send_sms_challenge(phone, log=log):
                    raise JwappError("短信验证码发送失败，请稍后重试")
                raise SmsChallenge(phone)

            result = self._submit_sms(
                result,
                sid,
                sms_code=sms_code,
                sms_solver=sms_solver,
                captcha_solver=captcha_solver,
                log=log,
            )
            if _inner_text(result.text or "", "current-login-type") == "smsLogin":
                raise JwappError(
                    _login_error(result.text or "") or "短信验证码没有通过"
                )
        elif login_type and login_type != "UsernamePassword":
            raise JwappError(f"学校要求「{login_type}」二次认证，暂时只支持短信")

        self._finish(result, log=log)

    def _finish(self, result, log=None):
        location = result.headers.get("Location") or ""
        if location:
            target = urljoin(result.url, location)
            if log:
                log(f"CAS 跳转 → {target[:110]}")
            final = self._req("GET", target, allow_redirects=True)
            if log:
                log(f"落地 → {final.status_code} {final.url[:100]}")
        else:
            final = result

        if "jwapp" not in (final.text or "") and "wdkbby" not in (final.text or ""):
            check = self._req("GET", ENTRY, allow_redirects=True)
            if "jwapp" not in (check.text or "") and "wdkbby" not in (check.text or ""):
                raise JwappError("登录后仍然打不开课表模块")
        return final

    def _post_sms_once(self, phone: str):
        for url in (SMS_SEND_API, SMS_SEND_API_FALLBACK):
            try:
                resp = self._req(
                    "POST",
                    url,
                    json={"phone": phone, "businessNo": "0008"},
                    headers={"Content-Type": "application/json", **_csrf_headers()},
                )
            except JwappError:
                continue
            if resp.status_code == 404:
                continue
            try:
                payload = resp.json()
            except ValueError:
                continue
            if payload.get("code") == 200:
                return True, payload
            data = payload.get("data") or {}
            if isinstance(data, dict) and (data.get("status") or data.get("result")):
                return True, payload
            return False, payload
        return False, {}

    def _send_sms_challenge(self, phone: str, log=None) -> bool:
        ok, payload = self._post_sms_once(phone)
        if ok:
            return True
        data = payload.get("data") if isinstance(payload, dict) else None
        error_code = data.get("errorCode") if isinstance(data, dict) else None
        if log:
            log(f"发送短信失败：errorCode={error_code}")
        if error_code in (60008, 1320007):
            headers = _csrf_headers()
            image = self._req("GET", CAPTCHA_API, headers=headers)
            pending = dict(self._pending_sms or {})
            pending.update({"kind": "sms_captcha", "phone": phone})
            self._pending = pending
            raise CaptchaChallenge(image.content or b"", "sms")
        return False

    def _validate_captcha(self, code: str) -> bool:
        headers = _csrf_headers()
        resp = self._req(
            "POST",
            CAPTCHA_VALIDATE_API,
            json={"type": "DEFAULT", "code": code, "delete": False},
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            return resp.json().get("code") == 200
        except ValueError:
            return False

    # ---------------------------------------------------------- 人工验证续跑
    def pending_kind(self) -> str:
        """当前待人工处理的验证类型。

        返回 ``""``（无）/ ``login_captcha`` / ``sms_captcha`` / ``sms``。
        插件据此决定 /code 应该喂给图形验证码还是短信验证码，
        不必再窥探 ``_pending`` 这类私有字段。
        """
        if isinstance(self._pending, dict):
            kind = str(self._pending.get("kind") or "")
            if kind:
                return kind
        if isinstance(self._pending_sms, dict):
            return "sms"
        return ""

    def resume_captcha(self, code: str) -> None:
        pending = self._pending
        if not pending:
            raise JwappError("没有待处理的图形验证码，请重新 /login")

        if pending["kind"] == "login_captcha":
            form = {
                "type": "UsernamePassword",
                "_eventId": "submit",
                "geolocation": "",
                "execution": pending["flowkey"],
                "croypto": pending["croypto"],
                "username": pending["sid"],
                "password": crypto.encrypt_cas_password(
                    pending["password"], pending["croypto"]
                ),
                "captcha": code,
            }
            result = self._req(
                "POST",
                pending["page_url"],
                data=form,
                headers={"Referer": pending["page_url"], "Origin": SSO_BASE},
                allow_redirects=False,
            )
            # 先判错再清空待处理状态：图形验证码可能只是看错了，
            # 保留 pending 才能让用户直接重试，而不用从头 /login。
            message = _login_error(result.text or "")
            if message:
                raise JwappError(f"{message}（可重新发送 /code 再试一次）")
            self._pending = None
            self._handle_login_result(result, pending["sid"])
            return

        if pending["kind"] == "sms_captcha":
            if not self._validate_captcha(code):
                raise JwappError("图形验证码不正确，请重新输入")
            ok, _payload = self._post_sms_once(pending["phone"])
            self._pending = None
            if not ok:
                self._pending_sms = None
                raise JwappError("短信发送失败，请稍后重试")
            raise SmsChallenge(pending["phone"])

        raise JwappError("未知的验证码状态")

    def resume_sms(self, code: str) -> None:
        pending = self._pending_sms
        if not pending:
            raise JwappError("没有待处理的短信验证码，请重新 /login")
        form = {
            "type": "smsLogin",
            "_eventId": "submit",
            "geolocation": "",
            "execution": pending["flowkey"],
            "username": pending["user"],
            "password": code,
            "captcha_code": "",
            "rememberMe": "false",
        }
        result = self._req(
            "POST",
            pending["page_url"],
            data=form,
            headers={"Referer": pending["page_url"], "Origin": SSO_BASE},
            allow_redirects=False,
        )
        self._pending_sms = None
        if _inner_text(result.text or "", "current-login-type") == "smsLogin":
            raise JwappError(
                _login_error(result.text or "") or "短信验证码不正确或已过期"
            )
        self._finish(result)

    def _submit_sms(self, page, sid, *, sms_code="", sms_solver=None, captcha_solver=None, log=None):
        text = page.text or ""
        flowkey = _inner_text(text, "login-page-flowkey")
        phone = _inner_text(text, "phone-number")
        user = _inner_text(text, "second-auth-user-id") or sid
        if not sms_code:
            if sms_solver is None:
                raise JwappError("学校要求短信验证码，但当前不是交互环境")
            self._send_sms(phone, captcha_solver=captcha_solver, log=log)
            sms_code = sms_solver(phone) or ""
        form = {
            "type": "smsLogin",
            "_eventId": "submit",
            "geolocation": "",
            "execution": flowkey,
            "username": user,
            "password": sms_code,
            "captcha_code": "",
            "rememberMe": "false",
        }
        result = self._req(
            "POST",
            page.url,
            data=form,
            headers={"Referer": page.url, "Origin": SSO_BASE},
            allow_redirects=False,
        )
        if log:
            log(f"POST 短信验证码 → {result.status_code}")
        loc = result.headers.get("Location") or ""
        if loc:
            target = urljoin(page.url, loc)
            if log:
                log(f"CAS 跳转 → {target[:110]}")
            result = self._req("GET", target, allow_redirects=True)
        return result

    def _send_sms(self, phone: str, *, captcha_solver=None, log=None) -> bool:
        if not phone:
            return False
        for url in (SMS_SEND_API, SMS_SEND_API_FALLBACK):
            try:
                resp = self._req(
                    "POST",
                    url,
                    json={"phone": phone, "businessNo": "0008"},
                    headers={"Content-Type": "application/json", **_csrf_headers()},
                )
            except JwappError:
                continue
            if resp.status_code == 404:
                continue
            try:
                payload = resp.json()
            except ValueError:
                continue
            if log:
                log(f"发送验证码 → {resp.status_code} {(resp.text or '')[:120]}")
            if payload.get("code") == 200:
                return True
            data = payload.get("data") or {}
            if isinstance(data, dict) and data.get("errorCode") in (60008, 1320007):
                if captcha_solver is None:
                    return False
                self._solve_captcha(captcha_solver, log=log)
            else:
                return False
        return False

    def _solve_captcha(self, captcha_solver, log=None) -> bool:
        headers = _csrf_headers()
        image = self._req("GET", CAPTCHA_API, headers=headers)
        code = (captcha_solver(image.content) or "").strip()
        if not code:
            return False
        resp = self._req(
            "POST",
            CAPTCHA_VALIDATE_API,
            json={"type": "DEFAULT", "code": code, "delete": False},
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            ok = resp.json().get("code") == 200
        except ValueError:
            ok = False
        if log:
            log(f"图形验证码校验 → {ok}")
        return ok
