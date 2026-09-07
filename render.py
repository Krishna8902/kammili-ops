"""Render out/ops.json into out/index.html. Static file, no framework,
no runtime dependencies."""
import json
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"

CSS = """
:root{
  --paper:#f2f3f1; --ink:#191c1a; --soft:#6c736e; --rule:#d2d6d1;
  --critical:#a62b1f; --watch:#8a6a12; --calm:#2f5344; --band:#e6e8e4;
}
@media (prefers-color-scheme: dark){
  :root{ --paper:#161917; --ink:#eceee9; --soft:#8e968f; --rule:#2c312e;
         --critical:#e8705f; --watch:#d3a63c; --calm:#7fb59c; --band:#1f2320; }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:16px; line-height:1.45; font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:760px; margin:0 auto; padding:28px 20px 72px}
.meta{display:flex; justify-content:space-between; gap:12px;
  font-size:13px; color:var(--soft); letter-spacing:.01em}
.stale{color:var(--critical); font-weight:600}
.verdict{
  font-size:clamp(28px,5.4vw,40px); line-height:1.12; font-weight:640;
  letter-spacing:-.022em; margin:26px 0 4px; max-width:18ch;
}
.verdict.clear{color:var(--calm)}
.sub{color:var(--soft); font-size:15px; margin:0 0 34px}
h2{font-size:15px; font-weight:640; letter-spacing:-.006em;
   margin:38px 0 2px; padding-bottom:7px; border-bottom:1.5px solid var(--ink)}

/* Exceptions: a ledger, not cards. Severity hangs in the left margin. */
.ex{list-style:none; margin:0; padding:0}
.ex li{display:grid; grid-template-columns:11px 1fr auto; gap:13px;
  align-items:baseline; padding:13px 0; border-bottom:1px solid var(--rule)}
.ex li::before{content:""; width:4px; height:4px; border-radius:50%;
  background:var(--watch); transform:translateY(-3px)}
.ex li.critical::before{background:var(--critical); width:8px; height:8px;
  margin-left:-2px}
.ex li.critical .what{font-weight:600}
.what{font-size:15.5px}
.who{font-size:13px; color:var(--soft); white-space:nowrap}
.none{padding:15px 0; color:var(--calm); font-size:15px;
  border-bottom:1px solid var(--rule)}

/* Today: out on the left, in on the right. */
.turn{margin:14px 0 0}
.turn-row{display:grid; grid-template-columns:1fr 1fr; gap:0;
  border-bottom:1px solid var(--rule)}
.turn-head{font-size:12.5px; color:var(--soft); padding:0 0 6px}
.cell{padding:11px 14px 11px 0; font-size:15px}
.cell.in{padding-left:14px; border-left:1px solid var(--rule)}
.prop{font-weight:600}
.time{color:var(--soft); font-size:13px; margin-left:7px}
.cleaner{display:block; font-size:13px; color:var(--soft); margin-top:2px}
.cleaner.missing{color:var(--critical); font-weight:600}
.flag{display:inline-block; font-size:12px; color:var(--watch);
  border:1px solid currentColor; border-radius:2px; padding:0 5px; margin-left:6px;
  vertical-align:1px}

/* Pacing: a bar per listing, lowest first. */
.pace{margin:14px 0 0}
.pace-row{display:grid; grid-template-columns:minmax(0,1fr) 96px 46px;
  gap:12px; align-items:center; padding:8px 0}
.pace-row .name{overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  font-size:15px}
.bar{height:9px; background:var(--band); position:relative}
.bar span{position:absolute; inset:0 auto 0 0; background:var(--calm)}
.bar.low span{background:var(--watch)}
.pct{text-align:right; font-size:14px; color:var(--soft)}
.total{display:flex; justify-content:space-between; padding:12px 0 0;
  margin-top:8px; border-top:1px solid var(--rule); font-size:14px;
  color:var(--soft)}
.total b{color:var(--ink); font-weight:640}
.foot{margin-top:46px; font-size:12.5px; color:var(--soft)}
@media (max-width:560px){
  .turn-row{grid-template-columns:1fr; padding:4px 0}
  .turn-head{display:none}
  .cell{padding:9px 0}
  .cell.in{border-left:0; padding-left:0}
  .cell:empty{display:none}
  .cell::before{content:attr(data-l); display:block; font-size:12px;
    color:var(--soft); margin-bottom:2px}
  .pace-row{grid-template-columns:minmax(0,1fr) 68px 42px}
}
"""


