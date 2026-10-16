"""Visual reports: standalone HTML (inline SVG charts, embedded thumbnails),
PDF via the machine's own Edge/Chrome in headless mode, and CSV exports.

A report is regenerated only when its input hash changes (same period, same
data → reuse the saved file).
"""

import base64
import csv
import hashlib
import html
import io
import json
import os
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

from growth_os import analytics, brands
from growth_os.db import DATA_DIR, new_id, utcnow

REPORTS_DIR = DATA_DIR / "reports"


def esc(s):
    return html.escape(str(s if s is not None else ""))


def fmt(v, kind="int"):
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v * 100:.1f}%" if abs(v) <= 1.5 else f"{v:.1f}%"
    if kind == "change":
        return f"{'+' if v >= 0 else '−'}{abs(v) * 100:.1f}%"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f}M"
    if abs(v) >= 1e4:
        return f"{v / 1e3:.1f}K"
    return f"{v:,.0f}"


def svg_line(points, w=640, h=180, color="#a88c1c", label=""):
    """Points: [(label, value)]. Single series, recessive grid, end label."""
    if len(points) < 2:
        return f'<p class="muted">Not enough data for a chart.</p>'
    vals = [p[1] for p in points]
    lo, hi = 0, max(vals) or 1
    pad_l, pad_b, pad_t = 44, 22, 10
    iw, ih = w - pad_l - 50, h - pad_b - pad_t
    xs = [pad_l + i * iw / (len(points) - 1) for i in range(len(points))]
    ys = [pad_t + ih - (v - lo) / (hi - lo) * ih for v in vals]
    grid = "".join(
        f'<line x1="{pad_l}" x2="{pad_l + iw}" y1="{pad_t + ih * f:.1f}" y2="{pad_t + ih * f:.1f}" stroke="#e5e5e2"/>'
        f'<text x="{pad_l - 6}" y="{pad_t + ih * f + 4:.1f}" text-anchor="end" font-size="10" fill="#77756f">{fmt(hi * (1 - f))}</text>'
        for f in (0, 0.5, 1))
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    ticks = "".join(f'<text x="{xs[i]:.1f}" y="{h - 6}" font-size="10" fill="#77756f" text-anchor="middle">{esc(points[i][0][5:])}</text>'
                    for i in (0, len(points) // 2, len(points) - 1))
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}" style="width:100%;height:auto">{grid}'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
            f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="4" fill="{color}"/>'
            f'<text x="{xs[-1] + 8:.1f}" y="{ys[-1] + 4:.1f}" font-size="11" fill="#1d1d1b">{fmt(vals[-1])}</text>{ticks}</svg>')


def thumb_data_uri(tenant_id, asset_id):
    p = DATA_DIR / "thumbs" / tenant_id / f"{asset_id}.jpg"
    if not p.exists():
        return None
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()


