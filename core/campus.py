"""把教务系统「学期课表」的 JSON 行解析成课程实例。"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .ics import Occurrence
from .schedule import PERIODS

WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def parse_weeks(zcmc: str | None, mask: str | None = None, max_week: int = 30) -> list[int]:
    """解析上课周次。

    ``ZCMC`` 形如「1-8周」「1-16周」「1-15周(单)」「1-8周,10-12周」；
    解析不了时退回 ``SKZC`` 的按周位图（如 ``1111111100000000``）。
    """
    weeks: set[int] = set()
    text = (zcmc or "").strip()
    if text:
        for chunk in re.split(r"[,，;；、]", text):
            if not chunk.strip():
                continue
            parity = _parity(chunk)
            match = re.search(r"(\d+)\s*[-~至]\s*(\d+)", chunk)
            if match:
                start, end = int(match.group(1)), int(match.group(2))
            else:
                singles = [int(n) for n in re.findall(r"\d+", chunk)]
                if not singles:
                    continue
                start = end = singles[0]
            for week in range(start, end + 1):
                if 1 <= week <= max_week and _match_parity(week, parity):
                    weeks.add(week)

    if not weeks and mask:
        for index, flag in enumerate(mask.strip()):
            if flag == "1":
                weeks.add(index + 1)

    return sorted(weeks)


def _parity(chunk: str) -> str:
    if "单" in chunk:
        return "odd"
    if "双" in chunk:
        return "even"
    return ""


def _match_parity(week: int, parity: str) -> bool:
    if parity == "odd":
        return week % 2 == 1
    if parity == "even":
        return week % 2 == 0
    return True


def row_periods(row: dict) -> tuple[int, int]:
    """返回 (起始节, 结束节)，都是 1 起。"""
    try:
        start = int(row.get("KSJC") or 0)
    except (TypeError, ValueError):
        start = 0
    try:
        end = int(row.get("JSJC") or start)
    except (TypeError, ValueError):
        end = start
    start = min(max(start, 1), len(PERIODS))
    end = min(max(end, start), len(PERIODS))
    return start, end


def rows_to_occurrences(rows: list[dict], term_start: date) -> list[Occurrence]:
    occurrences: list[Occurrence] = []
    seen: set[tuple] = set()

    for row in rows:
        name = (row.get("KCM") or "").strip()
        if not name:
            continue
        try:
            weekday = int(row.get("SKXQ") or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= weekday <= 7:
            continue

        start_period, end_period = row_periods(row)
        start_time = PERIODS[start_period - 1][0]
        end_time = PERIODS[end_period - 1][1]

        weeks = parse_weeks(row.get("ZCMC"), row.get("SKZC"))
        if not weeks:
            weeks = list(range(1, 17))

        location = (row.get("JASMC") or "").strip()
        teacher = (row.get("SKJS") or "").strip()
        hint = (row.get("ZCMC") or "").strip()

        for week in weeks:
            day = term_start + timedelta(weeks=week - 1, days=weekday - 1)
            key = (name, day, start_period, end_period, location)
            if key in seen:
                continue
            seen.add(key)
            occurrences.append(
                Occurrence(
                    summary=name,
                    location=location,
                    teacher=teacher,
                    start=datetime.combine(day, start_time),
                    end=datetime.combine(day, end_time),
                    uid=str(row.get("WID") or row.get("JXBID") or ""),
                    week_hint=hint,
                )
            )

    occurrences.sort(key=lambda o: (o.start, o.summary))
    return occurrences


def index_rows(rows: list[dict]) -> list[dict]:
    """给每行补上展示用字段，方便 --view list 之类的地方核对原始数据。"""
    result = []
    for row in rows:
        start_period, end_period = row_periods(row)
        result.append(
            {
                "name": row.get("KCM"),
                "teacher": row.get("SKJS"),
                "location": row.get("JASMC"),
                "weekday": row.get("SKXQ"),
                "periods": f"{start_period}-{end_period}",
                "weeks": row.get("ZCMC"),
                "class": row.get("SKBJ"),
                "raw": row.get("YPSJDD"),
            }
        )
    return result