def verdict(ops):
    c, w = ops["counts"]["critical"], ops["counts"]["watch"]
    if c == 0 and w == 0:
        return "Nothing needs you.", "Nine listings, no exceptions. Go and sign the tenth.", True
    if c == 0:
        return f"{w} thing{'s' if w > 1 else ''} to watch.", "Nothing is broken. Check these before they are.", False
    first_in = ops["arrivals"][0]["checkin"] if ops["arrivals"] else None
    by = f" before {first_in}" if first_in else ""
    n = f"{c} things need" if c > 1 else "1 thing needs"
    tail = f" {w} more to watch." if w else ""
    return f"{n} you{by}.", f"Everything else is running.{tail}", False


def render(ops):
    head, sub, clear = verdict(ops)
    day = datetime.fromisoformat(ops["date"]).strftime("%d %B %Y")
    gen = datetime.fromisoformat(ops["generated"]).strftime("%H:%M")
    age = ops.get("data_age_minutes")
    stale = age is not None and age > 90
    if age is None:
        age_txt = "data age unknown"
    elif stale:
        age_txt = f'<span class="stale">data {age // 60}h old</span>'
    else:
        age_txt = f"data {age}m old"
    meta_txt = f"built {gen} · {age_txt}"

    h = [f'<div class="meta"><span>{day}</span><span>{meta_txt}</span></div>',
         f'<h1 class="verdict{" clear" if clear else ""}">{escape(head)}</h1>',
         f'<p class="sub">{escape(sub)}</p>']

    h.append("<h2>Needs a decision</h2>")
    if ops["exceptions"]:
        h.append('<ul class="ex">')
        for e in ops["exceptions"]:
            h.append(f'<li class="{e["severity"]}"><span class="what">'
                     f'{escape(e["what"])}</span>'
                     f'<span class="who">{escape(str(e["who"]))}</span></li>')
        h.append("</ul>")
        if ops.get("hidden"):
            h.append(f'<p class="foot" style="margin-top:12px">'
                     f'{ops["hidden"]} more below the line. If that number is '
                     f'never zero, you have a capacity problem, not a visibility one.</p>')
    else:
        h.append('<p class="none">Clear. Nothing has slipped since yesterday.</p>')

    h.append("<h2>Today on the ground</h2>")
    arr, dep = ops["arrivals"], ops["departures"]
    if arr or dep:
        h.append('<div class="turn"><div class="turn-row">'
                 '<div class="turn-head">Out</div>'
                 '<div class="turn-head" style="padding-left:14px">In</div></div>')
        for i in range(max(len(arr), len(dep))):
            h.append('<div class="turn-row">')
            if i < len(dep):
                x = dep[i]
                h.append(f'<div class="cell" data-l="Out"><span class="prop">{escape(x["property"])}'
                         f'</span><span class="time">{escape(x["checkout"])}</span></div>')
            else:
                h.append('<div class="cell"></div>')
            if i < len(arr):
                a = arr[i]
                flag = '<span class="flag">same day</span>' if a["same_day"] else ""
                h.append(f'<div class="cell in" data-l="In"><span class="prop">{escape(a["property"])}'
                         f'</span><span class="time">{escape(a["checkin"])}</span>{flag}</div>')
            else:
                h.append('<div class="cell in"></div>')
            h.append("</div>")
        h.append("</div>")
    else:
        h.append('<p class="none">No arrivals or departures today.</p>')

    h.append("<h2>Next 30 nights</h2><div class=\"pace\">")
    for p in ops["pacing"]:
        pct = int(p["occupancy"] * 100)
        low = " low" if p["occupancy"] < 0.55 else ""
        h.append(f'<div class="pace-row"><div class="name">{escape(p["property"])}</div>'
                 f'<div class="bar{low}"><span style="width:{pct}%"></span></div>'
                 f'<div class="pct">{pct}%</div></div>')
    h.append(f'<div class="total"><span>Portfolio</span>'
             f'<b>{int(ops["portfolio_occupancy"] * 100)}% booked</b></div></div>')

    pipe = ops["pipeline"]
    h.append("<h2>Pipeline</h2>")
    stale_names = ", ".join(escape(l["name"]) for l in pipe["stale"]) or "none"
    h.append(f'<p class="sub" style="margin:14px 0 0">'
             f'{pipe["new"]} new this week. Gone quiet: {stale_names}.</p>')

    h.append('<p class="foot">Built from OwnerRez. '
             'If a number here looks wrong, the source is wrong. Fix the source.</p>')

    return (f'<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="300">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex">'
            f'<title>Ops {ops["date"]}</title><style>{CSS}</style></head>'
            f'<body><main class="wrap">{"".join(h)}</main></body></html>')


if __name__ == "__main__":
    ops = json.loads((OUT / "ops.json").read_text())
    (OUT / "index.html").write_text(render(ops))
    print(f"rendered {OUT / 'index.html'}")
