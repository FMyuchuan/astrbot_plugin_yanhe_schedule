"""把 Timetable 渲染成终端表格 / 列表 / JSON / 单文件 HTML。"""

from __future__ import annotations

import html
import json
import unicodedata

from .schedule import PERIODS, WEEKDAY_NAMES, Timetable, period_label

CELL_WIDTH = 18
TIME_WIDTH = 19


# --------------------------------------------------------------------- 宽度
def display_width(text: str) -> int:
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def shorten(text: str, width: int) -> str:
    text = " ".join(text.split())
    if display_width(text) <= width:
        return text
    out = ""
    for ch in text:
        if display_width(out) + display_width(ch) > width - 1:
            break
        out += ch
    return out + "…"


def fit(text: str, width: int) -> str:
    text = shorten(text, width)
    return text + " " * max(0, width - display_width(text))


def cell_text(name: str, location: str, width: int) -> str:
    base = name
    if location and display_width(base) + 1 + display_width(location) <= width:
        return base + " " + location
    if location and display_width(base) < width - 3:
        return base + " " + shorten(location, width - display_width(base) - 1)
    return base


# --------------------------------------------------------------------- 网格
def render_grid(timetable: Timetable, week: int, show_weekend: bool | None = None) -> str:
    days = timetable.active_days(week)
    if show_weekend is False:
        days = [d for d in days if d < 5]
    elif show_weekend is True:
        days = list(range(7))
    days = sorted(set(days))

    dates = timetable.week_dates(week)
    lines = [
        f"{dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}    第 {week} 周",
        "",
        " " * TIME_WIDTH + "".join(
            "|" + fit(f"{WEEKDAY_NAMES[d]} {dates[d].strftime('%m-%d')}", CELL_WIDTH)
            for d in days
        ) + "|",
        "-" * TIME_WIDTH + ("+" + "-" * CELL_WIDTH) * len(days) + "+",
    ]

    blocks = {d: timetable.blocks_for_day(week, d) for d in days}
    tail: dict[int, list[str]] = {d: [] for d in days}

    for period in range(len(PERIODS)):
        cells: list[str] = []
        for d in days:
            if tail[d]:
                cells.append(tail[d].pop(0) or "·")
                continue
            block = blocks[d].get(period)
            if block is None:
                cells.append("")
                continue
            occurrence = block.occurrence
            if block.span == 1:
                cells.append(cell_text(occurrence.summary, occurrence.location, CELL_WIDTH - 1))
                continue
            cells.append(shorten(occurrence.summary, CELL_WIDTH - 1))
            extra = [shorten(occurrence.location, CELL_WIDTH - 1)] if occurrence.location else []
            extra += [""] * (block.span - 1 - len(extra))
            tail[d] = extra
        lines.append(fit(period_label(period), TIME_WIDTH) + "".join(
            "|" + fit(cell, CELL_WIDTH) for cell in cells
        ) + "|")
        lines.append("-" * TIME_WIDTH + ("+" + "-" * CELL_WIDTH) * len(days) + "+")

    return "\n".join(lines)


# --------------------------------------------------------------------- 列表
def render_list(timetable: Timetable, week: int) -> str:
    dates = timetable.week_dates(week)
    events = timetable.occurrences_in_week(week)
    lines = [f"{dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}    第 {week} 周", ""]
    if not events:
        lines.append("这一周没有课。")
        return "\n".join(lines)
    for day in dates:
        daily = [o for o in events if o.start.date() == day]
        if not daily:
            continue
        lines.append(f"{WEEKDAY_NAMES[day.weekday()]}  {day.strftime('%m-%d')}")
        for o in daily:
            parts = [f"{o.start.strftime('%H:%M')}-{o.end.strftime('%H:%M')}", o.summary]
            if o.location:
                parts.append(f"@{o.location}")
            if o.teacher:
                parts.append(o.teacher)
            lines.append("  " + "  ".join(parts))
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------- JSON
def to_dict(timetable: Timetable, week: int) -> dict:
    dates = timetable.week_dates(week)
    events = timetable.occurrences_in_week(week)
    return {
        "week": week,
        "term_start": timetable.term_start.isoformat(),
        "week_start": dates[0].isoformat(),
        "week_end": dates[-1].isoformat(),
        "events": [
            {
                "summary": o.summary,
                "location": o.location,
                "teacher": o.teacher,
                "start": o.start.isoformat(timespec="minutes"),
                "end": o.end.isoformat(timespec="minutes"),
                "weekday": o.start.weekday() + 1,
                "week_hint": o.week_hint,
            }
            for o in events
        ],
    }


def render_json(timetable: Timetable, week: int) -> str:
    return json.dumps(to_dict(timetable, week), ensure_ascii=False, indent=2)


# --------------------------------------------------------------------- HTML
def _color_for(name: str) -> str:
    # 稳定配色：按名字哈希取色相
    hue = sum(ord(ch) for ch in name) * 47 % 360
    return f"hsl({hue}, 68%, 90%)"


def _border_for(name: str) -> str:
    hue = sum(ord(ch) for ch in name) * 47 % 360
    return f"hsl({hue}, 48%, 58%)"


