# -*- coding: utf-8 -*-
"""插件纯函数单测（不依赖 astrbot）。"""

import importlib.util
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "yanhe_schedule_format", ROOT / "core" / "format.py"
)
fmt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fmt)


class FakeOccurrence:
    def __init__(self, summary, start, end, location="", teacher=""):
        self.summary = summary
        self.start = start
        self.end = end
        self.location = location
        self.teacher = teacher


class ParseArgsTest(unittest.TestCase):
    def test_plain_week(self):
        args = fmt.parse_schedule_args("课表 9")
        self.assertEqual(args["week"], 9)
        self.assertEqual(args["action"], "")

    def test_week_and_view(self):
        args = fmt.parse_schedule_args("课表 第9周 表格")
        self.assertEqual(args["week"], 9)
        self.assertEqual(args["view"], "grid")

    def test_refresh_and_json(self):
        args = fmt.parse_schedule_args("课表 json 刷新")
        self.assertTrue(args["refresh"])
        self.assertEqual(args["view"], "json")

    def test_today_tomorrow(self):
        self.assertEqual(fmt.parse_schedule_args("课表 今天")["action"], "today")
        self.assertEqual(fmt.parse_schedule_args("课表 明天")["action"], "tomorrow")

    def test_terms(self):
        self.assertEqual(fmt.parse_schedule_args("课表 学期")["action"], "terms")

    def test_set_term(self):
        args = fmt.parse_schedule_args("课表 学期 2026-2027-1")
        self.assertEqual(args["action"], "set_term")
        self.assertEqual(args["term"], "2026-2027-1")

    def test_reset_term(self):
        args = fmt.parse_schedule_args("课表 学期 默认")
        self.assertEqual(args["action"], "set_term")
        self.assertEqual(args["term"], "")

    def test_help(self):
        self.assertTrue(fmt.parse_schedule_args("课表 帮助")["help"])
        self.assertTrue(fmt.parse_schedule_args("schedule help")["help"])

    def test_english_command_and_args(self):
        args = fmt.parse_schedule_args("schedule 9 grid")
        self.assertEqual(args["week"], 9)
        self.assertEqual(args["view"], "grid")
        self.assertEqual(fmt.parse_schedule_args("schedule today")["action"], "today")
        self.assertEqual(fmt.parse_schedule_args("schedule tomorrow")["action"], "tomorrow")
        self.assertEqual(fmt.parse_schedule_args("schedule terms")["action"], "terms")
        self.assertEqual(
            fmt.parse_schedule_args("schedule terms 2026-2027-1")["term"], "2026-2027-1"
        )

    def test_command_name_is_ignored_as_token(self):
        # /schedule 9 里的 schedule 不应被当成周次或视图
        args = fmt.parse_schedule_args("/schedule 9")
        self.assertEqual(args["week"], 9)
        self.assertIsNone(args["view"])


class FormatTest(unittest.TestCase):
    def setUp(self):
        self.events = [
            FakeOccurrence(
                "示例课程A",
                datetime(2026, 10, 19, 13, 20),
                datetime(2026, 10, 19, 14, 55),
                "示例楼101",
                "某老师",
            ),
            FakeOccurrence(
                "示例课程B",
                datetime(2026, 10, 19, 15, 15),
                datetime(2026, 10, 19, 17, 40),
                "示例楼202",
                "另一位老师",
            ),
        ]

    def test_format_day(self):
        text = fmt.format_day(self.events, date(2026, 10, 19))
        self.assertIn("周一", text)
        self.assertIn("示例课程A", text)
        self.assertIn("@示例楼101", text)

    def test_format_empty_day(self):
        text = fmt.format_day(self.events, date(2026, 10, 20))
        self.assertIn("没有课", text)

    def test_next_class(self):
        occurrence = fmt.next_class(self.events, datetime(2026, 10, 19, 12, 0))
        self.assertEqual(occurrence.summary, "示例课程A")

    def test_next_class_ongoing(self):
        text = fmt.format_next(self.events, datetime(2026, 10, 19, 13, 30))
        self.assertIn("正在上", text)
        self.assertIn("示例课程A", text)

    def test_next_class_none(self):
        self.assertIsNone(fmt.next_class(self.events, datetime(2026, 11, 30, 12, 0)))

    def test_format_terms(self):
        rows = [
            {"dm": "2026-2027-1", "mc": "2026-2027学年 1学期"},
            {"dm": "2025-2026-2", "mc": "2025-2026学年 2学期"},
        ]
        text = fmt.format_terms(rows, "2026-2027-1")
        self.assertIn("← 当前", text)
        self.assertIn("2025-2026-2", text)


if __name__ == "__main__":
    unittest.main()
