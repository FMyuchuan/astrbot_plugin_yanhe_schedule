"""课表模型：把 occurrences 按教学周 / 星期 / 节次组织起来。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# 上课时间表（2026-2027 学年教学日历，自 2021-08-23 起实行）
# 上午 2 大节 5 小节、下午 2 大节 5 小节、晚上 1 大节 3 小节，共 13 节
PERIODS: list[tuple[time, time]] = [
    (time(8, 0), time(8, 45)),      # 第一节
    (time(8, 50), time(9, 35)),     # 第二节
    (time(9, 55), time(10, 40)),    # 第三节
    (time(10, 45), time(11, 30)),   # 第四节
    (time(11, 35), time(12, 20)),   # 第五节
    (time(13, 20), time(14, 5)),    # 第六节
    (time(14, 10), time(14, 55)),   # 第七节
    (time(15, 15), time(16, 0)),    # 第八节
    (time(16, 5), time(16, 50)),    # 第九节
    (time(16, 55), time(17, 40)),   # 第十节
    (time(18, 30), time(19, 15)),   # 第十一节
    (time(19, 20), time(20, 5)),    # 第十二节
    (time(20, 10), time(20, 55)),   # 第十三节
]

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def period_index(start: datetime) -> int:
    """把上课时间映射到第几节（0 起）。落在空隙时取最接近的下一节。"""
    clock = start.time().replace(second=0, microsecond=0)
    for idx, (begin, end) in enumerate(PERIODS):
        if begin <= clock <= end:
            return idx
    for idx, (begin, _end) in enumerate(PERIODS):
        if clock < begin:
            return idx
    return len(PERIODS) - 1


def period_label(index: int) -> str:
    if 0 <= index < len(PERIODS):
        begin, end = PERIODS[index]
        return f"第{index + 1}节 {begin.strftime('%H:%M')}-{end.strftime('%H:%M')}"
    return f"第{index + 1}节"


@dataclass
class Block:
    occurrence: "object"
    start_period: int
    span: int


class Timetable:
    """一个学期的课表。"""

    def __init__(self, occurrences, term_start: date | None = None, weeks: int = 20):
        self.occurrences = list(occurrences)
        self.term_start = term_start or self._infer_term_start()
        self.weeks = max(weeks, self._max_week_from_data())

    # ------------------------------------------------------------- 学期边界
    def _infer_term_start(self) -> date:
        if not self.occurrences:
            today = date.today()
            return today - timedelta(days=today.weekday())
        first = min(o.start.date() for o in self.occurrences)
        return first - timedelta(days=first.weekday())

    def _max_week_from_data(self) -> int:
        if not self.occurrences:
            return 1
        last = max(o.start.date() for o in self.occurrences)
        return self.week_of(last)

    # ----------------------------------------------------------------- 周次
    def week_of(self, day: date) -> int:
        delta = (day - self.term_start).days
        return delta // 7 + 1

    def week_start(self, week: int) -> date:
        return self.term_start + timedelta(weeks=week - 1)

    def week_dates(self, week: int) -> list[date]:
        start = self.week_start(week)
        return [start + timedelta(days=i) for i in range(7)]

    def current_week(self, today: date | None = None) -> int:
        day = today or date.today()
        week = self.week_of(day)
        return min(max(week, 1), max(self.weeks, 1))

    def occurrences_in_week(self, week: int) -> list:
        days = set(self.week_dates(week))
        return [o for o in self.occurrences if o.start.date() in days]

    # ----------------------------------------------------------------- 网格
    def blocks_for_day(self, week: int, weekday: int) -> dict[int, Block]:
        """返回 {起始节次: Block}，用于渲染合并单元格。"""
        target = self.week_start(week) + timedelta(days=weekday)
        blocks: dict[int, Block] = {}
        day_events = [o for o in self.occurrences if o.start.date() == target]
        for occurrence in day_events:
            start_idx = period_index(occurrence.start)
            end_idx = period_index(occurrence.end - timedelta(minutes=1))
            span = max(1, end_idx - start_idx + 1)
            # 冲突时顺延，避免互相覆盖
            while start_idx in blocks:
                start_idx += 1
            blocks[start_idx] = Block(occurrence=occurrence, start_period=start_idx, span=span)
        return blocks

    def active_days(self, week: int | None = None) -> list[int]:
        """有课的星期（默认总是显示周一到周五）。"""
        days = {o.start.weekday() for o in self.occurrences}
        if week is not None:
            days |= {o.start.weekday() for o in self.occurrences_in_week(week)}
        base = set(range(5))
        return sorted(base | days)

    def today_occurrences(self, today: date | None = None) -> list:
        day = today or date.today()
        return sorted(
            [o for o in self.occurrences if o.start.date() == day], key=lambda o: o.start
        )

    def term_bounds(self) -> tuple[datetime, datetime]:
        start = datetime.combine(self.week_start(1), time(0, 0))
        end = datetime.combine(self.week_start(self.weeks) + timedelta(days=6), time(23, 59))
        return start, end
