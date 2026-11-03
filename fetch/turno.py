"""Pull Turno cleaning projects when credentials exist.

Turno External API v2 (https://apidocs.turnoverbnb.com/):
  Authorization: Bearer token
  TBNB-Partner-ID: the partner id from Turno's API token page
  GET https://api.turnoverbnb.com/v2/projects

Secrets: TURNO_TOKEN and TURNO_PARTNER_ID. When either is missing the panel
stays "Not connected yet" and this script exits 0. Response fields are not
invented: a successful call records only that it connected and, when the
body is a list (or an object whose "data" member is a list), how many
projects came back.

The token is sent as a header and is never printed. HTTP error bodies are
discarded for the same reason.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://api.turnoverbnb.com/v2"
RAW = Path(__file__).resolve().parent.parent / "raw"
TOKEN = os.environ.get("TURNO_TOKEN", "").strip()
PARTNER_ID = os.environ.get("TURNO_PARTNER_ID", "").strip()


def project_count(body):
    """Count projects only when the JSON shape is an actual list."""
    if isinstance(body, list):
        return len(body)
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return len(body["data"])
    return None


def write(payload):
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "turno.json").write_text(json.dumps(payload, indent=1))


def main():
    if not TOKEN or not PARTNER_ID:
        missing = []
        if not TOKEN:
            missing.append("TURNO_TOKEN")
        if not PARTNER_ID:
            missing.append("TURNO_PARTNER_ID")
        write({"status": "not_connected", "detail": "Not connected yet"})
        print("turno  not connected (missing " + ", ".join(missing) + ")")
        return

    req = urllib.request.Request(
        BASE + "/projects",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "TBNB-Partner-ID": PARTNER_ID,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        write({
            "status": "error",
            "detail": f"not connected / error (HTTP {exc.code})",
        })
        print(f"turno  not connected / error (HTTP {exc.code})")
        return
    except Exception:
        write({"status": "error", "detail": "not connected / error"})
        print("turno  not connected / error")
        return

    payload = {"status": "ok", "detail": "Connected"}
    count = project_count(body)
    if count is not None:
        payload["count"] = count
    write(payload)
    print(f"turno  connected  {count if count is not None else 'response received'}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        write({"status": "error", "detail": "not connected / error"})
        print("turno  not connected / error")
        sys.exit(0)
