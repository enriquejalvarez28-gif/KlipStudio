"""One-click growth brief: read every dashboard's data at once, then say what's
happening, where viewers leave, which words show up in what works, and what to
do for the next episode.

Facts are deterministic (same numbers the pages show). The written brief is an
optional cached AI synthesis of those facts only; without AI a rule-based brief
is built from the same facts. Nothing here touches YouTube.
"""

import json
import re
import statistics
from collections import Counter

from growth_os import ai, analytics, thumbs, trends
from growth_os.db import new_id, utcnow

STOP = set(trends.STOP) | set("i you we he she they my your our his her their me us them do does did not no yes what "
                              "why how when who where which can should would will just get got about into out up so "
                              "than then too very really all one two kids kid".split())


def _words(title):
    t = re.sub(r"[^\w\s'-]", " ", (title or "").split("|")[0].lower())
    return {w.strip("'-") for w in t.split() if len(w) > 2 and w not in STOP and not w.isdigit()}


def title_words(vids, top_n=8):
    """Words over-represented in the top quarter (views/day, same format) vs the rest. Correlation only."""
    out = {}
    for fmt in ("short_heuristic", "long_form"):
        g = sorted([v for v in vids if v["format"] == fmt and v["views_per_day"] is not None and (v["age_days"] or 0) >= 7],
                   key=lambda v: -v["views_per_day"])
        if len(g) < 8:
            continue
        q = max(2, len(g) // 4)
        top, rest = g[:q], g[q:]
        ct, cr = Counter(w for v in top for w in _words(v["title"])), Counter(w for v in rest for w in _words(v["title"]))
        rows = []
        for w, n in ct.items():
            if n < 2:
                continue
            lift = (n / len(top)) / max(cr.get(w, 0) / len(rest), 1 / len(rest))
            if lift >= 1.5:
                rows.append({"word": w, "in_top": n, "top_n": len(top), "in_rest": cr.get(w, 0), "rest_n": len(rest),
                             "lift": round(lift, 1)})
        out[fmt] = sorted(rows, key=lambda r: (-r["lift"], -r["in_top"]))[:top_n]
    return out


def _at(curve, x):
    if not curve:
        return None
    p = min(curve, key=lambda p: abs(p["x"] - x))
    return p["v"] if abs(p["x"] - x) <= 0.06 else None


def retention_pattern(conn, tenant_id, vids):
    """Across videos of each format: share still watching at 10/25/50/90% and where big drops cluster."""
    curves = analytics.retention_curves(conn, tenant_id)
    by_id = {v["asset_id"]: v for v in vids}
    out = {}
    for fmt in ("short_heuristic", "long_form"):
        ids = [a for a in curves if a in by_id and by_id[a]["format"] == fmt]
        if len(ids) < 3:
            continue
        marks = {}
        for x in (0.02, 0.1, 0.25, 0.5, 0.9):
            vals = [v for v in (_at(curves[a], x) for a in ids) if v is not None]
            marks[f"{int(x * 100)}%"] = round(100 * statistics.median(vals), 1) if vals else None
        zones, replays = Counter(), []
        bench, _ = analytics.benchmark_curve(curves, ids)
        for a in ids:
            v = by_id[a]
            for e in analytics.retention_events(curves[a], bench, v["duration_s"], v["metrics"].get("views")):
                zone = "opening" if e["x"] < 0.15 else "ending" if e["x"] > 0.8 else "middle"
                if e["kind"] in ("drop", "weak"):
                    zones[zone] += 1
                elif e["kind"] == "replay" and e.get("t") is not None:
                    replays.append({"title": v["title"], "asset_id": a, "t": e["t"], "label": e["label"]})
        out[fmt] = {"videos": len(ids), "still_watching_median_pct": marks,
                    "over_100_means": "viewers rewatching/looping (common on Shorts)", "drop_zones": dict(zones),
                    "replay_moments": replays[:5]}
    return out


def facts(conn, tenant_id, days=28):
    from growth_os import api  # api imports analytics; keep import local
    vids = analytics.videos(conn, tenant_id)
    settled = sorted([v for v in vids if v["views_per_day"] is not None and (v["age_days"] or 0) >= 7],
                     key=lambda v: -v["views_per_day"])
    card = lambda v: {"title": v["title"], "asset_id": v["asset_id"], "format": v["format"],
                      "views_per_day": round(v["views_per_day"], 1), "avg_pct_viewed": v["metrics"].get("averageViewPercentage"),
                      "views": v["metrics"].get("views")}
    kp = [{"label": k["label"], "value": k["value"], "change_pct": round(100 * k["change"], 1) if k.get("change") is not None else None}
          for k in api._kpis(conn, tenant_id, days)]
    terms = [{"term": r[0], "views": int(r[1])} for r in conn.execute(
        """SELECT period_start, SUM(value) FROM metrics WHERE tenant_id=? AND grain='search_term'
           GROUP BY period_start ORDER BY SUM(value) DESC LIMIT 12""", (tenant_id,))]
    tt = analytics.traffic_over_time(conn, tenant_id, days)
    traffic = [{"source": s["source"].replace("_", " ").lower(), "views": s["total"]} for s in tt.get("series", [])]
    aud = analytics.audience(conn, tenant_id)
    mon = analytics.monetization(conn, tenant_id)
    recs = [r[0] for r in conn.execute("""SELECT title FROM recommendations WHERE tenant_id=? AND status='open'
                                          ORDER BY priority, created_at DESC LIMIT 4""", (tenant_id,))]
    trs = [{"title": r[0], "source": r[1], "date": (r[2] or "")[:10]} for r in conn.execute(
        """SELECT title, source, published_at FROM trends WHERE tenant_id=? AND status!='dismissed'
           ORDER BY score DESC LIMIT 4""", (tenant_id,))]
    fp = thumbs.format_performance(conn, tenant_id)
    return {
        "window_days": days,
        "kpis": kp,
        "formats": analytics.formats_compare(conn, tenant_id, days)["types"],
        "top": [card(v) for v in settled[:5]],
        "bottom": [card(v) for v in settled[-3:]] if len(settled) > 6 else [],
        "retention": retention_pattern(conn, tenant_id, vids),
        "title_words": title_words(vids),
        "search_terms": terms,
        "traffic": traffic,
        "audience": {"age": sorted(aud.get("age", []), key=lambda a: -a["pct"])[:3],
                     "gender": aud.get("gender", [])[:2], "country": [c["label"] for c in aud.get("country", [])[:3]],
                     "subscribed": aud.get("subscribed", [])} if aud.get("available") else None,
        "monetization": {"long_form_hours_365d": mon.get("long_form_watch_hours_365d"), "subscribers": mon.get("subscribers"),
                         "days_to_3000h_at_pace": (mon.get("tiers") or [{}])[0].get("days_to_watch_hours_at_pace")}
        if mon.get("available") else None,
        "thumbnail_formats": [{k: r[k] for k in ("label", "video_format", "n", "median_ctr")} for r in fp.get("rows", []) if r.get("n")],
        "open_recommendations": recs,
        "trend_radar": trs,
        "freshness": analytics.freshness(conn, tenant_id).get("youtube", {}).get("through"),
    }


BRIEF_INSTRUCTIONS = (
    "You are the growth producer for a sports interview podcast on YouTube. Using ONLY the numbers in INPUT, write a "
    "short brief for the owner. Plain words, no jargon, no hype. Every claim must point to an INPUT number. Never "
    "predict virality, never invent search volume, never invent guest quotes. 'title_words' are words more common in "
    "the best performers: present them as 'words that show up in what works', not guarantees. If data is thin, say so. "
    "Retention: 'still_watching_median_pct' is the median share still watching at that point of the video; "
    "Values above 100% mean viewers rewatch or loop (common on Shorts), not more viewers. "
    "'drop_zones' counts sharp drops by part of the video; 100 minus the '10%' value is the share gone in the opening. "
    "Use them for opening/ending advice. "
    'Shape: {"headline":"one sentence","whats_happening":["3-5 bullets with numbers"],"whats_working":["2-4"],'
    '"where_viewers_leave":["2-3"],"next_episode":{"angle":"","why":"","opening":"how to open, first 30 s",'
    '"ending":"how to end/CTA","title_words":["4-6 words from INPUT.title_words or search_terms"],'
    '"title_options":["3 titles"],"thumbnail":"which format and why","shorts_to_cut":["2-3 clip ideas"]},'
    '"this_week":["exactly 3 actions"],"watch_next":"one metric and target"}'
)


def _pct(x):
    return f"{x:.1f}%" if isinstance(x, (int, float)) else "—"


def rule_brief(f):
    """Plain, deterministic brief from the same facts (used when AI is off or unavailable)."""
    k = {x["label"]: x for x in f["kpis"]}
    hap = []
    for lab in ("Views", "Watch hours", "Subscribers gained"):
        x = k.get(lab) or next((v for kk, v in k.items() if kk.lower().startswith(lab.lower()[:5])), None)
        if x and x["value"] is not None:
            ch = f" ({'+' if (x['change_pct'] or 0) >= 0 else ''}{x['change_pct']}% vs the 28 days before)" if x["change_pct"] is not None else ""
            hap.append(f"{lab}: {x['value']:,.0f} in the last {f['window_days']} days{ch}.")
    for t in f["formats"]:
        if t.get("views") is not None:
            hap.append(f"{t['label']}: {t['views']:,} views and {t['watch_hours']} watch hours; median {_pct(t.get('median_pct_viewed'))} viewed.")
    work = [f"“{v['title']}” — {v['views_per_day']} views/day" for v in f["top"][:3]]
    leave = []
    for fmt, r in f["retention"].items():
        name = "Shorts" if fmt == "short_heuristic" else "Long-form"
        m = r["still_watching_median_pct"]
        z = max(r["drop_zones"], key=r["drop_zones"].get) if r["drop_zones"] else None
        loop = " (over 100% = rewatching/looping)" if (m.get("10%") or 0) > 100 else ""
        lost = (100 - m["10%"]) if m.get("10%") is not None and m["10%"] < 100 else None
        leave.append(f"{name}: {_pct(m.get('10%'))} at the 10% mark{loop}, {_pct(m.get('25%'))} a quarter in, "
                     f"{_pct(m.get('50%'))} at halfway" + (f"; about {lost:.0f}% of viewers are gone before the 10% mark" if lost else "")
                     + (f"; most sharp drops happen in the {z}." if z else "."))
    words = [w["word"] for fmt in ("long_form", "short_heuristic") for w in f["title_words"].get(fmt, [])][:6] \
        or [t["term"] for t in f["search_terms"][:6]]
    z_all = Counter()
    for r in f["retention"].values():
        z_all.update(r["drop_zones"])
    lf = f["retention"].get("long_form", {}).get("still_watching_median_pct", {})
    early_loss = (100 - lf["10%"]) if lf.get("10%") is not None else 0
    opening = (f"About {early_loss:.0f}% of long-form viewers leave before the 10% mark: open with the guest's strongest "
               "answer as a cold open, then introduce them." if early_loss >= 20 or (z_all and z_all.most_common(1)[0][0] == "opening")
               else "Deliver what the title promises within the first 30 seconds; trim setup.")
    best = f["top"][0] if f["top"] else None
    return {
        "headline": (f"{best['title'].split('|')[0].strip()} is your strongest recent upload; build the next episode around that angle."
                     if best else "Not enough settled videos yet for a full brief."),
        "whats_happening": hap[:5], "whats_working": work, "where_viewers_leave": leave,
        "next_episode": {"angle": f"Follow-up to “{best['title'].split('|')[0].strip()}”" if best else "",
                         "why": "It has the highest views per day among videos at least a week old." if best else "",
                         "opening": opening,
                         "ending": "Ask one specific question for the comments and point to the related full episode or Short.",
                         "title_words": words, "title_options": [], "thumbnail": "", "shorts_to_cut": []},
        "this_week": (f["open_recommendations"][:3] or ["Run the daily review to get this week's actions."]),
        "watch_next": "Median % viewed on the next upload vs the format median above.",
        "_rule_based": True,
    }


def generate(conn, tenant_id, *, force=False, runner=None):
    f = facts(conn, tenant_id)
    try:
        out, meta = ai.ask(conn, tenant_id, "brief", f, BRIEF_INSTRUCTIONS, model="sonnet", runner=runner, force=force)
        brief, source = out, f"AI synthesis of the facts below ({meta['model']}{', cached' if meta.get('cached') else ''})"
    except (ai.AIUnavailable, ValueError, KeyError) as e:
        brief, source = rule_brief(f), f"Rule-based (AI unavailable: {str(e)[:100]})"
    rid = new_id("brf_")
    conn.execute("INSERT INTO growth_briefs VALUES (?,?,?,?,?,?)",
                 (rid, tenant_id, json.dumps(brief), json.dumps(f), source, utcnow()))
    return latest(conn, tenant_id)


def latest(conn, tenant_id):
    r = conn.execute("SELECT * FROM growth_briefs WHERE tenant_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (tenant_id,)).fetchone()
    hist = [dict(x) for x in conn.execute("SELECT id, created_at, source FROM growth_briefs WHERE tenant_id=? "
                                          "ORDER BY created_at DESC, rowid DESC LIMIT 10", (tenant_id,))]
    if not r:
        return {"brief": None, "history": []}
    return {"id": r["id"], "created_at": r["created_at"], "source": r["source"], "brief": json.loads(r["brief_json"]),
            "facts": json.loads(r["facts_json"]), "history": hist,
            "note": "Built from your own analytics at the time shown. Words come from your best-performing titles and real "
                    "search terms; they show what has worked, not a guarantee. Nothing is changed on YouTube."}
