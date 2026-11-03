"""Enso Connect has no public API.

Drop a CSV at data/enso_response_times.csv and this script turns it into
raw/enso.json. Without that file the panel stays "Not connected yet".
A broken file exits 0 and the panel shows "not connected / error".
The OwnerRez build does not depend on it.

CSV format (header row required):

    received_at,first_reply_at,property,conversation_id

  received_at       ISO-8601 datetime the guest message arrived. Required.
  first_reply_at    ISO-8601 datetime of the first reply. Required.
  property          Optional label. Not used in the average.
  conversation_id   Optional id. Not used in the average.

Naive timestamps (no offset) are read as Europe/London. Rows whose
received_at is outside the last 30 London days are ignored. The panel
reports the average and the median of (first_reply_at - received_at)
in minutes. The median of an even count is the mean of the two middle
values.

See data/enso_response_times.example.csv for a fake sample. That example
is not read; only data/enso_response_times.csv is.
"""
import csv
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "enso_response_times.csv"
RAW = ROOT / "raw"
LONDON = ZoneInfo("Europe/London")
WINDOW_DAYS = 30


def london_today():
    return datetime.now(LONDON).date()


def parse_when(value, london):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=london)
    return parsed


def summarise(rows, today):
    """rows are dicts from csv.DictReader. Returns the raw/enso.json object."""
    start = today - timedelta(days=WINDOW_DAYS)
    minutes = []
    skipped = 0
    for row in rows:
        received = parse_when(row.get("received_at"), LONDON)
        replied = parse_when(row.get("first_reply_at"), LONDON)
        if received is None or replied is None:
            skipped += 1
            continue
        if not (start <= received.astimezone(LONDON).date() <= today):
            continue
        delta = (replied - received).total_seconds() / 60
        if delta < 0:
            skipped += 1
            continue
        minutes.append(delta)
    if not minutes:
        return {
            "status": "ok",
            "count": 0,
            "average_minutes": None,
            "median_minutes": None,
            "skipped": skipped,
            "window_days": WINDOW_DAYS,
        }
    return {
        "status": "ok",
        "count": len(minutes),
        "average_minutes": round(statistics.fmean(minutes), 1),
        "median_minutes": round(statistics.median(minutes), 1),
        "skipped": skipped,
        "window_days": WINDOW_DAYS,
    }


def write(payload):
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "enso.json").write_text(json.dumps(payload, indent=1))


def main():
    if not CSV_PATH.exists():
        write({"status": "not_connected", "detail": "Not connected yet"})
        print("enso  not connected (data/enso_response_times.csv is absent)")
        return
    try:
        with CSV_PATH.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        payload = summarise(rows, london_today())
    except Exception:
        write({"status": "error", "detail": "not connected / error"})
        print("enso  not connected / error")
        return
    write(payload)
    print(f"enso  {payload['count']} threads in {WINDOW_DAYS} days")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        write({"status": "error", "detail": "not connected / error"})
        print("enso  not connected / error")
        sys.exit(0)
