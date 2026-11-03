"""Read Krishna's weekly task tracker and write raw/tasks.json.

Source: Google Drive file "Daily_Task_Tracker_2026 (Version 2).xlsx"
(file id 1H_AF8V3JXpeWD17sx0S7IAUUkiMJ6vx7), downloaded as xlsx.

Auth: put the service-account JSON key in GOOGLE_SERVICE_ACCOUNT_JSON.
Share the workbook with that key's client_email (Viewer). The key and the
access token are never printed.

A missing secret or a failed call still exits 0. The panel shows
"Not connected yet" or "not connected / error", and the OwnerRez build
is unchanged.

Workbook layout (one tab per week, named "WC dd Mon"):
  A1 is the title.
  Two blocks, "TASKS" (the team) and "KRISHNA TASKS".
  Header columns: task name in A, Start Date, End Date, Mon..Sun, Priority.
  The row under the header holds that week's dates.
  Column headed "Key" is a legend and is ignored.
  A task is done when any other cell in the row contains "done"
  (case-insensitive, so "Done by Krishna" counts).
  Overdue means End Date is before today in London and the row is not done.
  A "(Daily)" row is not one overdue item: each past day this week with no
  "Done" in that day's column is a missed day.
  Dates may be datetimes or Excel serials (epoch 1899-12-30).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

RAW = Path(__file__).resolve().parent.parent / "raw"
FILE_ID = "1H_AF8V3JXpeWD17sx0S7IAUUkiMJ6vx7"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
LONDON = ZoneInfo("Europe/London")
EXCEL_EPOCH = date(1899, 12, 30)
MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
DAY_HEADERS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def london_today():
    return datetime.now(LONDON).date()


def norm(value):
    return str(value or "").replace("\xa0", " ").strip()


def contains_done(value):
    return "done" in norm(value).lower()


def year_in(value):
    match = re.search(r"(20\d{2})", norm(value))
    return int(match.group(1)) if match else None


def as_date(value, year_hint=None):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        serial = int(value)
        if serial <= 0:
            return None
        return EXCEL_EPOCH + timedelta(days=serial)
    text = norm(value)
    for fmt, chunk in (("%Y-%m-%d", text[:10]), ("%d/%m/%Y", text), ("%d-%m-%Y", text)):
        try:
            return datetime.strptime(chunk, fmt).date()
        except ValueError:
            pass
    match = re.match(r"(\d{1,2})\s+([A-Za-z]{3})", text)
    if match and year_hint:
        month = MONTHS.get(match.group(2).title())
        if month:
            try:
                return date(year_hint, month, int(match.group(1)))
            except ValueError:
                return None
    return None


def closest_date(day, month, today):
    options = []
    for delta in (-1, 0, 1):
        try:
            options.append(date(today.year + delta, month, day))
        except ValueError:
            pass
    return min(options, key=lambda item: abs((item - today).days))


def parse_tab_date(name, today, year):
    match = re.match(r"WC\s+(\d{1,2})\s+([A-Za-z]{3})", norm(name), re.I)
    if not match:
        return None
    month = MONTHS.get(match.group(2).title())
    if not month:
        return None
    day = int(match.group(1))
    if year:
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return closest_date(day, month, today)


def block_owner(value):
    text = norm(value).upper()
    if text == "KRISHNA TASKS":
        return "Krishna"
    if text == "TASKS":
        return "Team"
    return None


def header_columns(ws, row):
    found = {}
    for col in range(1, (ws.max_column or 1) + 1):
        key = norm(ws.cell(row, col).value).lower()
        if key and key not in found:
            found[key] = col
    return found


def choose_sheet(wb, today):
    """Current London week's Monday, else the latest dated tab."""
    dated = []
    for name in wb.sheetnames:
        year = year_in(wb[name]["A1"].value)
        monday = parse_tab_date(name, today, year)
        if monday:
            dated.append((monday, name))
    if not dated:
        return None
    current = today - timedelta(days=today.weekday())
    for monday, name in dated:
        if monday == current:
            return name
    return max(dated, key=lambda item: item[0])[1]


def _day_dates(ws, row, columns, year_hint):
    dates = {}
    for day in DAY_HEADERS:
        col = columns.get(day)
        if not col:
            continue
        dates[day] = as_date(ws.cell(row, col).value, year_hint)
    return dates


def _row_done(ws, row, key_col):
    last = ws.max_column or 1
    for col in range(1, last + 1):
        if col == key_col:
            continue
        if contains_done(ws.cell(row, col).value):
            return True
    return False


