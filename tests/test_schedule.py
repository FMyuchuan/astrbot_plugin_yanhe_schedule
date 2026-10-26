# -*- coding: utf-8 -*-
"""core.schedule 单测：周次换算、网格合并、越界保护。"""

import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.schedule import (  # noqa: E402
    PERIODS,
    Timetable,
    period_index,
    period_label,
)

TERM_START = date(2026, 9, 21)  # 周一


class FakeOcc:
    def __init__(self, summary, start, end, location="", teacher=""):
        self.summary = summary
        self.start = start
        self.end = end
        self.location = location
        self.teacher = teacher


def occ(day, hour, minute, duration_minutes=95, summary="课", location="", weekday_offset=0):
    start = datetime(2026, 9, 21 + weekday_offset, hour, minute)
    return FakeOcc(summary, start, start + timedelta(minutes=duration_minutes), location)


class PeriodTest(unittest.TestCase):
    def test_exact_start_maps_to_period(self):
        self.assertEqual(period_index(datetime(2026, 9, 21, 8, 0)), 0)
        self.assertEqual(period_index(datetime(2026, 9, 21, 13, 20)), 5)
        self.assertEqual(period_index(datetime(2026, 9, 21, 20, 10)), 12)

    def test_gap_snaps_to_next_period(self):
        # 9:35~9:55 是课间
        self.assertEqual(period_index(datetime(2026, 9, 21, 9, 40)), 2)

    def test_after_last_period_clamps(self):
        self.assertEqual(period_index(datetime(2026, 9, 21, 23, 50)), len(PERIODS) - 1)

    def test_period_label(self):
        self.assertIn("第1节", period_label(0))
        self.assertIn("08:00", period_label(0))


class WeekMathTest(unittest.TestCase):
    def setUp(self):
        self.tt = Timetable([occ(0, 8, 0)], term_start=TERM_START, weeks=16)

    def test_week_of(self):
        self.assertEqual(self.tt.week_of(date(2026, 9, 21)), 1)
        self.assertEqual(self.tt.week_of(date(2026, 9, 27)), 1)
        self.assertEqual(self.tt.week_of(date(2026, 9, 28)), 2)

    def test_week_of_before_term(self):
        self.assertEqual(self.tt.week_of(date(2026, 9, 14)), 0)

    def test_current_week_clamped(self):
        self.assertEqual(self.tt.current_week(date(2026, 9, 21)), 1)
        self.assertEqual(self.tt.current_week(date(2026, 9, 15)), 1)  # 开学前
        self.assertEqual(self.tt.current_week(date(2030, 1, 1)), self.tt.weeks)  # 学期后

    def test_occurrences_in_week(self):
        self.assertEqual(len(self.tt.occurrences_in_week(1)), 1)
        self.assertEqual(len(self.tt.occurrences_in_week(2)), 0)

    def test_weeks_expands_with_data(self):
        tt = Timetable([occ(0, 8, 0)], term_start=TERM_START, weeks=2)
        far = Timetable(
            [
                FakeOcc(
                    "课",
                    datetime(2026, 11, 16, 8, 0),
                    datetime(2026, 11, 16, 9, 35),
                )
            ],
            term_start=TERM_START,
            weeks=2,
        )
        self.assertEqual(tt.weeks, 2)
        self.assertEqual(far.weeks, 9)  # 数据跨到第 9 周，上限要跟着放大

    def test_active_days_defaults_to_workdays(self):
        self.assertEqual(self.tt.active_days(1), [0, 1, 2, 3, 4])

    def test_active_days_includes_weekend(self):
        tt = Timetable(
            [
                FakeOcc(
                    "周六课",
                    datetime(2026, 9, 26, 8, 0),
                    datetime(2026, 9, 26, 9, 35),
                )
            ],
            term_start=TERM_START,
        )
        self.assertEqual(tt.active_days(1), [0, 1, 2, 3, 4, 5])


class BlocksTest(unittest.TestCase):
    def test_span_merges_periods(self):
        tt = Timetable([occ(0, 8, 0, duration_minutes=95)], term_start=TERM_START)
        blocks = tt.blocks_for_day(1, 0)
        self.assertEqual(set(blocks), {0})
        self.assertEqual(blocks[0].span, 2)

    def test_conflict_shifts_down(self):
        tt = Timetable(
            [occ(0, 8, 0, summary="A"), occ(0, 8, 0, summary="B")],
            term_start=TERM_START,
        )
        blocks = tt.blocks_for_day(1, 0)
        self.assertEqual(len(blocks), 2)
        self.assertEqual({b.occurrence.summary for b in blocks.values()}, {"A", "B"})

    def test_overflow_is_dropped_not_rendered_outside_grid(self):
        """13 节全被占满后，冲突的课不能再顺延到网格外面去。"""
        full_day = FakeOcc(
            "占满",
            datetime(2026, 9, 21, 8, 0),
            datetime(2026, 9, 21, 20, 55),
        )
        extra = [
            occ(0, 8, 0, summary=f"挤{i}") for i in range(1, 20)
        ]
        tt = Timetable([full_day, *extra], term_start=TERM_START)
        blocks = tt.blocks_for_day(1, 0)
        self.assertTrue(all(0 <= key < len(PERIODS) for key in blocks))
        for block in blocks.values():
            self.assertLessEqual(block.start_period + block.span, len(PERIODS))


class TermBoundsTest(unittest.TestCase):
    def test_bounds_cover_whole_term(self):
        tt = Timetable([occ(0, 8, 0)], term_start=TERM_START, weeks=16)
        start, end = tt.term_bounds()
        self.assertEqual(start, datetime(2026, 9, 21, 0, 0))
        self.assertEqual(end.date(), TERM_START + timedelta(weeks=15, days=6))


if __name__ == "__main__":
    unittest.main()
