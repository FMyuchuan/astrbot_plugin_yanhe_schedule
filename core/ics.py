"""最小可用的 iCalendar (RFC 5545) 解析与周次展开。

教务系统导出的 .ics 大多是「每周重复」的 VEVENT：一个课程 = 一个
``RRULE:FREQ=WEEKLY;COUNT=n``（或 ``UNTIL=``）事件，外加可能的 EXDATE。
本模块负责把它展开成一条条具体的上课记录。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

_WEEKDAYS = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}

_ESCAPES = {
    "n": "\n",
    "N": "\n",
    ",": ",",
    ";": ";",
    "\\": "\\",
}


@dataclass
class Event:
    summary: str = ""
    location: str = ""
    description: str = ""
    start: datetime | None = None
    end: datetime | None = None
    uid: str = ""
    rrule: dict[str, str] = field(default_factory=dict)
    exdates: list[datetime] = field(default_factory=list)

    @property
    def duration(self) -> timedelta:
        if self.start and self.end and self.end > self.start:
            return self.end - self.start
        return timedelta(minutes=95)

    @property
    def teacher(self) -> str:
        return guess_teacher(self.description)

    @property
    def week_hint(self) -> str:
        return guess_weeks(self.description)


@dataclass
class Occurrence:
    summary: str
    location: str
    teacher: str
    start: datetime
    end: datetime
    uid: str = ""
    week_hint: str = ""

    @property
    def day(self) -> date:
        return self.start.date()


def _unfold(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw in text.split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    def repl(match: re.Match) -> str:
        return _ESCAPES.get(match.group(1), match.group(1))

    return re.sub(r"\\(.)", repl, value)


def _split_property(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].strip().upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip().upper()] = v.strip().strip('"')
    return name, params, value


def parse_datetime(value: str, params: dict[str, str] | None = None) -> datetime | None:
    """解析 ICS 时间：支持 UTC(Z)、浮动时间和纯日期。

    这里统一换算成北京时间（UTC+8），避免依赖 tzdata。
    """
    params = params or {}
    value = value.strip()
    if not value:
        return None
    utc = value.endswith("Z")
    if utc:
        value = value[:-1]
    if "T" in value:
        try:
            dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
        except ValueError:
            try:
                dt = datetime.strptime(value, "%Y%m%dT%H%M")
            except ValueError:
                return None
    else:
        try:
            dt = datetime.strptime(value, "%Y%m%d")
        except ValueError:
            return None
    if utc:
        dt = dt + timedelta(hours=8)
    return dt


def parse_ics(text: str) -> list[Event]:
    events: list[Event] = []
    current: dict | None = None
    for line in _unfold(text):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper() == "BEGIN:VEVENT":
            current = {"exdates": [], "rrule": {}}
            continue
        if stripped.upper() == "END:VEVENT":
            if current is not None:
                events.append(
                    Event(
                        summary=current.get("summary", ""),
                        location=current.get("location", ""),
                        description=current.get("description", ""),
                        start=current.get("start"),
                        end=current.get("end"),
                        uid=current.get("uid", ""),
                        rrule=current.get("rrule", {}),
                        exdates=current.get("exdates", []),
                    )
                )
            current = None
            continue
        if current is None:
            continue

        parsed = _split_property(stripped)
        if not parsed:
            continue
        name, params, value = parsed

        if name == "SUMMARY":
            current["summary"] = _unescape(value).strip()
        elif name == "LOCATION":
            current["location"] = _unescape(value).strip()
        elif name == "DESCRIPTION":
            current["description"] = _unescape(value).strip()
        elif name == "UID":
            current["uid"] = value.strip()
        elif name == "DTSTART":
            current["start"] = parse_datetime(value, params)
        elif name == "DTEND":
            current["end"] = parse_datetime(value, params)
        elif name == "RRULE":
            rule = {}
            for part in value.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    rule[k.strip().upper()] = v.strip()
            current["rrule"] = rule
        elif name == "EXDATE":
            for chunk in value.split(","):
                dt = parse_datetime(chunk, params)
                if dt:
                    current["exdates"].append(dt)
    return [e for e in events if e.start]


def _rrule_until(rule: dict[str, str]) -> datetime | None:
    raw = rule.get("UNTIL")
    if not raw:
        return None
    return parse_datetime(raw)


def expand_event(
    event: Event, window_start: datetime, window_end: datetime
) -> list[Occurrence]:
    """把单个事件在窗口内展开成 occurrences。"""
    if event.start is None:
        return []
    duration = event.duration
    rule = event.rrule or {}

    if not rule or "FREQ" not in rule:
        if window_start <= event.start <= window_end:
            return [_occurrence(event, event.start, event.start + duration)]
        return []

    freq = rule["FREQ"].upper()
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = _rrule_until(rule)
    byday = [d.strip().upper() for d in rule.get("BYDAY", "").split(",") if d.strip()]
    weekdays = [_WEEKDAYS[d[-2:]] for d in byday if d[-2:] in _WEEKDAYS] or [
        event.start.weekday()
    ]

    exdates = {d.replace(second=0, microsecond=0) for d in event.exdates}
    results: list[Occurrence] = []
    produced = 0

    if freq == "DAILY":
        cursor = event.start
        while cursor <= window_end:
            if until and cursor > until:
                break
            if count is not None and produced >= count:
                break
            key = cursor.replace(second=0, microsecond=0)
            if key not in exdates and cursor >= window_start:
                results.append(_occurrence(event, cursor, cursor + duration))
            produced += 1
            cursor += timedelta(days=interval)
        return results

    # 以 DTSTART 所在周为第 0 周，按周推进
    base_monday = event.start.date() - timedelta(days=event.start.weekday())
    start_time = event.start.time()
    week_idx = 0
    while True:
        week_monday = base_monday + timedelta(weeks=week_idx * interval)
        week_start_dt = datetime.combine(week_monday, start_time)
        if week_start_dt > window_end and week_idx > 0:
            break
        for weekday in sorted(set(weekdays)):
            occurrence_start = datetime.combine(
                week_monday + timedelta(days=weekday), start_time
            )
            if occurrence_start < event.start:
                continue
            if until and occurrence_start > until:
                continue
            if count is not None and produced >= count:
                continue
            produced += 1
            key = occurrence_start.replace(second=0, microsecond=0)
            if key in exdates:
                continue
            if window_start <= occurrence_start <= window_end:
                results.append(
                    _occurrence(event, occurrence_start, occurrence_start + duration)
                )
        week_idx += 1
        if week_idx > 60:
            break
    results.sort(key=lambda o: o.start)
    return results


def _occurrence(event: Event, start: datetime, end: datetime) -> Occurrence:
    return Occurrence(
        summary=event.summary or "未命名课程",
        location=event.location,
        teacher=event.teacher,
        start=start,
        end=end,
        uid=event.uid,
        week_hint=event.week_hint,
    )


def expand_calendar(
    text: str, window_start: datetime, window_end: datetime
) -> list[Occurrence]:
    occurrences: list[Occurrence] = []
    for event in parse_ics(text):
        occurrences.extend(expand_event(event, window_start, window_end))
    occurrences.sort(key=lambda o: (o.start, o.summary))
    return occurrences


def guess_teacher(description: str) -> str:
    if not description:
        return ""
    patterns = [
        r"教师\s*[:：]\s*([^\n,;，；]+)",
        r"任课教师\s*[:：]\s*([^\n,;，；]+)",
        r"授课教师\s*[:：]\s*([^\n,;，；]+)",
        r"老师\s*[:：]\s*([^\n,;，；]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, description)
        if match:
            return match.group(1).strip()
    return ""


def guess_weeks(description: str) -> str:
    if not description:
        return ""
    match = re.search(r"(\d+(?:\s*[-~]\s*\d+)?\s*周)", description)
    return match.group(1).replace(" ", "") if match else ""
