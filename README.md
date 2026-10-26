# 延河课表 AstrBot 插件

[![tests](https://github.com/FMyuchuan/astrbot_plugin_yanhe_schedule/actions/workflows/tests.yml/badge.svg)](https://github.com/FMyuchuan/astrbot_plugin_yanhe_schedule/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](requirements.txt)

延河课表 AstrBot 插件：在聊天里查课表，并注册成 Agent 函数工具（`llm_tool`）。

> ⚠️ 非官方项目，与任何学校官方无关。**仅用于查询你自己的课表**，请遵守学校网络与信息系统管理规定，不要分享账号、不要高频请求。接口可能随学校改版失效。

## 功能

- 本周 / 指定周 / 某天 / 下节课
- 学期列表与切换
- 自动周次对齐（读取教务的教学周偏移），也可手动校准
- 登录支持短信、图形验证码（在聊天里发 `/code` 继续）
- 整学期导出 `.ics`，可直接导入手机日历
- 6 个 Agent 工具，模型可自行调用

## 安装

```bash
git clone https://github.com/FMyuchuan/astrbot_plugin_yanhe_schedule.git
```

把 `astrbot_plugin_yanhe_schedule/` 整个目录放进 AstrBot 的 `data/plugins/`，
重启 AstrBot，在 WebUI 插件管理里填 `sid` / `password`。

要求 AstrBot `>= 4.9.2`，依赖 `requests`（AstrBot 自带）。

## 配置

| 配置项 | 必填 | 说明 |
| --- | --- | --- |
| `sid` | 是 | 学号 |
| `password` | 是 | 统一身份认证密码（只用于登录，登录后存 cookie） |
| `term` | 否 | 学期代码，留空自动取当前学期 |
| `term_start` | 否 | 教学第一周周一，留空自动推算 |
| `default_view` | 否 | `list`（默认）/ `grid` / `json` |
| `max_weeks` | 否 | 学期总周数，默认 16 |
| `cache_hours` | 否 | 课表缓存时长，默认 6 小时 |
| `allowed_users` | 否 | 允许查询的发送者 ID，留空所有人可查 |
| `admin_users` | 否 | 允许 `/校准`、`/登录`、`/验证码`、`/取消登录` 的 ID；留空时退回 `allowed_users`，两者都空则所有人可用 |

运行数据存在 `AstrBot/data/plugin_data/astrbot_plugin_yanhe_schedule/`：

- `session.json`：学号、登录 cookie、周次校准值
- `cache/term-<学期>.json`：课表缓存

## 命令

> 指令名和参数都用英文；**回复文案仍是中文**。

| 命令 | 作用 |
| --- | --- |
| `/schedule` / `/schedule 9` / `/schedule 9 grid` | 本周 / 指定周 / 表格样式（`grid`、`json`、`list`） |
| `/schedule today` / `/schedule tomorrow` | 某天 |
| `/schedule refresh` | 忽略缓存重新拉取 |
| `/schedule terms` / `/schedule terms 2026-2027-1` | 学期列表 / 切换 |
| `/next` | 最近一节课 |
| `/today` / `/tomorrow` | 今天 / 明天（`/schedule today` 的快捷写法） |
| `/status` | 学期、教学第一周、缓存状态 |
| `/export` | 整学期导出为 `.ics` 日历文件（可导入手机日历） |
| `/login` | 发起登录（管理员） |
| `/code 123456` | 提交短信 / 图形验证码（管理员） |
| `/cancel_login` | 放弃待验证的登录（管理员） |
| `/calibrate 5` | 校准本周为第 5 周（管理员） |

## Agent 工具

| 工具 | 参数 | 作用 |
| --- | --- | --- |
| `yanhe_get_schedule` | `week=0`, `view="list"` | 查某周课表 |
| `yanhe_get_day_schedule` | `day="today"` | 查某天（today/tomorrow/YYYY-MM-DD） |
| `yanhe_next_class` | — | 最近一节课 |
| `yanhe_list_terms` | — | 列出学期 |
| `yanhe_switch_term` | `term` | 切换学期 |
| `yanhe_calibrate_week` | `week` | 校准周次（管理员） |

例：「我明天几节课」「下节课在哪」「第 8 周周三有什么」——模型会自己选工具。

## 示例

```
/schedule
2026-2027学年 1学期

2026-10-19 ~ 2026-10-25    第 5 周

周一  10-19
  13:20-14:55  示例课程A  @示例楼101  某老师
  15:15-17:40  示例课程B  @示例楼202  另一位老师
周二  10-20
  08:00-09:35  示例课程C  @示例楼303  某老师
```

```
/next
14.8 小时后：10-26 13:20-14:55 示例课程A @示例楼101 某老师
```

## 需要短信/图形验证码时

1. 发 `/login`
2. 需要图形验证码时机器人会发图片，按提示发 `/code abcd`
3. 需要短信时提示「已发到尾号 XXXX」，发 `/code 123456`
4. 中途可能先图形、再短信，按提示走

验证成功后 cookie 会存进 `session.json`；待验证状态在内存里，重启 AstrBot 需要重新 `/login`。

## 周次是怎么算的

教务接口里「校历第 1 周」和课表上的「教学第 1 周」差一个偏移，插件读取这个偏移后
自动算出教学第一周周一；偏移不准时用 `/校准 N` 修正。

## 测试

```bash
python -m unittest discover -s tests -v
```

纯函数单测，不联网、不需要 AstrBot。

## 隐私与安全

- 仓库不含任何账号、cookie 或密钥；`session.json`、`data/` 等在 `.gitignore` 里
- 密码只用于登录，登录后保存的是 cookie；如果账号开了二次认证，按 `/登录` 提示完成
- 请勿把带 cookie / ticket / 手机号的日志或截图贴到公开 issue

## License

MIT，见 [LICENSE](LICENSE)。使用风险自负。
