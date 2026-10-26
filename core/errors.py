"""插件用到的异常类型。

单独放一份，避免 jwapp（教务接口）与 cas_login（登录流程）互相 import。
"""

class JwappError(Exception):
    pass


class LoginRequired(JwappError):
    pass


class LoginChallenge(JwappError):
    """登录需要人工介入（短信/图形验证码）。"""


class CaptchaChallenge(LoginChallenge):
    def __init__(self, image: bytes, purpose: str = "login"):
        super().__init__("需要图形验证码")
        self.image = image
        self.purpose = purpose


class SmsChallenge(LoginChallenge):
    def __init__(self, phone: str):
        super().__init__("需要短信验证码")
        self.phone = phone