def build_data(conn, tenant_id, start, end):
    brand = brands.get_brand(conn, tenant_id)
    days = (end - start).days + 1
    kpis = [analytics.kpi(conn, tenant_id, m, days) for m in
            ("views", "estimatedMinutesWatched", "subscribersGained", "averageViewDuration")]
    vids = analytics.videos(conn, tenant_id)
    in_period = [v for v in vids if v["published_at"] and start.isoformat() <= v["published_at"][:10] <= end.isoformat()]
    ranked = sorted([v for v in vids if v["views_per_day"] is not None], key=lambda v: v["views_per_day"], reverse=True)
    recs = [dict(r) for r in conn.execute(
        "SELECT * FROM recommendations WHERE tenant_id=? AND status='open' ORDER BY priority, created_at DESC LIMIT 3",
        (tenant_id,))]
    trs = [dict(r) for r in conn.execute(
        "SELECT * FROM trends WHERE tenant_id=? AND status!='dismissed' ORDER BY score DESC LIMIT 6", (tenant_id,))]
    acts = [dict(r) for r in conn.execute(
        """SELECT l.to_state, l.actor, l.note, l.at, r.title, r.result_json FROM action_ledger l JOIN recommendations r
           ON r.id=l.rec_id WHERE l.tenant_id=? AND l.at>=? AND l.at<? AND l.to_state IN
           ('approved','executed','verified','evaluated','reverted','blocked','failed') ORDER BY l.at""",
        (tenant_id, start.isoformat(), (end + timedelta(days=2)).isoformat()))]  # ledger is UTC; period is local
    return {
        "actions": [{"state": analytics.STATE_LABELS.get(a["to_state"], a["to_state"]), "title": a["title"],
                     "at": a["at"][:10], "note": a["note"], "outcome": _outcome(a)} for a in acts],
        "brand": dict(brand), "start": start.isoformat(), "end": end.isoformat(),
        "kpis": [k for k in kpis if k], "series": analytics.series(conn, tenant_id, "views", days),
        "published": [{k: v[k] for k in ("asset_id", "title", "published_at", "format")} | {"views": v["metrics"].get("views")}
                      for v in in_period],
        "top": [{k: v[k] for k in ("asset_id", "title", "views_per_day", "format")} for v in ranked[:5]],
        "bottom": [{k: v[k] for k in ("asset_id", "title", "views_per_day", "format")} for v in ranked[-3:]] if len(ranked) > 6 else [],
        "recs": [{k: r[k] for k in ("title", "detail", "basis", "priority")} for r in recs],
        "trends": [{k: t[k] for k in ("title", "source", "url", "score", "uncertainty", "published_at")} for t in trs],
        "freshness": analytics.freshness(conn, tenant_id),
        "accounts": [{k: a[k] for k in ("platform", "account_name", "platform_account_id", "state", "data_as_of")}
                     for a in brands.accounts(conn, tenant_id) if a["state"] != brands.REJECTED],
    }


def _outcome(a):
    if a["to_state"] != "evaluated" or not a["result_json"]:
        return ""
    res = json.loads(a["result_json"])
    b, af = res.get("before") or {}, res.get("after") or {}
    parts = []
    for k, lab in (("views_per_day", "views/day"), ("videoThumbnailImpressionsClickRate", "CTR %"),
                   ("averageViewPercentage", "avg % viewed")):
        if b.get(k) is not None and af.get(k) is not None:
            parts.append(f"{lab} {b[k]:.1f} → {af[k]:.1f}")
    return "; ".join(parts) + (" (observational)" if parts else "")


CSS = """
body{font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif;color:#1d1d1b;background:#fff;margin:0}
.wrap{max-width:860px;margin:0 auto;padding:32px 24px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px;border-bottom:2px solid #CFB53B;padding-bottom:4px}
.muted{color:#6b6a65}.eyebrow{color:#8a7414;letter-spacing:.14em;text-transform:uppercase;font-size:11px;font-weight:700}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.kpi{border:1px solid #e5e5e2;border-radius:10px;padding:12px}.kpi b{font-size:22px;display:block}
.vid{display:flex;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid #eee;break-inside:avoid}
.vid img{width:120px;aspect-ratio:16/9;object-fit:cover;border-radius:6px;background:#eee}
.tag{font-size:10px;font-weight:700;letter-spacing:.06em;border:1px solid #ccc;border-radius:99px;padding:1px 6px;color:#555}
.banner{background:#fff4d6;border:1px solid #e8c766;padding:10px 12px;border-radius:8px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:12.5px}td,th{text-align:left;padding:5px 8px 5px 0;border-bottom:1px solid #eee}
a{color:#1c5cab}
@media print{.wrap{padding:0}h2{break-after:avoid}}
"""


