"""
Pull raw Turno cleaning-job data to raw/turno.json.

PARKED: not wired into run.sh or the GitHub Actions workflow, and build.py
does not read raw/turno.json yet. This sits here unused until real Turno
partner API credentials are in hand. Do not add it to any pipeline step
without confirming the details below against the current docs.

Auth: Turno's External API v2 (apidocs.turnoverbnb.com) is OAuth 2.0 bearer
tokens plus a partner ID header, granted on request to partners -- not a
simple static API key. Access and refresh tokens last about a year.
  TURNO_API_KEY     the OAuth access token
  TURNO_PARTNER_ID  the partner ID Turno issued you, sent as TBNB-Partner-ID

Endpoint: the resource is called "projects" in Turno's API (a project is a
cleaning). Base URL, exact path, query params (date filtering, pagination)
and response shape below are UNCONFIRMED -- the public docs site is a JS
app that would not yield endpoint details to automated fetching. Verify
everything against https://apidocs.turnoverbnb.com/ (or your partner
onboarding docs) before this is ever added to run.sh or the workflow.

This script does one job: fetch and dump. No logic. If it breaks, nothing
downstream notices, because nothing downstream reads its output yet.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE = "https://api.turnoverbnb.com/v2"  # TODO: confirm against current docs
RAW = Path(__file__).resolve().parent.parent / "raw"
API_KEY = os.environ.get("TURNO_API_KEY", "")
PARTNER_ID = os.environ.get("TURNO_PARTNER_ID", "")


def get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {API_KEY}",
        "TBNB-Partner-ID": PARTNER_ID,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def fetch_cleaning_jobs():
    today = date.today()
    horizon = today + timedelta(days=60)
    # TODO: confirm path and param names ("projects" and from/to are a guess).
    return get("/projects", {
        "from": today.isoformat(),
        "to": horizon.isoformat(),
    })


def main():
    RAW.mkdir(exist_ok=True)
    if not API_KEY or not PARTNER_ID:
        sys.exit("Set TURNO_API_KEY and TURNO_PARTNER_ID. Nothing fetched.")

    data = fetch_cleaning_jobs()
    (RAW / "turno.json").write_text(json.dumps(data, indent=1))
    print(f"ok   turno  {len(data)} records")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAIL turno: {e}", file=sys.stderr)
