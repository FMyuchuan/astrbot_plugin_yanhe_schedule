# Changelog

## v0.1.0 (2026-10-26)

首个版本。

- 聊天命令：`/课表`、`/课表 N`、`/课表 今天|明天`、`/下节课`、`/今日`、`/明日`
- 学期：`/课表 学期` 列表、`/课表 学期 <代码>` 切换
- 周次：读取教务的教学周偏移自动对齐，`/校准 N` 可手动修正
- 登录：`/登录` + `/验证码`，支持短信与图形验证码；待验证状态在内存中
- Agent 工具：`yanhe_get_schedule`、`yanhe_get_day_schedule`、`yanhe_next_class`、
  `yanhe_list_terms`、`yanhe_switch_term`、`yanhe_calibrate_week`
- 缓存：课表默认缓存 6 小时，`/课表 刷新` 强制更新
- 权限：`allowed_users` 控制查询，`admin_users` 控制校准
- 测试：纯函数单测 + GitHub Actions
