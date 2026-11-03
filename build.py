"""
Read raw/*.json, write out/ops.json.

This is the only file that contains business logic. Fetching is separate on
purpose. A dead OwnerRez call must fail here, not render the last dump as
if it were today's occupancy.

Every block is exception-first. The page exists to show you what is wrong,
not to list what is fine.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
OUT = ROOT / "out"

# Guest message unanswered for longer than this is an exception.
REPLY_SLA_HOURS = 4
# Occupancy for the next 30 nights below this on any listing is an exception.
PACING_FLOOR = 0.55
# Older than this, the file is a cache, not a picture of the business.
MAX_DATA_AGE_MINUTES = 90
# Confirmed guest stays and owner stays occupy a night. Blocks, quote holds
# and linked availability close the calendar for other reasons; they are not
# "booked" on this board. OwnerRez status "canceled" is the API spelling.
OCCUPANCY_TYPES = {"booking", "owner"}
CANCELLED = {"cancelled", "canceled", "declined"}


def d(v):
    """Parse a date whether the API returns ISO or DD-MM-YYYY."""
    if not v:
        return None
    s = str(v)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    for sep in ("-", "/"):
        parts = s.split(sep)
        if len(parts) == 3 and len(parts[0]) == 2:
            try:
                return date(int(parts[2]), int(parts[1]), int(parts[0]))
            except ValueError:
                return None
    return None


def prop_name(props, pid):
    for p in props:
        if str(p.get("id")) == str(pid):
            return p.get("name") or p.get("external_name") or p.get("nickname") or f"Property {pid}"
    return f"Property {pid}"


def property_is_active(prop):
    """OwnerRez omits empty fields, but `active: false` is present when off."""
    return prop.get("active") is not False


def guest_name(booking):
    if booking.get("guest_name"):
        return booking["guest_name"]
    guest = booking.get("guest") or {}
    name = " ".join(part for part in (guest.get("first_name"), guest.get("last_name")) if part)
    return name or "Guest"


def counts_as_booked(booking):
    status = str(booking.get("status", "")).lower()
    if status in CANCELLED:
        return False
    kind = str(booking.get("type") or "booking").lower()
    if kind not in OCCUPANCY_TYPES:
        return False
    if status and status != "active":
        return False
    return True


def read_ownerrez_meta(raw, now):
    path = raw / "ownerrez_meta.json"
    if not path.exists():
        sys.exit(
            "OwnerRez fetch metadata is missing (raw/ownerrez_meta.json). "
            "Refusing to build from cached raw/. Run fetch/ownerrez.py. "
            "If that reports HTTP 401, update the OWNERREZ_USER and OWNERREZ_TOKEN "
            "secrets at GitHub → Settings → Secrets and variables → Actions "
            "(or in .env locally). Do not commit them."
        )
    try:
        meta = json.loads(path.read_text())
    except json.JSONDecodeError:
        sys.exit("raw/ownerrez_meta.json is not valid JSON. Refusing to build.")
    if not meta.get("ok"):
        sys.exit("OwnerRez fetch did not succeed. Refusing to build from cached raw/.")
    try:
        fetched = datetime.fromisoformat(meta["fetched_at"])
    except (KeyError, TypeError, ValueError):
        sys.exit("raw/ownerrez_meta.json has no fetched_at timestamp. Refusing to build.")
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    minutes = int((now - fetched).total_seconds() // 60)
    if minutes < 0:
        minutes = 0
    stale = minutes > MAX_DATA_AGE_MINUTES
    if stale and os.environ.get("KAMMI_ALLOW_STALE") != "1":
        hours, mins = divmod(minutes, 60)
        sys.exit(
            f"OwnerRez data is {hours}h {mins}m old (fetched {meta['fetched_at']}). "
            "Refusing to render it as current. Re-run fetch/ownerrez.py against the "
            "live API. Set KAMMI_ALLOW_STALE=1 only to inspect the old file."
        )
    return meta, minutes, stale, fetched


def build(raw=None, out=None, today=None, now=None):
    raw = raw or RAW
    out = out or OUT
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    meta, book_minutes, stale, fetched = read_ownerrez_meta(raw, now)

    def read_json(name, default):
        path = raw / f"{name}.json"
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return default

    props = read_json("ownerrez_properties", [])
    bookings = read_json("ownerrez_bookings", [])
    pipeline = read_json("ghl_pipeline", {})
    issues = read_json("maintenance", [])

    props = [p for p in props if property_is_active(p)]
    active_ids = {str(p.get("id")) for p in props}
    active = [
        b for b in bookings
        if counts_as_booked(b) and str(b.get("property_id")) in active_ids
    ]

    # --- Block 1: today's movements -------------------------------------
    arrivals, departures = [], []
    for b in active:
        arr, dep = d(b.get("arrival")), d(b.get("departure"))
        name = prop_name(props, b.get("property_id"))
        if arr == today:
            arrivals.append({
                "property": name,
                "guest": guest_name(b),
                "nights": (dep - arr).days if arr and dep else None,
                "booking_id": b.get("id"),
                "checkin": b.get("check_in") or "15:00",
            })
        if dep == today:
            departures.append({
                "property": name,
                "booking_id": b.get("id"),
                "checkout": b.get("check_out") or "10:00",
            })

    dep_props = {x["property"] for x in departures}
    arr_props = {x["property"] for x in arrivals}
    same_day = sorted(dep_props & arr_props)

    for a in arrivals:
        a["same_day"] = a["property"] in same_day

    # --- Block 2: exceptions --------------------------------------------
    exceptions = []

    for i in issues:
        opened = d(i.get("opened"))
        age = (today - opened).days if opened else 0
        if i.get("status") == "open" and (i.get("urgent") or age >= 3):
            age_txt = "raised today" if age == 0 else f"open {age}d"
            exceptions.append({
                "severity": "critical" if i.get("urgent") else "watch",
                "what": f"{i.get('summary', 'Open job')}. {i.get('property', '')}, {age_txt}.",
                "who": i.get("assigned_to") or "Unassigned",
            })

    # --- Block 3: forward pacing ----------------------------------------
    booked = {}
    for b in active:
        arr, dep = d(b.get("arrival")), d(b.get("departure"))
        if not arr or not dep:
            continue
        name = prop_name(props, b.get("property_id"))
        n = arr
        while n < dep:
            if today <= n < today + timedelta(days=30):
                booked.setdefault(name, set()).add(n)
            n += timedelta(days=1)

    all_props = sorted({prop_name(props, p.get("id")) for p in props} or booked.keys())
    pacing = []
    for name in all_props:
        nights = len(booked.get(name, set()))
        occ = nights / 30 if all_props else 0
        pacing.append({"property": name, "nights": nights, "occupancy": round(occ, 3)})
    pacing.sort(key=lambda p: p["occupancy"])

    # Only the two worst. If six listings are soft that is a pricing review,
    # not six morning tasks, and it belongs in the pacing block below.
    soft = [p for p in pacing if p["occupancy"] < PACING_FLOOR]
    for p in soft[:2]:
        exceptions.append({
            "severity": "watch",
            "what": f"{p['property']} is {int(p['occupancy']*100)}% booked for the next 30 nights.",
            "who": "Revenue",
        })
    if len(soft) > 2:
        exceptions.append({
            "severity": "watch",
            "what": f"{len(soft)} listings are under {int(PACING_FLOOR*100)}% for the next 30 nights. Pricing review, not a morning job.",
            "who": "Revenue",
        })

    portfolio_occ = (sum(p["nights"] for p in pacing) / (30 * len(pacing))) if pacing else 0

    # --- Block 4: pipeline ----------------------------------------------
    pipe = {
        "new": pipeline.get("new_this_week", 0),
        "stale": pipeline.get("stale", []),
    }
    for lead in pipe["stale"][:3]:
        exceptions.append({
            "severity": "watch",
            "what": f"{lead.get('name', 'Lead')} has gone quiet {lead.get('days', '?')}d. {lead.get('stage', '')}.",
            "who": "Sales",
        })

    # Sort last, once every source has contributed. Hard cap at 8: a board
    # you scroll is a board you stop reading. If this truncates every day,
    # the problem is upstream, not on the page.
    order = {"critical": 0, "watch": 1}
    exceptions.sort(key=lambda e: order.get(e["severity"], 9))
    hidden = max(0, len(exceptions) - 8)
    counts = {
        "critical": sum(1 for e in exceptions if e["severity"] == "critical"),
        "watch": sum(1 for e in exceptions if e["severity"] == "watch"),
    }
    exceptions = exceptions[:8]

    ops = {
        "generated": now.isoformat(timespec="seconds"),
        "updated": fetched.astimezone(ZoneInfo("Europe/London")).isoformat(timespec="seconds"),
        "fetched_at": fetched.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "date": today.isoformat(),
        "data_age_minutes": book_minutes,
        "stale": stale,
        "inactive_properties": list(meta.get("inactive_properties") or []),
        "arrivals": sorted(arrivals, key=lambda x: x["checkin"]),
        "departures": sorted(departures, key=lambda x: x["checkout"]),
        "exceptions": exceptions,
        "pacing": pacing,
        "portfolio_occupancy": round(portfolio_occ, 3),
        "pipeline": pipe,
        "hidden": hidden,
        "counts": counts,
    }

    out.mkdir(exist_ok=True)
    (out / "ops.json").write_text(json.dumps(ops, indent=1))
    print(f"built  {ops['counts']['critical']} critical  "
          f"{ops['counts']['watch']} watch  "
          f"{len(arrivals)} arrivals  {len(departures)} departures  "
          f"data {book_minutes}m old")
    print(f"portfolio {int(round(portfolio_occ * 100))}%")
    for row in pacing:
        print(f"  {int(round(row['occupancy'] * 100)):3d}%  {row['nights']:2d}n  {row['property']}")
    skipped = ops["inactive_properties"]
    if skipped:
        print("excluded inactive: " + ", ".join(skipped))
    return ops


if __name__ == "__main__":
    try:
        build()
    except Exception as e:
        sys.exit(f"build failed: {e}")
