"""
Pull raw OwnerRez data to raw/ownerrez_*.json.

Auth: OwnerRez API v2 uses HTTP Basic with the account username and a
personal access token (OwnerRez → Settings → API). Docs:
https://api.ownerrez.com/help

A failed fetch must not look like a successful one. This script writes
raw/ only after both the active-property list and the booking calendar
come back. build.py refuses to run without a fresh raw/ownerrez_meta.json,
so a dead token cannot be rendered as today's occupancy.
"""
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "https://api.ownerrez.com/v2"
RAW = Path(__file__).resolve().parent.parent / "raw"
USER = os.environ.get("OWNERREZ_USER", "").strip()
TOKEN = os.environ.get("OWNERREZ_TOKEN", "").strip()
UA = os.environ.get("OWNERREZ_UA", "KammiliOps/1.0 (ops@kammiliproperties.uk)")
LONDON = ZoneInfo("Europe/London")
PAGE_CAP = 50


def credentials_missing_message():
    return (
        "OWNERREZ_USER and OWNERREZ_TOKEN are not set. "
        "Nothing was fetched, and the dashboard will not build from cached raw/. "
        "Create a personal access token in OwnerRez (Settings → API) and store it "
        "as repository secrets OWNERREZ_USER and OWNERREZ_TOKEN at "
        "GitHub → Settings → Secrets and variables → Actions. "
        "Locally, put the same names in .env (that file is gitignored). "
        "Do not commit or paste the token into the repo."
    )


def auth_rejected_message(status):
    return (
        f"OwnerRez returned HTTP {status}. "
        "OWNERREZ_USER or OWNERREZ_TOKEN was rejected (missing, expired, or rotated). "
        "Generate a new personal access token in OwnerRez → Settings → API, then "
        "update the OWNERREZ_TOKEN secret (and OWNERREZ_USER if the username changed) "
        "at GitHub → Settings → Secrets and variables → Actions. "
        "Do not commit the token."
    )


def build_url(path, params=None):
    url = BASE + path
    if params:
        # Commas in property_ids must stay commas. OwnerRez expects
        # property_ids=1,2,3, not a repeated key and not a quoted list.
        url += "?" + urllib.parse.urlencode(params, safe=",")
    return url


def booking_params(property_ids, start, end):
    """Calendar pull: property_ids + from/to, no since_utc.

    since_utc is a change-feed cursor. Combined with a date window it is the
    wrong query for "what is on the calendar", and offset paging is deprecated.
    `from` keeps stays that depart on or after that date; `to` keeps stays
    that arrive on or before it.
    """
    return {
        "property_ids": ",".join(str(i) for i in property_ids),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "include_guest": "true",
        "include_charges": "false",
        "limit": 100,
    }


def absolute(url):
    if url.startswith("https://") or url.startswith("http://"):
        return url
    if url.startswith("/v2/"):
        return "https://api.ownerrez.com" + url
    if url.startswith("/"):
        return BASE + url
    return url


def collect_pages(fetch, url):
    """Follow next_page_url until it is absent. Do not page with offset."""
    items = []
    seen = set()
    while url and url not in seen and len(seen) < PAGE_CAP:
        seen.add(url)
        data = fetch(url)
        if not isinstance(data, dict):
            raise RuntimeError(f"OwnerRez returned {type(data).__name__}, expected an object")
        items.extend(data.get("items") or [])
        nxt = data.get("next_page_url")
        url = absolute(nxt) if nxt else None
    if url and url in seen:
        raise RuntimeError("OwnerRez next_page_url looped")
    if len(seen) >= PAGE_CAP and url:
        raise RuntimeError(f"OwnerRez pagination exceeded {PAGE_CAP} pages")
    return items


def split_properties(records):
    active, inactive = [], []
    for prop in records:
        if prop.get("active") is False:
            inactive.append(prop)
        else:
            active.append(prop)
    return active, inactive


def label(prop):
    return prop.get("name") or prop.get("external_name") or f"Property {prop.get('id')}"


class OwnerRezError(Exception):
    pass


