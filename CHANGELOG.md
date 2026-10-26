# Changelog

## v0.3.3 (2026-10-26)

周次偏移实证 + 修一个真 bug。

实证（2026-2027-1，用真实账号数据核对）：

- `WEEK_OFFSET` 接口返回 `BITKBXSTQJZ = 3`
- `week_dates(term, 4)` 的周一 = `2026-09-21`，与缓存里的 `term_start` 完全一致
- `SKZC` 位图交叉验证：`0001111111111111111` 对应「1-16周」，教学第 1 周落在校历第 4 位
- 结论：**教学第 n 周 = 校历第 (n + offset) 周**，`week_dates(term, 1 + offset)`
  取教学第一周周一是正确写法，无需改动

修复：

- `parse_weeks` 在 `ZCMC` 解析不出、退回 `SKZC` 位图时，把**校历周**直接当成
  **教学周**用了，整门课会偏 offset 周（实测偏 3 周）。新增 `mask_offset` 参数把周次
  换算回教学周；位图分支现在也遵守 `max_week`
- `rows_to_occurrences` 增加 `week_offset` 参数并透传给 `parse_weeks`
- 课表缓存 payload 记录 `week_offset`（旧缓存没有该字段时按 0 处理，不影响 ZCMC 正常解析）

真实数据回归：22 行 / 207 条课程实例，带不带 offset 结果完全一致（`ZCMC` 齐全时不受影响）；
把 `ZCMC` 人为清空模拟坏数据，修复前首节课算成 10-12，修复后回到正确的 09-21。

测试：100 → 104 个用例。

## v0.3.2 (2026-10-26)

- 命令参数也统一改成英文，中文参数不再识别：`第9周`、`表格`、`刷新`、`今天`、`明天`、
  `学期`、`默认`、`帮助` 全部下线，对应写法为 `9`、`grid`、`refresh`、`today`、
  `tomorrow`、`terms`、`auto`、`help`
- 回复文案仍为中文，只有指令与参数是英文
- `/schedule terms auto` 取代 `/schedule 学期 默认`
- 帮助文本、README 命令表同步；新增回归测试确保中文参数不会悄悄生效

## v0.3.1 (2026-10-26)

- 指令层不再做中文兼容：`/验证码`、`/校准` 之类旧中文名不会被识别为指令（参数里的中文
  照旧有效，如 `/schedule 第9周 表格`）。要报错就干干净净报错，不留半套兼容

## v0.3.0 (2026-10-26)

> ⚠️ 破坏性变更：斜杠指令改为英文。**回复正文仍是中文**，只是指令名换了。

指令对照：

| 旧 | 新 |
| --- | --- |
| `/课表` | `/schedule` |
| `/下节课` | `/next` |
| `/今日` / `/明日` | `/today` / `/tomorrow` |
| `/课表状态` | `/status` |
| `/导出` | `/export` |
| `/登录` | `/login` |
| `/验证码` | `/code` |
| `/取消登录` | `/cancel_login` |
| `/校准` | `/calibrate` |

命令参数仍兼容中文（`/schedule 第9周 表格`），并新增英文写法（`today` / `tomorrow` / `terms`）。
帮助文本里出现的指令名已同步成英文，避免照着帮助打出旧指令。

重构：

- 登录流程（CAS 密码 / 图形验证码 / 短信二次验证，约 380 行）从 `core/jwapp.py`
  拆到 `core/cas_login.py`，以 `CasLoginMixin` 混入 `JwappClient`
- 异常类型统一挪到 `core/errors.py`，打破 `jwapp` ↔ `cas_login` 的循环依赖；
  `from .core.jwapp import JwappError` 仍可用（转出 re-export）
- 教务端点常量挪到 `core/endpoints.py`，两个模块共用，不再各自硬编码 URL
- `core/jwapp.py` 从 563 行降到 190 行，只留 HTTP 会话与数据接口

网络层：

- 连接超时与读超时分离（默认 10s / 25s），不再一个 `timeout` 打天下
- GET 遇到 429/500/502/503/504、超时、连接错误时指数退避重试（默认 2 次，最多等 4s）
- **POST 默认不重试**：短信验证码接口重放会重复发短信，需要重试必须显式 `retry=True`

测试：85 → 99 个用例，新增 `tests/test_jwapp.py`（重试策略、超时映射、待验证状态、cookie 往返）。

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
