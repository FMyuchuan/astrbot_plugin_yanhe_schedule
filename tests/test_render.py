# -*- coding: utf-8 -*-
"""core.render 单测：列表 / JSON / 网格 / ICS 输出。"""

import json
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ics import Occurrence  # noqa: E402
from core.render import (  # noqa: E402
    display_width,
    fit,
    render_grid,
    render_ics,
    render_json,
    render_list,
    shorten,
)
from core.schedule import Timetable  # noqa: E402

TERM_START = date(2026, 9, 21)


def occ(week, weekday, hour, minute, duration=95, summary="高等数学", location="A101", teacher="张老师"):
    start = datetime(2026, 9, 21 + (week - 1) * 7 + weekday, hour, minute)
    from datetime import timedelta

    return Occurrence(
        summary=summary,
        location=location,
        teacher=teacher,
        start=start,
        end=start + timedelta(minutes=duration),
    )


def build():
    return Timetable(
        [occ(1, 0, 8, 0), occ(1, 0, 13, 20), occ(1, 2, 15, 15)],
        term_start=TERM_START,
        weeks=16,
    )


class WidthTest(unittest.TestCase):
    def test_display_width_cjk(self):
        self.assertEqual(display_width("abc"), 3)
        self.assertEqual(display_width("课表"), 4)

    def test_shorten_adds_ellipsis(self):
        self.assertEqual(shorten("高等数学", 10), "高等数学")
        self.assertTrue(shorten("高等数学与线性代数", 8).endswith("…"))

    def test_fit_pads(self):
        self.assertEqual(display_width(fit("课", 6)), 6)


class ListJsonTest(unittest.TestCase):
    def test_list_contains_courses(self):
        text = render_list(build(), 1)
        self.assertIn("高等数学", text)
        self.assertIn("周一", text)
        self.assertIn("@A101", text)

    def test_list_empty_week(self):
        self.assertIn("没有课", render_list(build(), 5))

    def test_json_structure(self):
        payload = json.loads(render_json(build(), 1))
        self.assertEqual(payload["week"], 1)
        self.assertEqual(payload["week_start"], "2026-09-21")
        self.assertEqual(payload["week_end"], "2026-09-27")
        self.assertEqual(len(payload["events"]), 3)
        first = payload["events"][0]
        self.assertEqual(first["summary"], "高等数学")
        self.assertEqual(first["weekday"], 1)
        self.assertEqual(first["start"], "2026-09-21T08:00")
        self.assertEqual(first["end"], "2026-09-21T09:35")


class GridTest(unittest.TestCase):
    def test_rows_have_equal_width(self):
        lines = render_grid(build(), 1).split("\n")
        table = [line for line in lines[2:] if line]
        widths = {display_width(line) for line in table}
        self.assertEqual(len(widths), 1, "表格每行宽度必须一致，否则手机端会错位")

    def test_grid_shows_course_name(self):
        self.assertIn("高等数学", render_grid(build(), 1))

    def test_weekend_hidden_by_default_when_no_weekend_class(self):
        self.assertNotIn("周六", render_grid(build(), 1))

    def test_weekend_shown_when_forced(self):
        self.assertIn("周日", render_grid(build(), 1, show_weekend=True))


class IcsRenderTest(unittest.TestCase):
    def test_structure(self):
        text = render_ics(build(), calendar_name="2026-2027-1")
        self.assertTrue(text.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(text.rstrip().endswith("END:VCALENDAR"))
        self.assertEqual(text.count("BEGIN:VEVENT"), 3)
        self.assertEqual(text.count("END:VEVENT"), 3)
        self.assertIn("X-WR-CALNAME:2026-2027-1", text)
        self.assertIn("\r\n", text)

    def test_datetime_format(self):
        text = render_ics(build())
        self.assertIn("DTSTART:20260921T080000", text)
        self.assertIn("DTEND:20260921T093500", text)

    def test_escapes_special_chars(self):
        timetable = Timetable([occ(1, 0, 8, 0, summary="A,B;C")], term_start=TERM_START)
        text = render_ics(timetable)
        self.assertIn("SUMMARY:A\\,B\\;C", text)

    def test_uid_unique(self):
        text = render_ics(build())
        uids = [line for line in text.split("\r\n") if line.startswith("UID:")]
        self.assertEqual(len(uids), len(set(uids)))


if __name__ == "__main__":
    unittest.main()
