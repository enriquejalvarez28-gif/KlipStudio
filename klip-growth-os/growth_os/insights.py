"""Thumbnail & subscriber growth insights (deterministic; the weekly report and
the Insights page read this). Small samples are labelled, never treated as
patterns. Nothing here assumes the thumbnail caused a result.
"""

import hashlib
import json
import statistics

from growth_os import analytics, prep, thumbs
from growth_os.db import DATA_DIR

RELIABLE_N = 5
DISCOVERY_SOURCES = ("YT_SEARCH", "RELATED_VIDEO", "YT_OTHER_PAGE", "SHORTS", "EXT_URL", "HASHTAGS", "NOTIFICATION",
                     "PLAYLIST", "YT_PLAYLIST_PAGE", "NO_LINK_OTHER")
NOT_IN_API = {
    "new_vs_returning": "New vs returning viewers aren't available from the YouTube API (YouTube Studio → Audience only).",
    "end_screen_ctr": "End-screen click rate isn't in the API; we show views that ARRIVED from end screens instead.",
}


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def _sample(n):
    return "reliable" if n >= RELIABLE_N else f"small sample (n={n}) — not a pattern yet"


def first30(curve, duration_s):
    """Share of viewers still watching at 0:30 (aggregate retention curve)."""
    if not curve or not duration_s or duration_s < 60:
        return None
    x = 30 / duration_s
    pts = sorted(curve, key=lambda p: p["x"])
    for a, b in zip(pts, pts[1:]):
        if a["x"] <= x <= b["x"]:
            t = (x - a["x"]) / max(b["x"] - a["x"], 1e-9)
            return round(100 * (a["v"] + t * (b["v"] - a["v"])), 1)
    return None


def _traffic(conn, tenant_id):
    by = {}
    for a, src, v in conn.execute("SELECT asset_id, period_start, value FROM metrics WHERE tenant_id=? AND grain='traffic_source'",
                                  (tenant_id,)):
        by.setdefault(a, {})[src] = v
    return by


def ctr_by_source(conn, tenant_id):
    rows = conn.execute("""SELECT period_start, metric_name, SUM(value) FROM metrics WHERE tenant_id=? AND grain='day_video_src'
                           GROUP BY period_start, metric_name""", (tenant_id,)).fetchall()
    acc = {}
    for key, m, v in rows:
        src = key.split("|", 1)[-1]
        acc.setdefault(src, {"impressions": 0.0, "clicks": 0.0})["impressions" if m == "videoThumbnailImpressions" else "clicks"] += v
    out = [{"source": s.replace("_", " ").lower(), "impressions": int(a["impressions"]),
            "ctr": round(100 * a["clicks"] / a["impressions"], 2) if a["impressions"] >= 100 else None}
           for s, a in acc.items() if a["impressions"] > 0]
    return {"rows": sorted(out, key=lambda r: -r["impressions"]),
            "note": None if out else "Arrives with YouTube's detailed reach report (first files ~2 days after it's set up)."}


def thumb_people(tenant_id, asset_id):
    """Who appears on the CURRENT thumbnail (face recognition, cached per image). None if unknown."""
    p = DATA_DIR / "thumbs" / tenant_id / f"{asset_id}.jpg"
    if not p.exists():
        return None
    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    cache = DATA_DIR / "cache" / "thumbpeople" / tenant_id / f"{asset_id}.json"
    try:
        c = json.loads(cache.read_text())
        if c.get("hash") == h:
            return c["people"]
    except (OSError, ValueError):
        pass
    try:
        from growth_os import cast
        fx = _faces()
        img = fx.cv2.imread(str(p))
        people = sorted({fx.who(fx.embed(img, f))[0] for f in fx.detect(img) if f[2] >= 40} - {"unsure"})
    except Exception:
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"hash": h, "people": people}))
    return people


_FX = []


def _faces():
    if not _FX:
        from growth_os import cast
        _FX.append(cast._Faces())
    return _FX[0]


