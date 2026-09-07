"""
Pull raw OwnerRez data to raw/ownerrez_*.json

Auth: OwnerRez API v2 uses HTTP Basic with your account username and a
Personal Access Token (Settings > API in OwnerRez). Confirm the exact
endpoint paths against the current docs before trusting output:
https://api.ownerrez.com/help

This script does one job: fetch and dump. No logic. If it breaks, the
dashboard still builds from the last good dump.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE = "https://api.ownerrez.com/v2"
RAW = Path(__file__).resolve().parent.parent / "raw"
USER = os.environ.get("OWNERREZ_USER", "")
TOKEN = os.environ.get("OWNERREZ_TOKEN", "")
UA = os.environ.get("OWNERREZ_UA", "KammiliOps/1.0 (ops@kammiliproperties.uk)")


def get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    cred = base64.b64encode(f"{USER}:{TOKEN}".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {cred}",
        "User-Agent": UA,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def paged(path, params=None):
    """This endpoint paginates via offset/limit; there is no nextPageUrl.
    Walk offset until a page returns fewer items than the limit, cap at
    20 pages."""
    params = dict(params or {})
    limit = params.get("limit", 50)
    items, page = [], 0
    while page < 20:
        data = get(path, params)
        page_items = data.get("items", data if isinstance(data, list) else [])
        items.extend(page_items)
        if len(page_items) < limit:
            break
        params["offset"] = params.get("offset", 0) + limit
        page += 1
    return items


def main():
    if not USER or not TOKEN:
        sys.exit("Set OWNERREZ_USER and OWNERREZ_TOKEN. Nothing fetched.")

    today = date.today()
    horizon = today + timedelta(days=60)

    try:
        since = today.replace(year=today.year - 5)
    except ValueError:
        since = today.replace(year=today.year - 5, day=28)  # Feb 29 fallback

    jobs = {
        "properties": lambda: paged("/properties", {"limit": 50}),
        "bookings": lambda: paged("/bookings", {
            "since_utc": since.isoformat(),
            "from": (today - timedelta(days=3)).isoformat(),
            "to": horizon.isoformat(),
            "include_charges": "false",
            "limit": 100,
        }),
    }

    RAW.mkdir(exist_ok=True)
    failed = []
    for name, fn in jobs.items():
        try:
            data = fn()
            (RAW / f"ownerrez_{name}.json").write_text(json.dumps(data, indent=1))
            print(f"ok   ownerrez_{name}  {len(data)} records")
        except urllib.error.HTTPError as e:
            failed.append(f"{name}: HTTP {e.code} {e.reason}")
        except Exception as e:
            failed.append(f"{name}: {e}")

    for f in failed:
        print("FAIL " + f, file=sys.stderr)
    # Stale dumps are better than no dashboard. Exit 0 unless everything died.
    sys.exit(1 if len(failed) == len(jobs) else 0)


if __name__ == "__main__":
    main()