def request_json(url):
    cred = base64.b64encode(f"{USER}:{TOKEN}".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {cred}",
        "User-Agent": UA,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise OwnerRezError(auth_rejected_message(exc.code)) from None
        raise OwnerRezError(f"OwnerRez HTTP {exc.code} for {url.split('?', 1)[0]}") from None


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def summarise(active, inactive, bookings):
    print(f"active properties: {len(active)}")
    for prop in sorted(active, key=lambda p: label(p).lower()):
        print(
            f"  property id={prop.get('id')} snoozed={bool(prop.get('is_snoozed'))} "
            f"name={label(prop)}"
        )
    print(f"inactive properties (excluded): {len(inactive)}")
    for prop in sorted(inactive, key=lambda p: label(p).lower()):
        print(f"  inactive id={prop.get('id')} name={label(prop)}")

    counts = {}
    for booking in bookings:
        status = str(booking.get("status") or "").lower() or "unknown"
        kind = str(booking.get("type") or "booking").lower()
        key = (booking.get("property_id"), kind, status)
        counts[key] = counts.get(key, 0) + 1
    names = {p.get("id"): label(p) for p in active}
    print(f"bookings fetched: {len(bookings)}")
    for (pid, kind, status), count in sorted(counts.items(), key=lambda item: (names.get(item[0][0], ""), item[0][1], item[0][2])):
        print(f"  {count:3d}  {names.get(pid, 'id ' + str(pid))}  {kind}/{status}")


def confirmed_stay_lines(active, bookings):
    """Property and dates only. Never guest names."""
    names = {p.get("id"): label(p) for p in active}
    lines = []
    for booking in bookings:
        status = str(booking.get("status") or "").lower()
        kind = str(booking.get("type") or "booking").lower()
        if kind not in ("booking", "owner") or status not in ("active", ""):
            continue
        name = names.get(booking.get("property_id"), f"id {booking.get('property_id')}")
        lines.append(f"  stay {name} {str(booking.get('arrival') or '')[:10]} → {str(booking.get('departure') or '')[:10]}")
    return lines


def main():
    if not USER or not TOKEN:
        sys.exit(credentials_missing_message())

    # One-way fingerprint of exactly what goes into the Basic-auth header,
    # so a 401 here can be compared against a known-good run without
    # printing a reversible form of the credential.
    fingerprint = hashlib.sha256(f"{USER}:{TOKEN}".encode()).hexdigest()
    print(f"auth fingerprint (sha256 of USER:TOKEN): {fingerprint}")

    today = datetime.now(LONDON).date()
    # Include stays that depart today (from = depart on or after).
    start = today - timedelta(days=1)
    end = today + timedelta(days=60)

    try:
        active_records = collect_pages(
            request_json,
            build_url("/properties", {"active": "true", "limit": 50}),
        )
        active, hidden = split_properties(active_records)
        try:
            inactive_records = collect_pages(
                request_json,
                build_url("/properties", {"active": "false", "limit": 50}),
            )
        except OwnerRezError as exc:
            print(f"warning: inactive property list skipped: {exc}", file=sys.stderr)
            inactive_records = []
        # Anything returned by active=false, plus any active=false rows that
        # slipped into the active call, is not part of the live portfolio.
        inactive = [p for p in inactive_records if p.get("id") not in {a.get("id") for a in active}]
        if hidden:
            inactive.extend(hidden)
    except OwnerRezError as exc:
        sys.exit(str(exc))

    if not active:
        sys.exit(
            "OwnerRez returned no active properties. "
            "Refusing to build an empty portfolio. "
            "Check that listings are Active in OwnerRez, and that OWNERREZ_USER "
            "is the account that owns them."
        )

    bookings = []
    seen = set()
    try:
        for prop in active:
            rows = collect_pages(
                request_json,
                build_url("/bookings", booking_params([prop["id"]], start, end)),
            )
            print(f"ok   bookings {label(prop)}  {len(rows)}")
            for row in rows:
                bid = row.get("id")
                if bid in seen:
                    continue
                seen.add(bid)
                bookings.append(row)
    except OwnerRezError as exc:
        sys.exit(str(exc))

    if not bookings and os.environ.get("KAMMI_ALLOW_EMPTY") != "1":
        sys.exit(
            f"OwnerRez returned no bookings between {start.isoformat()} and {end.isoformat()} "
            f"for {len(active)} active properties. Refusing to overwrite the last fetch "
            "with an empty calendar. Set KAMMI_ALLOW_EMPTY=1 only if the portfolio "
            "is genuinely empty."
        )

    summarise(active, inactive, bookings)
    for line in confirmed_stay_lines(active, bookings):
        print(line)

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {
        "ok": True,
        "fetched_at": fetched_at,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "active_properties": [label(p) for p in active],
        "inactive_properties": sorted({label(p) for p in inactive}),
        "booking_count": len(bookings),
    }
    # Write the payload only after every request succeeded, so a partial
    # failure cannot pair a new property list with yesterday's bookings.
    dump(RAW / "ownerrez_properties.json", active)
    dump(RAW / "ownerrez_bookings.json", bookings)
    dump(RAW / "ownerrez_meta.json", meta)
    print(f"ok   ownerrez  {len(active)} active properties  {len(bookings)} bookings  fetched {fetched_at}")


if __name__ == "__main__":
    main()