def host_vs_guest(conn, tenant_id):
    """Do thumbnails that show a host (Jamar/Enrique) hold viewers and convert subscribers better than guest-only?"""
    groups = {"host_inclusive": [], "guest_only": []}
    for v in analytics.videos(conn, tenant_id):
        if v["format"] != "long_form" or (v["age_days"] or 0) < 7:
            continue
        ppl = thumb_people(tenant_id, v["asset_id"])
        if ppl is None:
            continue
        groups["host_inclusive" if {"jamar", "enrique"} & set(ppl) else "guest_only"].append(v)

    def stats(vs):
        m = lambda k: [x["metrics"].get(k) for x in vs]
        spk = [1000 * (x["metrics"].get("subscribersGained") or 0) / x["metrics"]["views"] for x in vs if x["metrics"].get("views")]
        return {"n": len(vs), "median_pct_viewed": _med(m("averageViewPercentage")),
                "median_avg_view_s": _med(m("averageViewDuration")), "median_subs_per_1k": _med(spk),
                "median_ctr": _med([x["metrics"].get("videoThumbnailImpressionsClickRate") for x in vs
                                    if (x["metrics"].get("videoThumbnailImpressions") or 0) >= thumbs.MIN_IMPRESSIONS]),
                "sample": _sample(len(vs))}
    a, b = stats(groups["host_inclusive"]), stats(groups["guest_only"])
    if min(a["n"], b["n"]) < RELIABLE_N:
        verdict = (f"Not enough yet: {a['n']} host-inclusive vs {b['n']} guest-only long-form thumbnails "
                   f"(need {RELIABLE_N}+ each). Keep mixing both and re-check.")
    else:
        better = [k for k, lab in (("median_pct_viewed", "% viewed"), ("median_subs_per_1k", "subs per 1,000 views"))
                  if a[k] is not None and b[k] is not None and a[k] > b[k] * 1.1]
        verdict = (f"Host-inclusive thumbnails lead on {', '.join(better)}." if better else
                   "No clear difference between host-inclusive and guest-only thumbnails yet.") + \
            " Observational: topic and guest also differ between these videos."
    return {"host_inclusive": a, "guest_only": b, "verdict": verdict,
            "method": "Faces on each current thumbnail are recognised locally (hosts vs guest). Long-form, 7+ days old."}


def age_matched(conn, tenant_id):
    """First-7-day views/watch hours per long-form episode (equal age windows) + format medians."""
    co = prep.cohorts(conn, tenant_id, "long_form", limit=40)["items"]
    rows = [{"title": i["title"], "asset_id": i["asset_id"], "published_at": i["published_at"],
             "d7_views": (i["points"].get("7") or {}).get("views"), "d7_hours": (i["points"].get("7") or {}).get("watch_hours")}
            for i in co if i["points"].get("7")]
    med = _med([r["d7_views"] for r in rows])
    for r in rows:
        r["vs_median"] = round(r["d7_views"] / med, 2) if med else None
    return {"rows": sorted(rows, key=lambda r: -(r["d7_views"] or 0)), "median_d7_views": med, "sample": _sample(len(rows))}


def video_table(conn, tenant_id):
    vids = [v for v in analytics.videos(conn, tenant_id) if v["format"] == "long_form"]
    curves = analytics.retention_curves(conn, tenant_id)
    tr = _traffic(conn, tenant_id)
    out = []
    for v in vids:
        m, t = v["metrics"], tr.get(v["asset_id"], {})
        views = m.get("views") or 0
        out.append({"asset_id": v["asset_id"], "title": v["title"], "age_days": v["age_days"], "views": views,
                    "ctr": m.get("videoThumbnailImpressionsClickRate") if (m.get("videoThumbnailImpressions") or 0) >= thumbs.MIN_IMPRESSIONS else None,
                    "impressions": m.get("videoThumbnailImpressions"),
                    "pct_viewed": round(m["averageViewPercentage"], 1) if m.get("averageViewPercentage") is not None else None,
                    "avg_view_s": m.get("averageViewDuration"), "first30": first30(curves.get(v["asset_id"]), v["duration_s"]),
                    "subs_per_1k": round(1000 * (m.get("subscribersGained") or 0) / views, 2) if views else None,
                    "from_shorts": int(t.get("SHORTS", 0)), "from_end_screens": int(t.get("END_SCREEN", 0)),
                    "discovery_share": round(100 * sum(t.get(s, 0) for s in DISCOVERY_SOURCES) / sum(t.values()), 1) if t else None})
    return out


