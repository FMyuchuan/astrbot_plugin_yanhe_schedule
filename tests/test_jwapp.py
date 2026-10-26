# -*- coding: utf-8 -*-
"""core.jwapp 单测：重试策略、超时、待验证状态（不联网）。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from core.jwapp import JwappClient, JwappError  # noqa: E402


class FakeResponse:
    def __init__(self, status=200, text="", url="https://example.invalid/x"):
        self.status_code = status
        self.text = text
        self.url = url
        self.headers = {}

    def json(self):
        return {}


def make_client(script):
    """script 里放 FakeResponse 或异常实例，按顺序返回。"""
    client = JwappClient(retries=2)
    calls = []
    queue = list(script)

    def fake_request(method, url, timeout=None, **kwargs):
        calls.append((method, url, timeout, kwargs))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    client.s.request = fake_request
    return client, calls


class RetryTest(unittest.TestCase):
    def test_get_retries_on_503_then_succeeds(self):
        client, calls = make_client([FakeResponse(503), FakeResponse(200, "ok")])
        with mock.patch("core.jwapp.time.sleep"):
            resp = client.get("/some/path")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(calls), 2)

    def test_get_gives_up_after_retries(self):
        client, calls = make_client([FakeResponse(503), FakeResponse(503), FakeResponse(503)])
        with mock.patch("core.jwapp.time.sleep"):
            with self.assertRaises(JwappError):
                client.get("/some/path")
        self.assertEqual(len(calls), 3)  # 1 次原始 + 2 次重试

    def test_post_is_not_retried_by_default(self):
        """短信验证码接口是 POST，重试会重复发短信，必须只发一次。"""
        client, calls = make_client([FakeResponse(500)])
        with mock.patch("core.jwapp.time.sleep"):
            with self.assertRaises(JwappError):
                client.post_form("/sms", {"phone": "1"})
        self.assertEqual(len(calls), 1)

    def test_post_can_opt_in_to_retry(self):
        client, calls = make_client([FakeResponse(502), FakeResponse(200, "ok")])
        with mock.patch("core.jwapp.time.sleep"):
            resp = client._req("POST", "/x", retry=True, data={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(calls), 2)

    def test_timeout_becomes_jwapp_error(self):
        client, calls = make_client([requests.Timeout("boom")] * 3)
        with mock.patch("core.jwapp.time.sleep"):
            with self.assertRaises(JwappError) as ctx:
                client.get("/slow")
        self.assertIn("超时", str(ctx.exception))
        self.assertEqual(len(calls), 3)

    def test_connection_error_retried(self):
        client, calls = make_client(
            [requests.ConnectionError("dns"), FakeResponse(200, "ok")]
        )
        with mock.patch("core.jwapp.time.sleep"):
            resp = client.get("/flaky")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(calls), 2)

    def test_timeout_tuple_is_connect_read(self):
        client, calls = make_client([FakeResponse(200)])
        client.get("/x")
        self.assertEqual(calls[0][2], (10.0, 25.0))

    def test_login_required_detected(self):
        client, _ = make_client(
            [FakeResponse(200, "ok", url="https://sso.bit.edu.cn/cas/login?x=1")]
        )
        with self.assertRaises(Exception) as ctx:
            client.get("/x")
        self.assertIn("会话已失效", str(ctx.exception))


class PendingStateTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(JwappClient().pending_kind(), "")

    def test_login_captcha(self):
        client = JwappClient()
        client._pending = {"kind": "login_captcha"}
        self.assertEqual(client.pending_kind(), "login_captcha")

    def test_sms_captcha(self):
        client = JwappClient()
        client._pending = {"kind": "sms_captcha"}
        self.assertEqual(client.pending_kind(), "sms_captcha")

    def test_sms_waiting(self):
        client = JwappClient()
        client._pending_sms = {"phone": "138****"}
        self.assertEqual(client.pending_kind(), "sms")


class CookieTest(unittest.TestCase):
    def test_roundtrip(self):
        source = JwappClient()
        source.s.cookies.set("JSESSIONID", "abc", domain="jxzxehallapp.bit.edu.cn", path="/")
        data = source.cookie_data()
        target = JwappClient()
        target.load_cookies(data)
        self.assertEqual(target.s.cookies.get("JSESSIONID"), "abc")

    def test_broken_items_ignored(self):
        client = JwappClient()
        client.load_cookies([{}, {"name": "x"}])  # 不该抛异常
        self.assertEqual(client.pending_kind(), "")


if __name__ == "__main__":
    unittest.main()