def render(data, kind):
    b = data["brand"]
    demo = b.get("kind") == "demo"
    h = [f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(b['display_name'])} — {esc(kind)} report</title>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'><style>{CSS}</style></head><body><div class='wrap'>",
         f"<div class='eyebrow'>Klip Growth OS · {esc(kind.title())} report</div><h1>{esc(b['display_name'])}</h1>",
         f"<p class='muted'>{esc(data['start'])} to {esc(data['end'])} · generated {esc(utcnow()[:16].replace('T', ' '))} UTC</p>"]
    if demo:
        h.append("<div class='banner'><b>Synthetic demo data.</b> Every number in this report was generated to test the "
                 "software. None of it is a real platform measurement.</div>")
    if not data["kpis"] and not data["published"]:
        h.append("<div class='banner'>No platform data yet for this brand. Connect and verify accounts in Manage Accounts; "
                 "this report will fill automatically after the first sync.</div>")
    if data["kpis"]:
        h.append("<h2>Headline numbers (YouTube)</h2><div class='kpis'>")
        for k in data["kpis"]:
            ch = f"<span class='muted'>{fmt(k['change'], 'change')} vs previous period</span>" if k["change"] is not None else "<span class='muted'>no comparable previous period</span>"
            h.append(f"<div class='kpi'><span class='muted'>{esc(k['label'])}</span><b>{fmt(k['value'])}</b>{ch}</div>")
        h.append("</div>")
        h.append("<h2>Daily views</h2>" + svg_line([(r["d"], r["v"]) for r in data["series"]], label="Daily views"))
    if data["top"]:
        h.append("<h2>Strongest content (views per day since publish)</h2>")
        for v in data["top"]:
            uri = thumb_data_uri(b["tenant_id"], v["asset_id"])
            img = f"<img src='{uri}' alt=''>" if uri else "<img alt=''>"
            h.append(f"<div class='vid'>{img}<div><b>{esc(v['title'])}</b><br><span class='muted'>{fmt(v['views_per_day'])} views/day</span> "
                     f"<span class='tag'>{esc(v['format'].replace('_heuristic', '').replace('_', ' '))}</span></div></div>")
    if data["bottom"]:
        h.append("<h2>Needs attention</h2>")
        for v in data["bottom"]:
            h.append(f"<div class='vid'><div><b>{esc(v['title'])}</b><br><span class='muted'>{fmt(v['views_per_day'])} views/day</span></div></div>")
    if data["recs"]:
        h.append("<h2>Recommended actions</h2><table><tr><th>Action</th><th>Basis</th></tr>")
        for r in data["recs"]:
            h.append(f"<tr><td><b>{esc(r['title'])}</b><br><span class='muted'>{esc(r['detail'])}</span></td><td>{esc(r['basis'])}</td></tr>")
        h.append("</table>")
    if data.get("actions"):
        h.append("<h2>Approved actions and outcomes</h2><table><tr><th>Date</th><th>State</th><th>Change</th><th>Outcome</th></tr>")
        for a in data["actions"]:
            h.append(f"<tr><td>{esc(a['at'])}</td><td>{esc(a['state'])}</td><td>{esc(a['title'])}<br><span class='muted'>"
                     f"{esc(a['note'] or '')}</span></td><td>{esc(a['outcome'] or '—')}</td></tr>")
        h.append("</table>")
    if data["trends"]:
        h.append("<h2>Opportunities on the radar</h2><table><tr><th>Topic</th><th>Source</th><th>Score*</th></tr>")
        for t in data["trends"]:
            h.append(f"<tr><td><a href='{esc(t['url'])}'>{esc(t['title'])}</a><br><span class='muted'>{esc(t['uncertainty'])}</span></td>"
                     f"<td>{esc(t['source'])}<br><span class='muted'>{esc((t['published_at'] or '')[:10])}</span></td><td>{esc(t['score'])}</td></tr>")
        h.append("</table><p class='muted'>*Heuristic opportunity score (relevance, freshness, corroboration, novelty). Not search volume or a virality prediction.</p>")
    h.append("<h2>Sources and data freshness</h2><table><tr><th>Platform</th><th>Account</th><th>State</th><th>Data as of</th></tr>")
    for a in data["accounts"]:
        h.append(f"<tr><td>{esc(a['platform'])}</td><td>{esc(a['account_name'])} <span class='muted'>{esc(a['platform_account_id'])}</span></td>"
                 f"<td>{esc(a['state'])}</td><td>{esc(a['data_as_of'] or '—')}</td></tr>")
    if not data["accounts"]:
        h.append("<tr><td colspan='4' class='muted'>No accounts connected.</td></tr>")
    h.append("</table><p class='muted'>Definitions: Views and watch time come from the YouTube Analytics API and lag 2–3 days. "
             "Podcast plays and listeners are never added to YouTube views. Recommendations marked “derived” are calculations "
             "over measured data; “ai” items are drafts for review.</p></div></body></html>")
    return "".join(h)


