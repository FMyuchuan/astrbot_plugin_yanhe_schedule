# Changelog

## v0.2.0 (2026-10-26)

维护轮：修掉一批并发 / 权限 / 边界问题，补上 `.ics` 导出与测试。

修复：

- `/登录`、`/验证码`、`/取消登录` 之前只受 `allowed_users` 约束，`allowed_users`
  留空时任何人都能触发登录（会消耗真实短信、改写全局会话）。现在登录类命令统一走
  `admin_users`，留空才退回 `allowed_users`
- `/取消登录` 之前完全没有权限检查，任何人一条消息就能打断正在进行的登录
- 登录 / 验证码续跑与课表抓取现在共用同一把线程锁，避免并发改写 `requests.Session`
  导致 cookie 互相覆盖
- 图形验证码输错时不再清空待验证状态，可以直接重发 `/验证码` 重试，不用从头 `/登录`
- 读取课表缓存时对 `cache_hours` 配置做容错，缓存字段缺失当作未命中，不再抛 `KeyError`
- 网格渲染里同格冲突顺延可能把课推到 13 节之外、渲染成错位行，现在越界直接丢弃并裁剪跨度
- `parse_weeks` 的 `mask` 参数改为可选（之前调用方必须占位传参）
- 手动指定学期且无缓存时，顺手解析学期中文名，不再把 `2026-2027-1` 直接当标题

新增：

- `/导出`：整学期导出 `.ics` 日历文件（复用此前未被调用的 `core/render.render_ics`）
- `JwappClient.pending_kind()`：插件不再直接读 `_pending` 私有字段
- `session.json` 落盘后 `chmod 600`，登录 cookie 只给属主读
- 测试从 1 个文件 14 个用例扩到 5 个文件 83 个用例，覆盖 `schedule` / `campus` / `ics` / `render`

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
