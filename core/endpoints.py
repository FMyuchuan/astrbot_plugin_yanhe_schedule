"""教务系统的接口端点常量。

jwapp（数据接口）与 cas_login（登录流程）共用，避免两边各自硬编码 URL。
"""

BASE = "https://jxzxehallapp.bit.edu.cn"
ENTRY = BASE + "/jwapp/sys/wdkbby/*default/index.do"

SCHEDULE_APP = "/jwapp/sys/wdkbby/*default/index.do"
APP_CONFIG = "/jwapp/sys/funauthapp/api/getAppConfig/wdkbby-5959167891382285.do"
I18N = "/jwapp/i18n.do?appName=wdkbby&EMAP_LANG=zh"
CURRENT_TERM = "/jwapp/sys/wdkbby/modules/jshkcb/dqxnxq.do"
ALL_TERMS = "/jwapp/sys/wdkbby/modules/jshkcb/xnxqcx.do"
TERM_SCHEDULE = "/jwapp/sys/wdkbby/modules/xskcb/cxxszhxqkb.do"
WEEK_DATES = "/jwapp/sys/wdkbby/wdkbByController/cxzkbrq.do"
# 教学周偏移：教务「第 1 周」是校历周，课表上的第 1 教学周 = 校历周 1 + offset
WEEK_OFFSET = "/jwapp/sys/wdkbby/modules/jshkcb/cxtqzc.do"


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
