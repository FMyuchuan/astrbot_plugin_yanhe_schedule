# -*- coding: utf-8 -*-
"""core.ics 单测：时间解析、VEVENT 解析、RRULE 展开。"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ics import (  # noqa: E402
    expand_calendar,
    expand_event,
    guess_teacher,
    guess_weeks,
    parse_datetime,
    parse_ics,
)

WINDOW_START = datetime(2026, 9, 1)
WINDOW_END = datetime(2026, 10, 31, 23, 59)

SIMPLE = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "BEGIN:VEVENT",
        "SUMMARY:线性代数",
        "LOCATION:良乡 A101",
        "DESCRIPTION:教师：李四\\n上课周次：1-16周",
        "DTSTART:20260921T080000",
        "DTEND:20260921T093500",
        "UID:abc@school",
        "RRULE:FREQ=WEEKLY;COUNT=3",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
)


class ParseDatetimeTest(unittest.TestCase):
    def test_floating_time(self):
        self.assertEqual(parse_datetime("20260921T080000"), datetime(2026, 9, 21, 8, 0))

    def test_utc_converted_to_beijing(self):
        self.assertEqual(parse_datetime("20260921T000000Z"), datetime(2026, 9, 21, 8, 0))

    def test_date_only(self):
        self.assertEqual(parse_datetime("20260921"), datetime(2026, 9, 21, 0, 0))

    def test_short_time(self):
        self.assertEqual(parse_datetime("20260921T0800"), datetime(2026, 9, 21, 8, 0))

    def test_invalid(self):
        self.assertIsNone(parse_datetime("下周见"))
        self.assertIsNone(parse_datetime(""))


class ParseIcsTest(unittest.TestCase):
    def test_parses_vevent(self):
        events = parse_ics(SIMPLE)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.summary, "线性代数")
        self.assertEqual(event.location, "良乡 A101")
        self.assertEqual(event.start, datetime(2026, 9, 21, 8, 0))
        self.assertEqual(event.end, datetime(2026, 9, 21, 9, 35))
        self.assertEqual(event.uid, "abc@school")
        self.assertEqual(event.rrule["COUNT"], "3")

    def test_unescapes_and_unfolds(self):
        text = "\r\n".join(
            [
                "BEGIN:VEVENT",
                "SUMMARY:高等数学\\, 上",
                "DESCRIPTION:很长的描述第一段",
                " 续行内容",
                "DTSTART:20260921T080000",
                "END:VEVENT",
            ]
        )
        event = parse_ics(text)[0]
        self.assertEqual(event.summary, "高等数学, 上")
        self.assertIn("续行内容", event.description)

    def test_event_without_dtstart_dropped(self):
        text = "\r\n".join(
            ["BEGIN:VEVENT", "SUMMARY:没时间", "END:VEVENT"]
        )
        self.assertEqual(parse_ics(text), [])

    def test_teacher_and_weeks_guessed_from_description(self):
        event = parse_ics(SIMPLE)[0]
        self.assertEqual(event.teacher, "李四")
        self.assertEqual(event.week_hint, "1-16周")


class ExpandTest(unittest.TestCase):
    def test_weekly_count(self):
        occurrences = expand_calendar(SIMPLE, WINDOW_START, WINDOW_END)
        self.assertEqual(
            [o.start.date().isoformat() for o in occurrences],
            ["2026-09-21", "2026-09-28", "2026-10-05"],
        )

    def test_weekly_until(self):
        text = SIMPLE.replace("COUNT=3", "UNTIL=20261005T235959")
        occurrences = expand_calendar(text, WINDOW_START, WINDOW_END)
        self.assertEqual(len(occurrences), 3)

    def test_exdate_skips_one_week(self):
        text = SIMPLE.replace("RRULE:", "EXDATE:20260928T080000\r\nRRULE:")
        occurrences = expand_calendar(text, WINDOW_START, WINDOW_END)
        self.assertEqual(
            [o.start.date().isoformat() for o in occurrences],
            ["2026-09-21", "2026-10-05"],
        )

    def test_single_event_without_rrule(self):
        text = SIMPLE.replace("RRULE:FREQ=WEEKLY;COUNT=3", "")
        occurrences = expand_calendar(text, WINDOW_START, WINDOW_END)
        self.assertEqual(len(occurrences), 1)

    def test_single_event_outside_window(self):
        text = SIMPLE.replace("RRULE:FREQ=WEEKLY;COUNT=3", "")
        occurrences = expand_calendar(
            text, datetime(2026, 1, 1), datetime(2026, 2, 1)
        )
        self.assertEqual(occurrences, [])

    def test_duration_defaults_when_no_dtend(self):
        text = SIMPLE.replace("DTEND:20260921T093500\r\n", "").replace(
            "RRULE:FREQ=WEEKLY;COUNT=3", ""
        )
        occurrence = expand_calendar(text, WINDOW_START, WINDOW_END)[0]
        self.assertEqual((occurrence.end - occurrence.start).total_seconds(), 95 * 60)

    def test_expand_event_handles_missing_start(self):
        event = parse_ics(SIMPLE)[0]
        event.start = None
        self.assertEqual(expand_event(event, WINDOW_START, WINDOW_END), [])


class GuessTest(unittest.TestCase):
    def test_teacher_patterns(self):
        self.assertEqual(guess_teacher("教师：王五"), "王五")
        self.assertEqual(guess_teacher("任课教师: 赵六"), "赵六")
        self.assertEqual(guess_teacher(""), "")

    def test_weeks_pattern(self):
        self.assertEqual(guess_weeks("上课周次 1 - 8 周"), "1-8周")
        self.assertEqual(guess_weeks("没有周次"), "")


if __name__ == "__main__":
    unittest.main()