def period_for(kind, today=None):
    today = today or date.today()
    if kind == "weekly":
        end = today - timedelta(days=today.weekday() + 1)  # last Sunday
        return end - timedelta(days=6), end
    if kind == "monthly":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    return today - timedelta(days=27), today


def generate(conn, tenant_id, kind="manual", today=None, start=None, end=None):
    if start is None:
        start, end = period_for(kind, today)
    data = build_data(conn, tenant_id, start, end)
    ih = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]
    same = conn.execute("SELECT * FROM reports WHERE tenant_id=? AND kind=? AND period_start=? AND input_hash=?",
                        (tenant_id, kind, start.isoformat(), ih)).fetchone()
    if same and Path(same["html_path"]).exists():
        return {"report_id": same["id"], "reused": True}
    rid = new_id("rep_")
    d = REPORTS_DIR / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{rid}.html"
    path.write_text(render(data, kind), encoding="utf-8")
    title = f"{data['brand']['display_name']} · {kind.title()} · {start.isoformat()} – {end.isoformat()}"
    conn.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?)",
                 (rid, tenant_id, kind, start.isoformat(), end.isoformat(), title, str(path), ih, utcnow()))
    return {"report_id": rid, "reused": False, "path": str(path)}


def find_browser():
    cands = [os.environ.get("GROWTH_OS_BROWSER"),
             r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             shutil.which("msedge"), shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome"),
             "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
             "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return next((c for c in cands if c and os.path.exists(c)), None)


def to_pdf(html_path):
    pdf = Path(html_path).with_suffix(".pdf")
    if pdf.exists() and pdf.stat().st_mtime >= Path(html_path).stat().st_mtime:
        return pdf
    exe = find_browser()
    if not exe:
        raise RuntimeError("No Edge/Chrome found for PDF export; open the report and use Print → Save as PDF")
    args = [exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.append("--no-sandbox")  # Chromium refuses to run as root otherwise (Linux servers/containers)
    subprocess.run(args + [Path(html_path).resolve().as_uri()], capture_output=True, timeout=90,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not pdf.exists():
        raise RuntimeError("PDF export failed; use Print → Save as PDF from the report view")
    return pdf


def csv_export(conn, tenant_id, what):
    buf = io.StringIO()
    w = csv.writer(buf)
    if what == "videos":
        cols = ["asset_id", "title", "published_at", "format", "duration_s", "age_days", "views_per_day"] + list(analytics.VIDEO_METRICS)
        w.writerow(cols + ["data_quality"])
        for v in analytics.videos(conn, tenant_id):
            w.writerow([v.get(c) if c in v else v["metrics"].get(c) for c in cols] + [v["metrics"].get("_quality")])
    elif what == "daily":
        w.writerow(["platform", "date", "metric", "value", "source", "fetched_at", "available_through", "data_quality"])
        for r in conn.execute("""SELECT platform, period_start, metric_name, value, source, fetched_at, available_through, data_quality
                                 FROM metrics WHERE tenant_id=? AND grain='day' ORDER BY period_start, metric_name""", (tenant_id,)):
            w.writerow(list(r))
    elif what == "trends":
        w.writerow(["title", "url", "source", "source_type", "published_at", "score", "uncertainty", "matched_keywords", "status"])
        for r in conn.execute("""SELECT title, url, source, source_type, published_at, score, uncertainty, matched_keywords, status
                                 FROM trends WHERE tenant_id=? ORDER BY score DESC""", (tenant_id,)):
            w.writerow(list(r))
    elif what == "recommendations":
        w.writerow(["title", "detail", "basis", "priority", "status", "asset_id", "created_at", "evidence"])
        for r in conn.execute("""SELECT title, detail, basis, priority, status, asset_id, created_at, evidence_json
                                 FROM recommendations WHERE tenant_id=? ORDER BY created_at DESC""", (tenant_id,)):
            w.writerow(list(r))
    else:
        raise ValueError(what)
    return buf.getvalue()