def render_html(timetable: Timetable, week: int, title: str = "课表") -> str:
    days = timetable.active_days(week)
    dates = timetable.week_dates(week)
    events = timetable.occurrences_in_week(week)
    columns = len(days)

    items: list[str] = []
    for col, d in enumerate(days):
        items.append(
            f'<div class="day-head" style="grid-column:{col + 2};grid-row:1">'
            f"{WEEKDAY_NAMES[d]}<span>{dates[d].strftime('%m-%d')}</span></div>"
        )

    covered: set[tuple[int, int]] = set()
    day_blocks = {d: timetable.blocks_for_day(week, d) for d in days}
    for row in range(len(PERIODS)):
        items.append(
            f'<div class="time" style="grid-column:1;grid-row:{row + 2}">'
            f'<b>{row + 1}</b><span>{PERIODS[row][0].strftime("%H:%M")}</span></div>'
        )
        for col, d in enumerate(days):
            if (row, col) in covered:
                continue
            block = day_blocks[d].get(row)
            if block is None:
                items.append(
                    f'<div class="cell empty" style="grid-column:{col + 2};grid-row:{row + 2}"></div>'
                )
                continue
            for extra in range(1, block.span):
                covered.add((row + extra, col))
            o = block.occurrence
            items.append(
                f'<div class="cell course" style="grid-column:{col + 2};grid-row:{row + 2}/span {block.span};'
                f'background:{_color_for(o.summary)};border-left:3px solid {_border_for(o.summary)}">'
                f"<b>{html.escape(o.summary)}</b>"
                f"<span>{html.escape(o.location)}</span>"
                f"<em>{html.escape(o.teacher)}</em></div>"
            )

    names = sorted({e.summary for e in events})
    legend = "".join(
        f'<li><i style="background:{_color_for(n)};border:1px solid {_border_for(n)}"></i>{html.escape(n)}</li>'
        for n in names
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · 第{week}周</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 26px; background: #f5f6fa; color: #1f2430;
         font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; }}
  header {{ display: flex; align-items: baseline; gap: 14px; margin-bottom: 16px; }}
  h1 {{ font-size: 22px; margin: 0; }}
  .meta {{ color: #6b7280; font-size: 14px; }}
  .board {{ display: grid; grid-template-columns: 62px repeat({columns}, minmax(150px, 1fr));
            grid-auto-rows: 36px; gap: 5px; }}
  .day-head {{ display: flex; flex-direction: column; align-items: center; justify-content: center;
               background: #fff; border-radius: 10px; font-weight: 600; font-size: 13px;
               box-shadow: 0 1px 2px rgba(16,24,40,.06); }}
  .day-head span {{ font-size: 11px; color: #6b7280; font-weight: 400; }}
  .time {{ display: flex; flex-direction: column; align-items: center; justify-content: center;
           color: #6b7280; font-size: 11px; }}
  .time b {{ font-size: 13px; color: #374151; }}
  .cell {{ background: #fff; border-radius: 8px; padding: 3px 6px; overflow: hidden;
           box-shadow: 0 1px 2px rgba(16,24,40,.05); }}
  .cell.empty {{ background: #eef0f5; box-shadow: none; }}
  .course b {{ display: block; font-size: 12px; line-height: 1.25; }}
  .course span {{ display: block; font-size: 11px; color: #4b5563; margin-top: 1px; }}
  .course em {{ display: block; font-size: 10px; color: #6b7280; font-style: normal; }}
  footer {{ margin-top: 20px; font-size: 13px; color: #6b7280; }}
  ul {{ list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 12px; }}
  li {{ display: flex; align-items: center; gap: 6px; }}
  li i {{ width: 12px; height: 12px; border-radius: 3px; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <div class="meta">第 {week} 周 · {dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}</div>
</header>
<div class="board">{''.join(items)}</div>
<footer><ul>{legend}</ul></footer>
</body>
</html>
"""


def render(timetable: Timetable, week: int, view: str = "grid") -> str:
    if view == "list":
        return render_list(timetable, week)
    if view == "json":
        return render_json(timetable, week)
    return render_grid(timetable, week)


# --------------------------------------------------------------------- ICS
def render_ics(timetable: Timetable, calendar_name: str = "课表") -> str:
    """把整学期的课程导出成 iCalendar 文本（每条一个 VEVENT）。"""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//schedule-tool//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{calendar_name}",
    ]
    for index, occurrence in enumerate(timetable.occurrences):
        uid = occurrence.uid or f"{occurrence.start:%Y%m%d%H%M}-{index}"
        description = occurrence.teacher and f"教师：{occurrence.teacher}" or ""
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}-{index}@schedule-tool",
                f"DTSTART:{occurrence.start:%Y%m%dT%H%M%S}",
                f"DTEND:{occurrence.end:%Y%m%dT%H%M%S}",
                f"SUMMARY:{_escape_ics(occurrence.summary)}",
                f"LOCATION:{_escape_ics(occurrence.location)}",
                f"DESCRIPTION:{_escape_ics(description)}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _escape_ics(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )
