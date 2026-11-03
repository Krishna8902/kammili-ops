"""Phase 1 panels: turnovers, task tracker, Turno shape, Enso CSV."""
import csv
import io
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build
from fetch.enso import summarise
from fetch.tasks import parse_workbook
from fetch.turno import project_count


TODAY = date(2026, 11, 3)  # Tuesday; this week's Monday is 2 Nov


def workbook():
    wb = openpyxl.Workbook()
    older = wb.active
    older.title = "WC 26 Oct"
    older["A1"] = "DAILY TASK TRACKER — Week commencing 26 Oct 2026"
    current = wb.create_sheet("WC 02 Nov")
    current["A1"] = "DAILY TASK TRACKER — Week commencing 02 Nov 2026"
    headers = ["TASKS", "Start Date", "End Date", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Priority", None, "Key"]
    for col, value in enumerate(headers, 1):
        if value:
            current.cell(2, col, value)
    current["A3"] = "Date"
    # Excel serials for 2–8 Nov 2026. Epoch is 1899-12-30.
    for offset, col in enumerate(range(4, 11)):
        serial = (date(2026, 11, 2) + timedelta(days=offset) - date(1899, 12, 30)).days
        current.cell(3, col, serial)
    current["M3"] = "Urgent"
    # Daily row: Monday missed, Tuesday done. Key legend must not count as done.
    current["A4"] = "Check inboxes (Daily)"
    current["B4"] = datetime(2026, 11, 2)
    current["C4"] = datetime(2026, 11, 8)
    current["E4"] = "Done"
    current["M4"] = "Done within 1 day"
    # Overdue, with a progress note, and "Done by Krishna" is a different row.
    current["A5"] = "Send the invoice"
    current["B5"] = datetime(2026, 10, 28)
    current["C5"] = datetime(2026, 11, 1)
    current["D5"] = "Called"
    current["E5"] = "ongoing"
    current["K5"] = "Urgent"
    current["A6"] = "Finished job"
    current["C6"] = datetime(2026, 11, 1)
    current["D6"] = "Done by Krishna"
    # Future end date: not overdue.
    current["A7"] = "Still open"
    current["C7"] = datetime(2026, 11, 6)
    # Krishna block.
    current["A12"] = "KRISHNA TASKS"
    for col, value in enumerate(["Start Date", "End Date", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Priority"], 2):
        current.cell(12, col, value)
    for offset, col in enumerate(range(4, 11)):
        current.cell(13, col, f"{2 + offset:02d} Nov")
    current["A13"] = "Date"
    current["A14"] = "Bookkeeping"
    current["C14"] = datetime(2026, 10, 30)
    current["D14"] = "waiting"
    return wb


class TaskTests(unittest.TestCase):
    def test_current_week_overdue_missed_and_key_column(self):
        parsed = parse_workbook(workbook(), TODAY)
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["sheet"], "WC 02 Nov")
        overdue = {(item["owner"], item["task"]): item for item in parsed["overdue"]}
        self.assertEqual(set(overdue), {("Team", "Send the invoice"), ("Krishna", "Bookkeeping")})
        invoice = overdue[("Team", "Send the invoice")]
        self.assertEqual(invoice["days_overdue"], 2)
        self.assertEqual(invoice["note"], "ongoing")
        self.assertEqual(invoice["priority"], "Urgent")
        self.assertEqual(overdue[("Krishna", "Bookkeeping")]["days_overdue"], 4)
        self.assertNotIn(("Team", "Finished job"), overdue)
        self.assertNotIn(("Team", "Still open"), overdue)
        self.assertNotIn(("Team", "Check inboxes (Daily)"), overdue)
        missed = parsed["missed_daily"]
        self.assertEqual(len(missed), 1)
        self.assertEqual(missed[0]["owner"], "Team")
        self.assertEqual(missed[0]["days"], ["2026-11-02"])

    def test_fallback_is_the_latest_dated_tab(self):
        wb = openpyxl.Workbook()
        first = wb.active
        first.title = "WC 20 Jul"
        first["A1"] = "Week commencing 20 Jul 2026"
        later = wb.create_sheet("WC 26 Oct")
        later["A1"] = "Week commencing 26 Oct 2026"
        # No WC 02 Nov tab, so 3 Nov falls through to the latest dated tab.
        self.assertEqual(parse_workbook(wb, TODAY)["sheet"], "WC 26 Oct")


class TurnoverTests(unittest.TestCase):
    def test_same_day_today_and_tomorrow_use_property_times(self):
        props = [
            {"id": 6, "name": "Studio 6", "active": True},
            {"id": 34, "name": "34 Beeston St", "active": False},
        ]
        bookings = [
            {"id": 1, "property_id": 6, "status": "active", "type": "booking",
             "arrival": "2026-10-28", "departure": "2026-11-03",
             "check_in": "15:00", "check_out": "10:00",
             "cleaning_date": "2026-11-03T11:30:00"},
            {"id": 2, "property_id": 6, "status": "active", "type": "booking",
             "arrival": "2026-11-03", "departure": "2026-11-10",
             "check_in": "16:00", "check_out": "10:00",
             "cleaning_date": "2026-11-10T11:00:00"},
            {"id": 3, "property_id": 6, "status": "active", "type": "booking",
             "arrival": "2026-11-04", "departure": "2026-11-06",
             "check_in": "15:00", "check_out": "10:00"},
            {"id": 4, "property_id": 34, "status": "active", "type": "booking",
             "arrival": "2026-11-03", "departure": "2026-11-04",
             "check_in": "15:00", "check_out": "10:00"},
            {"id": 5, "property_id": 6, "status": "active", "type": "block",
             "arrival": "2026-11-05", "departure": "2026-11-05",
             "check_in": "12:00", "check_out": "12:00"},
        ]
        props = [p for p in props if build.property_is_active(p)]
        schedule = build.turnovers(props, bookings, TODAY)
        today = schedule["days"][0]
        self.assertEqual(today["when"], "today")
        self.assertEqual(len(today["rows"]), 1)
        row = today["rows"][0]
        self.assertTrue(row["same_day"])
        self.assertEqual(row["property"], "Studio 6")
        self.assertEqual(row["check_out"], "10:00")
        self.assertEqual(row["check_in"], "16:00")
        self.assertEqual(row["cleaning"], "3 Nov 11:30")
        tomorrow = schedule["days"][1]
        self.assertEqual(tomorrow["when"], "tomorrow")
        self.assertEqual(tomorrow["rows"][0]["check_in"], "15:00")
        self.assertIsNone(tomorrow["rows"][0]["check_out"])
        self.assertEqual(schedule["same_day"], 1)
        self.assertNotIn("34 Beeston St", [r["property"] for d in schedule["days"] for r in d["rows"]])
        # The block on 5 Nov is not a confirmed stay.
        fifth = [d for d in schedule["days"] if d["date"] == "2026-11-05"]
        self.assertEqual(fifth, [])


class EnsoTests(unittest.TestCase):
    def test_average_and_median_over_the_last_30_days(self):
        text = """received_at,first_reply_at,property,conversation_id
2026-10-20T09:00:00+00:00,2026-10-20T09:20:00+00:00,Example,a
2026-10-21T09:00:00+00:00,2026-10-21T10:00:00+00:00,Example,b
2026-09-01T09:00:00+00:00,2026-09-01T12:00:00+00:00,Example,old
"""
        rows = list(csv.DictReader(io.StringIO(text)))
        summary = summarise(rows, TODAY)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["average_minutes"], 40.0)
        self.assertEqual(summary["median_minutes"], 40.0)

    def test_median_of_an_even_count_averages_the_middle(self):
        text = """received_at,first_reply_at
2026-11-01T10:00:00+00:00,2026-11-01T10:10:00+00:00
2026-11-01T11:00:00+00:00,2026-11-01T12:00:00+00:00
"""
        rows = list(csv.DictReader(io.StringIO(text)))
        summary = summarise(rows, TODAY)
        self.assertEqual(summary["average_minutes"], 35.0)
        self.assertEqual(summary["median_minutes"], 35.0)


class TurnoTests(unittest.TestCase):
    def test_count_only_real_lists(self):
        self.assertEqual(project_count([{"id": 1}, {"id": 2}]), 2)
        self.assertEqual(project_count({"data": [{"id": 1}]}), 1)
        self.assertIsNone(project_count({"data": {"id": 1}}))
        self.assertIsNone(project_count({"projects": [{"id": 1}]}))


if __name__ == "__main__":
    unittest.main()
