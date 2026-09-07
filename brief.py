"""
Turn out/ops.json into a short plain-text brief and push it to Telegram.

This is the thing you will actually read. The HTML page is the backup.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
BOT = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def brief(ops):
    c, w = ops["counts"]["critical"], ops["counts"]["watch"]
    day = datetime.fromisoformat(ops["date"]).strftime("%d %B %Y")
    lines = [f"Ops {day}"]

    if c == 0 and w == 0:
        lines.append("Nothing needs you.")
    else:
        lines.append(f"{c} critical, {w} to watch.")

    crit = [e for e in ops["exceptions"] if e["severity"] == "critical"]
    if crit:
        lines.append("")
        for e in crit:
            lines.append(f"! {e['what']} ({e['who']})")

    arr = ops["arrivals"]
    if arr:
        lines.append("")
        lines.append(f"In today: {len(arr)}")
        for a in arr:
            cl = a["cleaner"] or "NO CLEANER"
            sd = " same day" if a["same_day"] else ""
            lines.append(f"  {a['property']} {a['checkin']} {cl}{sd}")

    dep = ops["departures"]
    if dep:
        lines.append("")
        lines.append(f"Out today: {len(dep)}")
        for x in dep:
            lines.append(f"  {x['property']} {x['checkout']}")

    lines.append("")
    lines.append(f"30 nights: {int(ops['portfolio_occupancy']*100)}% booked")
    for p in [p for p in ops["pacing"] if p["occupancy"] < 0.55][:2]:
        lines.append(f"  {p['property']} {int(p['occupancy']*100)}%")

    pipe = ops["pipeline"]
    quiet = ", ".join(l["name"] for l in pipe["stale"][:3])
    lines.append("")
    lines.append(f"Pipeline: {pipe['new']} new. Quiet: {quiet or 'none'}")

    age = ops.get("data_age_minutes")
    if age and age > 90:
        lines.append("")
        lines.append(f"WARNING data is {age // 60}h old")
    return "\n".join(lines)


def send(text):
    if not BOT or not CHAT:
        print(text)
        return
    body = urllib.parse.urlencode({"chat_id": CHAT, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT}/sendMessage", data=body)
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


if __name__ == "__main__":
    ops = json.loads((OUT / "ops.json").read_text())
    text = brief(ops)
    (OUT / "brief.txt").write_text(text)
    send(text)
    print("brief sent" if BOT else "brief printed (no TELEGRAM_BOT_TOKEN)")