def _latest_note(ws, row, columns, day_dates):
    notes = []
    for index, day in enumerate(DAY_HEADERS):
        col = columns.get(day)
        if not col:
            continue
        text = norm(ws.cell(row, col).value)
        if not text:
            continue
        when = day_dates.get(day) or date.min
        notes.append((when, index, text))
    if not notes:
        return ""
    notes.sort()
    return notes[-1][2][:160]


def parse_workbook(wb, today):
    sheet_name = choose_sheet(wb, today)
    if not sheet_name:
        return {
            "status": "error",
            "detail": "not connected / error. No week tab named 'WC dd Mon' was found.",
            "overdue": [],
            "missed_daily": [],
        }
    ws = wb[sheet_name]
    year_hint = year_in(ws["A1"].value) or today.year
    overdue = []
    missed = []
    owner = None
    columns = {}
    day_dates = {}
    key_col = None

    for row in range(1, (ws.max_row or 1) + 1):
        owner_here = block_owner(ws.cell(row, 1).value)
        if owner_here:
            owner = owner_here
            columns = header_columns(ws, row)
            key_col = columns.get("key")
            day_dates = _day_dates(ws, row + 1, columns, year_hint)
            continue
        if not owner:
            continue
        task = norm(ws.cell(row, 1).value)
        if not task or task.lower() == "date":
            continue
        start = as_date(ws.cell(row, columns.get("start date", 2)).value, year_hint)
        end = as_date(ws.cell(row, columns.get("end date", 3)).value, year_hint)
        done = _row_done(ws, row, key_col)
        priority_col = columns.get("priority")
        priority = norm(ws.cell(row, priority_col).value) if priority_col else ""
        daily = "(daily)" in task.lower()

        if daily:
            missed_days = []
            for day in DAY_HEADERS:
                col = columns.get(day)
                when = day_dates.get(day)
                if not col or not when or when >= today:
                    continue
                if start and when < start:
                    continue
                if end and when > end:
                    continue
                if contains_done(ws.cell(row, col).value):
                    continue
                missed_days.append(when.isoformat())
            if missed_days:
                missed.append({
                    "owner": owner,
                    "task": task,
                    "days": missed_days,
                })
            continue

        if end and end < today and not done:
            overdue.append({
                "owner": owner,
                "task": task,
                "end": end.isoformat(),
                "days_overdue": (today - end).days,
                "note": _latest_note(ws, row, columns, day_dates),
                "priority": priority,
            })

    overdue.sort(key=lambda item: (-item["days_overdue"], item["owner"], item["task"]))
    return {
        "status": "ok",
        "sheet": sheet_name,
        "overdue": overdue,
        "missed_daily": missed,
    }


def _write(payload):
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "tasks.json").write_text(json.dumps(payload, indent=1))


def _error(detail):
    _write({"status": "error", "detail": detail, "overdue": [], "missed_daily": []})
    print(f"tasks  {detail}")


def download_xlsx(token):
    url = f"https://www.googleapis.com/drive/v3/files/{FILE_ID}?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read(), None
    except urllib.error.HTTPError as exc:
        return None, exc.code


def main():
    raw_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip().lstrip("\ufeff")
    if not raw_key:
        _write({
            "status": "not_connected",
            "detail": "Not connected yet",
            "overdue": [],
            "missed_daily": [],
        })
        print("tasks  not connected (GOOGLE_SERVICE_ACCOUNT_JSON is unset)")
        return

    try:
        info = json.loads(raw_key)
    except json.JSONDecodeError:
        _error("not connected / error. GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON.")
        return
    if not isinstance(info, dict) or not info.get("client_email") or not info.get("private_key"):
        _error("not connected / error. The service account JSON is missing client_email or private_key.")
        return

    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        credentials.refresh(google.auth.transport.requests.Request())
        token = credentials.token
    except Exception:
        # Do not print the exception: google-auth errors can echo key material.
        _error("not connected / error. The service account JSON was rejected.")
        return

    blob, status = download_xlsx(token)
    if status == 403 or status == 404:
        _error(
            "not connected / error. Drive returned HTTP "
            f"{status}. Share the tracker with the service account email as Viewer."
        )
        return
    if blob is None:
        _error(f"not connected / error. Drive returned HTTP {status}.")
        return

    try:
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=False)
        payload = parse_workbook(wb, london_today())
    except Exception:
        _error("not connected / error. The workbook could not be parsed.")
        return

    _write(payload)
    overdue = len(payload.get("overdue") or [])
    missed = sum(len(item.get("days") or []) for item in payload.get("missed_daily") or [])
    print(f"tasks  {payload.get('status')}  sheet {payload.get('sheet', '-')}  "
          f"{overdue} overdue  {missed} missed daily days")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _error("not connected / error. The task fetch failed.")
        sys.exit(0)