def _topic_rows(conn, tenant_id, table):
    out = []
    for kw, _ in analytics.topic_keywords(conn, tenant_id):
        vs = [r for r in table if kw.lower() in (r["title"] or "").lower()]
        if not vs:
            continue
        views = sum(r["views"] for r in vs)
        out.append({"topic": kw, "videos": len(vs), "views": views,
                    "discovery_share": _med([r["discovery_share"] for r in vs]),
                    "subs_per_1k": _med([r["subs_per_1k"] for r in vs]), "sample": _sample(len(vs))})
    return out


def weekly(conn, tenant_id):
    table = video_table(conn, tenant_id)
    peer_ctr = _med([r["ctr"] for r in table])
    peer_pct = _med([r["pct_viewed"] for r in table])
    peer_30 = _med([r["first30"] for r in table])
    retest = [dict(r, why=f"CTR {r['ctr']}% vs {peer_ctr}% typical, but viewers who click stay ({r['pct_viewed']}% viewed vs "
                          f"{peer_pct}%): packaging may be holding it back.")
              for r in table if (r["age_days"] or 0) >= 14 and r["ctr"] is not None and peer_ctr and r["ctr"] < peer_ctr
              and r["pct_viewed"] and peer_pct and r["pct_viewed"] >= peer_pct and (r["impressions"] or 0) >= 500]
    hooks = sorted([r for r in table if r["first30"] is not None and peer_30 and r["first30"] < peer_30 * 0.9],
                   key=lambda r: r["first30"])[:5]
    topics = _topic_rows(conn, tenant_id, table)
    hv = host_vs_guest(conn, tenant_id)
    fp = thumbs.format_performance(conn, tenant_id)["rows"]
    pending = [json.loads(r[0]) for r in conn.execute(
        "SELECT picks_json FROM thumb_concepts WHERE tenant_id=? AND status='proposed' ORDER BY created_at DESC LIMIT 5", (tenant_id,))]
    experiments = [f"Retest the thumbnail on “{r['title']}” with YouTube Test & Compare (3 concepts)." for r in retest[:3]]
    experiments += [f"Rework the first 30 seconds pattern seen in “{r['title']}” ({r['first30']}% still watching at 0:30 vs "
                    f"{peer_30}%): open with the strongest answer." for r in hooks[:2]]
    if "Not enough" in hv["verdict"]:
        experiments.append("Alternate host-inclusive and guest-only thumbnails on the next episodes so the comparison becomes reliable.")
    if pending:
        experiments.append(f"{len(pending)} new episode(s) have 3 recommended thumbnail concepts ready for Test & Compare.")
    return {
        "retest": retest[:6],
        "styles": {"formats": [r for r in fp if r["video_format"] == "long_form"], "host_vs_guest": hv},
        "topics_new_viewers": sorted(topics, key=lambda r: -(r["discovery_share"] or 0))[:6],
        "topics_subscribers": sorted(topics, key=lambda r: -(r["subs_per_1k"] or 0))[:6],
        "hooks": hooks, "first30_median": peer_30,
        "experiments": experiments[:6],
        "age_matched": age_matched(conn, tenant_id),
        "ctr_by_source": ctr_by_source(conn, tenant_id),
        "not_in_api": NOT_IN_API,
        "notes": ["'New viewers' uses views from search, suggested, browse, Shorts and outside links as a proxy "
                  "(the API doesn't split new vs returning).",
                  f"Groups under {RELIABLE_N} videos are labelled small samples.",
                  "Before/after and group comparisons are observational: topic, guest and timing also change."],
    }


def page(conn, tenant_id):
    return {"weekly": weekly(conn, tenant_id), "videos": video_table(conn, tenant_id)}
