# -*- coding: utf-8 -*-
"""登录时用到的小工具：请求头、页面字段解析。

这里只做通用的表单/页面处理，不包含任何账号信息。
"""

from __future__ import annotations

import base64
import hashlib
import random
import re
import string

SSO_BASE = "https://sso.bit.edu.cn"


def _csrf_headers(key: str | None = None) -> dict:
    """生成一对请求头，供需要校验的登录接口使用。"""
    key = key or "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(32)
    )
    encoded = base64.b64encode(key.encode()).decode()
    half = len(encoded) // 2
    sandwich = encoded[:half] + encoded + encoded[half:]
    return {
        "Csrf-Key": key,
        "Csrf-Value": hashlib.md5(sandwich.encode()).hexdigest(),
    }


def _inner_text(html: str, element_id: str) -> str:
    match = re.search(
        rf'<p[^>]*id="{re.escape(element_id)}"[^>]*>(.*?)</p>', html, re.S | re.I
    )
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _login_error(html: str) -> str:
    for text in (
        "用户名或密码错误",
        "账号或密码错误",
        "密码错误",
        "验证码错误",
        "验证码已失效",
        "用户不存在",
        "账号已被锁定",
        "账号已冻结",
        "需要验证码",
    ):
        if text in html:
            return f"登录失败：{text}" if text == "需要验证码" else text
    return ""
