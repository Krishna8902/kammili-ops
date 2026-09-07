"""
Read your Google Calendar, write raw/calendar.json.

Source: the calendar's private iCal address, read-only by design.
Google Calendar > hover your calendar > three dots > Settings and sharing >
Integrate calendar > "Secret address in iCal format". Put it in .env as
CALENDAR_ICS_URL.

Anyone holding that URL can read your whole calendar. Keep it in .env only.
If it leaks, the same settings page has a Reset button.

NOTE: this file must NOT be called calendar.py. That name shadows Python's
own calendar module and breaks date parsing in a confusing way.

Output: [{"summary","start","end","all_day"}] for today only.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "raw"
URL = os.environ.get("CALENDAR_ICS_URL", "")


def unfold(text):
    """iCal wraps long lines with a leading space. Join them back."""
    return re.sub(r"\r?\n[ \t]", "", text)


def parse_dt(value, params):
    """Return (datetime or date, all_day). No strptime, no locale surprises."""
    v = value.strip().rstrip("Z")
    if "VALUE=DATE" in params or len(v) == 8:
        try:
            return date(int(v[0:4]), int(v[4:6]), int(v[6:8])), True
        except ValueError:
            return None, False
    if len(v) >= 15 and v[8] == "T":
        try:
            return datetime(int(v[0:4]), int(v[4:6]), int(v[6:8]),
                            int(v[9:11]), int(v[11:13]), int(v[13:15])), False
        except ValueError:
            return None, False
    return None, False


def day_of(x):
    return x.date() if isinstance(x, datetime) else x


def main():
    RAW.mkdir(exist_ok=True)
    if not URL:
        sys.exit("CALENDAR_ICS_URL not set. Calendar block stays empty.")

    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "KammiliOps/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = unfold(r.read().decode("utf-8", "replace"))
    except Exception as e:
        sys.exit(f"calendar unreachable: {e}")

    today = date.today()
    events, cur = [], None

    for line in text.split("\n"):
        line = line.strip()
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur and cur.get("start") is not None:
                s = cur["start"]
                e = cur.get("end") or s
                if day_of(s) <= today <= day_of(e) and \
                        str(cur.get("status", "")).upper() != "CANCELLED":
                    events.append({
                        "summary": cur.get("summary") or "(no title)",
                        "start": s.isoformat(),
                        "end": e.isoformat(),
                        "all_day": cur.get("all_day", False),
                    })
            cur = None
            continue
        if cur is None or ":" not in line:
            continue

        key, value = line.split(":", 1)
        name = key.split(";", 1)[0].upper()
        params = key[len(name):]

        if name == "SUMMARY":
            cur["summary"] = value.replace("\\,", ",").replace("\\n", " ").strip()
        elif name == "STATUS":
            cur["status"] = value
        elif name == "DTSTART":
            cur["start"], cur["all_day"] = parse_dt(value, params)
        elif name == "DTEND":
            cur["end"], _ = parse_dt(value, params)

    events.sort(key=lambda x: (not x["all_day"], x["start"]))
    (RAW / "calendar.json").write_text(json.dumps(events, indent=1))
    print(f"ok   calendar  {len(events)} events today")


if __name__ == "__main__":
    main()
