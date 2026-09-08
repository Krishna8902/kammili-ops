"""
Read raw/*.json, write out/ops.json.

This is the only file that contains business logic. Fetching is separate on
purpose: a dead API gives you a stale dashboard, not no dashboard.

Every block is exception-first. The page exists to show you what is wrong,
not to list what is fine.
"""
import json
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


def load(name, default):
    p = RAW / f"{name}.json"
    if not p.exists():
        return default, None
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(
        p.stat().st_mtime, tz=timezone.utc)
    try:
        return json.loads(p.read_text()), age
    except json.JSONDecodeError:
        return default, age


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
        if p.get("id") == pid:
            return p.get("name") or p.get("nickname") or f"Property {pid}"
    return f"Property {pid}"


def build():
    today = date.today()
    props, _ = load("ownerrez_properties", [])
    bookings, book_age = load("ownerrez_bookings", [])
    pipeline, _ = load("ghl_pipeline", {})
    issues, _ = load("maintenance", [])

    active = [b for b in bookings
              if str(b.get("status", "")).lower() not in ("cancelled", "canceled", "declined")]

    # --- Block 1: today's movements -------------------------------------
    arrivals, departures = [], []
    for b in active:
        arr, dep = d(b.get("arrival")), d(b.get("departure"))
        name = prop_name(props, b.get("property_id"))
        if arr == today:
            arrivals.append({
                "property": name,
                "guest": b.get("guest_name") or "Guest",
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
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "updated": datetime.now(ZoneInfo("Europe/London")).isoformat(timespec="seconds"),
        "date": today.isoformat(),
        "data_age_minutes": int(book_age.total_seconds() / 60) if book_age else None,
        "arrivals": sorted(arrivals, key=lambda x: x["checkin"]),
        "departures": sorted(departures, key=lambda x: x["checkout"]),
        "exceptions": exceptions,
        "pacing": pacing,
        "portfolio_occupancy": round(portfolio_occ, 3),
        "pipeline": pipe,
        "hidden": hidden,
        "counts": counts,
    }

    OUT.mkdir(exist_ok=True)
    (OUT / "ops.json").write_text(json.dumps(ops, indent=1))
    print(f"built  {ops['counts']['critical']} critical  "
          f"{ops['counts']['watch']} watch  "
          f"{len(arrivals)} arrivals  {len(departures)} departures")
    return ops


if __name__ == "__main__":
    try:
        build()
    except Exception as e:
        sys.exit(f"build failed: {e}")
