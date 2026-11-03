"""Pipeline rules that do not need OwnerRez credentials."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build
import fetch.ownerrez as ownerrez
from fetch.check_window import main as window_main


TODAY = date(2026, 11, 3)
NOW = datetime(2026, 11, 3, 19, 5, tzinfo=timezone.utc)


def stay(pid, arrival, departure, status="active", kind="booking", bid=1):
    return {
        "id": bid,
        "property_id": pid,
        "arrival": arrival,
        "departure": departure,
        "status": status,
        "type": kind,
        "check_in": "15:00",
        "check_out": "10:00",
        "guest": {"first_name": "Olivia", "last_name": "Stott"},
    }


class QueryTests(unittest.TestCase):
    def test_booking_query_is_a_calendar_pull(self):
        params = ownerrez.booking_params([8, 6], date(2026, 11, 2), date(2027, 1, 2))
        self.assertEqual(params["property_ids"], "8,6")
        self.assertEqual(params["from"], "2026-11-02")
        self.assertEqual(params["to"], "2027-01-02")
        self.assertNotIn("since_utc", params)
        self.assertNotIn("offset", params)

    def test_pages_follow_next_url_not_a_short_page(self):
        pages = {
            "https://api.ownerrez.com/v2/bookings?page=1": {
                "items": [{"id": 1}, {"id": 2}],
                "next_page_url": "https://api.ownerrez.com/v2/bookings?page=2",
            },
            "https://api.ownerrez.com/v2/bookings?page=2": {
                "items": [{"id": 3}],
            },
        }
        items = ownerrez.collect_pages(pages.get, "https://api.ownerrez.com/v2/bookings?page=1")
        self.assertEqual([i["id"] for i in items], [1, 2, 3])

    def test_inactive_properties_are_split_out(self):
        active, inactive = ownerrez.split_properties([
            {"id": 1, "name": "Studio 6", "active": True},
            {"id": 2, "name": "34 Beeston St", "active": False},
        ])
        self.assertEqual([p["name"] for p in active], ["Studio 6"])
        self.assertEqual([p["name"] for p in inactive], ["34 Beeston St"])


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / "raw"
        self.out = Path(self.tmp.name) / "out"
        self.raw.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def write_live(self, props, bookings, fetched_at=None, inactive=None):
        fetched_at = fetched_at or NOW.isoformat(timespec="seconds")
        (self.raw / "ownerrez_properties.json").write_text(json.dumps(props))
        (self.raw / "ownerrez_bookings.json").write_text(json.dumps(bookings))
        (self.raw / "ownerrez_meta.json").write_text(json.dumps({
            "ok": True,
            "fetched_at": fetched_at,
            "inactive_properties": inactive or [],
        }))

    def test_confirmed_studio_stay_counts_and_inactive_is_dropped(self):
        props = [
            {"id": 6, "name": "Studio 6", "active": True},
            {"id": 7, "name": "Studio 7", "active": True},
            {"id": 34, "name": "34 Beeston St", "active": False},
            {"id": 8, "name": "8 Bilsborrow Road", "active": True},
        ]
        bookings = [
            stay(6, "2026-11-03", "2026-11-10", bid=1),
            stay(7, "2026-11-03", "2026-11-06", bid=2),
            stay(34, "2026-11-03", "2026-11-20", bid=3),
            stay(8, "2026-11-06", "2026-11-08", bid=4),
            stay(6, "2026-11-12", "2026-11-15", status="canceled", bid=5),
            stay(6, "2026-11-01", "2026-11-05", kind="block", bid=6),
            stay(7, "2026-11-20", "2026-11-22", status="pending", bid=7),
        ]
        self.write_live(props, bookings, inactive=["34 Beeston St"])
        ops = build.build(raw=self.raw, out=self.out, today=TODAY, now=NOW)
        by_name = {p["property"]: p for p in ops["pacing"]}
        self.assertNotIn("34 Beeston St", by_name)
        self.assertEqual(by_name["Studio 6"]["nights"], 7)
        self.assertEqual(by_name["Studio 7"]["nights"], 3)
        self.assertEqual(by_name["8 Bilsborrow Road"]["nights"], 2)
        self.assertEqual(ops["arrivals"][0]["property"], "Studio 6")
        self.assertEqual(ops["arrivals"][0]["guest"], "Olivia Stott")
        self.assertEqual(ops["inactive_properties"], ["34 Beeston St"])
        self.assertFalse(ops["stale"])
        self.assertEqual(ops["data_age_minutes"], 0)

    def test_missing_meta_refuses_cached_dump(self):
        (self.raw / "ownerrez_properties.json").write_text("[]")
        (self.raw / "ownerrez_bookings.json").write_text("[]")
        with self.assertRaises(SystemExit) as caught:
            build.build(raw=self.raw, out=self.out, today=TODAY, now=NOW)
        self.assertIn("Refusing to build from cached raw/", str(caught.exception))
        self.assertFalse((self.out / "ops.json").exists())

    def test_old_fetch_refuses_unless_override(self):
        fetched = (NOW - timedelta(hours=1293)).isoformat(timespec="seconds")
        self.write_live(
            [{"id": 1, "name": "Studio 6", "active": True}],
            [stay(1, "2026-09-01", "2026-09-04")],
            fetched_at=fetched,
        )
        with self.assertRaises(SystemExit) as caught:
            build.build(raw=self.raw, out=self.out, today=TODAY, now=NOW)
        self.assertIn("1293h", str(caught.exception))

        os.environ["KAMMI_ALLOW_STALE"] = "1"
        try:
            ops = build.build(raw=self.raw, out=self.out, today=TODAY, now=NOW)
        finally:
            del os.environ["KAMMI_ALLOW_STALE"]
        self.assertTrue(ops["stale"])
        self.assertGreater(ops["data_age_minutes"], 90)


class WindowTests(unittest.TestCase):
    def test_night_skips_and_manual_runs(self):
        night = datetime(2026, 11, 2, 22, 59, tzinfo=timezone.utc)
        self.assertEqual(window_main(now=night, event_name="schedule"), 2)
        self.assertEqual(window_main(now=night, event_name="workflow_dispatch"), 0)
        afternoon = datetime(2026, 11, 3, 13, 40, tzinfo=timezone.utc)
        self.assertEqual(window_main(now=afternoon, event_name="schedule"), 0)


if __name__ == "__main__":
    unittest.main()
