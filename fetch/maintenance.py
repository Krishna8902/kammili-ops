"""
Read the maintenance sheet, write raw/maintenance.json.

Source: a Google Sheet published to the web as CSV.
File > Share > Publish to web > choose the sheet > CSV > Publish.
Put that URL in .env as MAINTENANCE_SHEET_CSV.

Required columns (header row, exact names, any order):
  opened      date the job was raised (DD-MM-YYYY or YYYY-MM-DD)
  property    must match the OwnerRez property name exactly
  issue       one line, what is wrong
  assigned    who owns it, blank means unassigned
  status      open or done, blank means open
  priority    urgent or blank

Anything marked done is ignored. Open jobs flag on the board when they
are urgent, or when they have been open three days or more.
"""
import csv
import io
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "raw"
SHEET = os.environ.get("MAINTENANCE_SHEET_CSV", "")


def parse_date(v):
    s = str(v or "").strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    parts = s.replace("/", "-").split("-")
    if len(parts) == 3 and len(parts[0]) == 2:
        try:
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
        except ValueError:
            return None
    return None


def main():
    RAW.mkdir(exist_ok=True)
    if not SHEET:
        sys.exit("MAINTENANCE_SHEET_CSV not set. Maintenance block stays empty.")

    try:
        with urllib.request.urlopen(SHEET, timeout=30) as r:
            text = r.read().decode("utf-8-sig")
    except Exception as e:
        sys.exit(f"maintenance sheet unreachable: {e}")

    rows, skipped = [], 0
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if str(row.get("status", "")).lower() in ("done", "closed", "complete", "completed"):
            continue
        issue = row.get("issue") or row.get("summary")
        prop = row.get("property")
        opened = parse_date(row.get("opened"))
        if not issue or not prop:
            skipped += 1
            continue
        rows.append({
            "summary": issue,
            "property": prop,
            "opened": opened.isoformat() if opened else date.today().isoformat(),
            "status": "open",
            "urgent": str(row.get("priority", "")).lower() in ("urgent", "high", "yes", "y"),
            "assigned_to": row.get("assigned") or None,
        })

    (RAW / "maintenance.json").write_text(json.dumps(rows, indent=1))
    msg = f"ok   maintenance  {len(rows)} open jobs"
    if skipped:
        msg += f" ({skipped} rows skipped, missing issue or property)"
    print(msg)


if __name__ == "__main__":
    main()
