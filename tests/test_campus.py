# -*- coding: utf-8 -*-
"""core.campus 单测：周次字符串解析、节次归一、行转课程实例。"""

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.campus import parse_weeks, row_periods, rows_to_occurrences  # noqa: E402

TERM_START = date(2026, 9, 21)  # 周一


def row(**kwargs):
    base = {
        "KCM": "高等数学",
        "SKXQ": "1",
        "KSJC": "1",
        "JSJC": "2",
        "JASMC": "良乡 A101",
        "SKJS": "张老师",
        "ZCMC": "1-16周",
        "SKZC": "",
        "WID": "w1",
    }
    base.update(kwargs)
    return base


class ParseWeeksTest(unittest.TestCase):
    def test_plain_range(self):
        self.assertEqual(parse_weeks("1-8周"), list(range(1, 9)))

    def test_single_week(self):
        self.assertEqual(parse_weeks("10周"), [10])

    def test_odd_weeks(self):
        self.assertEqual(parse_weeks("1-15周(单)"), [1, 3, 5, 7, 9, 11, 13, 15])

    def test_even_weeks(self):
        self.assertEqual(parse_weeks("1-16周(双)"), [2, 4, 6, 8, 10, 12, 14, 16])

    def test_multiple_chunks(self):
        self.assertEqual(
            parse_weeks("1-4周,10-12周"), [1, 2, 3, 4, 10, 11, 12]
        )

    def test_chinese_comma_and_range_symbol(self):
        self.assertEqual(parse_weeks("1~3周，6周"), [1, 2, 3, 6])

    def test_mask_fallback(self):
        self.assertEqual(parse_weeks("", "1111000000000000"), [1, 2, 3, 4])

    def test_mask_ignored_when_text_parses(self):
        self.assertEqual(parse_weeks("2-3周", "11111111"), [2, 3])

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_weeks("待定", ""), [])

    def test_respects_max_week(self):
        self.assertEqual(parse_weeks("1-50周", "", max_week=3), [1, 2, 3])


class RowPeriodsTest(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(row_periods({"KSJC": "3", "JSJC": "5"}), (3, 5))

    def test_clamped_to_period_table(self):
        self.assertEqual(row_periods({"KSJC": "0", "JSJC": "99"}), (1, 13))

    def test_missing_values(self):
        self.assertEqual(row_periods({}), (1, 1))

    def test_broken_values(self):
        self.assertEqual(row_periods({"KSJC": "x", "JSJC": "y"}), (1, 1))


class RowsToOccurrencesTest(unittest.TestCase):
    def test_expands_each_week(self):
        events = rows_to_occurrences([row(ZCMC="1-2周")], TERM_START)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].start, datetime(2026, 9, 21, 8, 0))
        self.assertEqual(events[1].start, datetime(2026, 9, 28, 8, 0))
        self.assertEqual(events[0].end, datetime(2026, 9, 21, 9, 35))

    def test_weekend_weekday(self):
        events = rows_to_occurrences([row(SKXQ="6", ZCMC="1周")], TERM_START)
        self.assertEqual(events[0].start.date(), date(2026, 9, 26))

    def test_duplicate_rows_deduped(self):
        events = rows_to_occurrences([row(ZCMC="1周"), row(ZCMC="1周")], TERM_START)
        self.assertEqual(len(events), 1)

    def test_same_course_different_room_kept(self):
        events = rows_to_occurrences(
            [row(ZCMC="1周"), row(ZCMC="1周", JASMC="良乡 B202")], TERM_START
        )
        self.assertEqual(len(events), 2)

    def test_skips_empty_name_or_bad_weekday(self):
        events = rows_to_occurrences(
            [row(KCM=""), row(SKXQ="9"), row(SKXQ="abc")], TERM_START
        )
        self.assertEqual(events, [])

    def test_missing_weeks_falls_back_to_full_term(self):
        events = rows_to_occurrences([row(ZCMC="", SKZC="")], TERM_START)
        self.assertEqual(len(events), 16)

    def test_fields_carried_over(self):
        event = rows_to_occurrences([row(ZCMC="1周")], TERM_START)[0]
        self.assertEqual(event.summary, "高等数学")
        self.assertEqual(event.location, "良乡 A101")
        self.assertEqual(event.teacher, "张老师")
        self.assertEqual(event.uid, "w1")
        self.assertEqual(event.week_hint, "1周")

    def test_sorted_by_start(self):
        events = rows_to_occurrences(
            [
                row(SKXQ="3", ZCMC="1周", KCM="周三课"),
                row(SKXQ="1", ZCMC="1周", KCM="周一课"),
            ],
            TERM_START,
        )
        self.assertEqual([e.summary for e in events], ["周一课", "周三课"])


if __name__ == "__main__":
    unittest.main()
