"""Deterministic analytics. No model calls in this module.

Everything returned here is either MEASURED (straight from a platform row)
or DERIVED (arithmetic over measured rows). AI interpretation lives in ai.py
and is labelled separately everywhere it is shown.
"""

import hashlib
import json
import math
import re
import statistics
from datetime import date, datetime, timedelta, timezone

from growth_os.db import new_id, utcnow

# Daily channel metrics that are additive over days. Others (averages) are
# averaged, never summed; views vs plays vs listeners are never mixed.
ADDITIVE = {"views", "estimatedMinutesWatched", "subscribersGained", "subscribersLost", "plays", "listeners_new"}
LABELS = {
    "views": "Views", "estimatedMinutesWatched": "Watch time (min)", "averageViewDuration": "Avg view duration (s)",
    "subscribersGained": "Subscribers gained", "subscribersLost": "Subscribers lost",
    "videoThumbnailImpressions": "Impressions", "videoThumbnailImpressionsClickRate": "Impressions CTR",
    "averageViewPercentage": "Avg % viewed",
}


def _today(conn, tenant_id):
    row = conn.execute(
        "SELECT MAX(period_start) FROM metrics WHERE tenant_id=? AND grain='day'", (tenant_id,)).fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


def series(conn, tenant_id, metric, days=90, platform="youtube", asset_id=None):
    end = _today(conn, tenant_id)
    if not end:
        return []
    start = (end - timedelta(days=days - 1)).isoformat()
    sql = """SELECT period_start d, value v, data_quality q FROM metrics WHERE tenant_id=? AND platform=? AND grain='day'
             AND metric_name=? AND period_start>=?"""
    args = [tenant_id, platform, metric, start]
    if asset_id:
        sql += " AND asset_id=?"
        args.append(asset_id)
    else:
        sql += " AND asset_id=platform_account_id"
    return [dict(r) for r in conn.execute(sql + " ORDER BY d", args)]


def kpi(conn, tenant_id, metric, days, platform="youtube"):
    """Window value vs the previous equal window. None when not enough data."""
    s = series(conn, tenant_id, metric, days * 2, platform)
    if not s:
        return None
    end = date.fromisoformat(s[-1]["d"])
    cut = (end - timedelta(days=days - 1)).isoformat()
    cur = [r["v"] for r in s if r["d"] >= cut]
    prev = [r["v"] for r in s if r["d"] < cut]
    agg = sum if metric in ADDITIVE else (lambda xs: statistics.fmean(xs) if xs else None)
    c = agg(cur) if cur else None
    p = agg(prev) if len(prev) >= days * 0.8 else None  # don't compare against a partial window
    change = ((c - p) / p) if (c is not None and p) else None
    return {"metric": metric, "label": LABELS.get(metric, metric), "days": days, "value": c, "previous": p,
            "change": change, "through": s[-1]["d"], "quality": s[-1]["q"]}


def freshness(conn, tenant_id):
    rows = conn.execute(
        """SELECT platform, MAX(fetched_at) fetched, MAX(available_through) through, MAX(data_quality) q,
           GROUP_CONCAT(DISTINCT source) sources FROM metrics WHERE tenant_id=? GROUP BY platform""",
        (tenant_id,)).fetchall()
    return {r["platform"]: dict(r) for r in rows}


# ── Videos & peers ────────────────────────────────────────────────────

VIDEO_METRICS = ("views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage",
                 "videoThumbnailImpressions", "videoThumbnailImpressionsClickRate", "likes", "comments",
                 "subscribersGained")


def duration_bucket(s):
    if s is None:
        return "unknown"
    return "short" if s <= 180 else "mid" if s <= 1200 else "long" if s <= 3600 else "xlong"


def age_days(published_at, ref=None):
    if not published_at:
        return None
    ref = ref or datetime.now(timezone.utc)
    p = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    return max(0, (ref - p).days)


def videos(conn, tenant_id, platform="youtube"):
    assets = conn.execute("SELECT * FROM assets WHERE tenant_id=? AND platform=? ORDER BY published_at DESC",
                          (tenant_id, platform)).fetchall()
    m = {}
    for r in conn.execute(
            f"""SELECT asset_id, metric_name, value, data_quality, available_through FROM metrics
                WHERE tenant_id=? AND platform=? AND grain='video_lifetime'
                AND metric_name IN ({",".join("?" * len(VIDEO_METRICS))})""",
            (tenant_id, platform, *VIDEO_METRICS)):
        m.setdefault(r["asset_id"], {})[r["metric_name"]] = r["value"]
        m[r["asset_id"]]["_quality"] = r["data_quality"]
        m[r["asset_id"]]["_through"] = r["available_through"]
    out = []
    for a in assets:
        d = dict(a)
        d["metrics"] = m.get(a["asset_id"], {})
        d["age_days"] = age_days(a["published_at"])
        d["duration_bucket"] = duration_bucket(a["duration_s"])
        v = d["metrics"].get("views")
        d["views_per_day"] = (v / max(d["age_days"], 1)) if v is not None and d["age_days"] is not None else None
        out.append(d)
    return out


def percentile_rank(values, x):
    vals = sorted(v for v in values if v is not None)
    if not vals or x is None:
        return None
    below = sum(1 for v in vals if v < x)
    equal = sum(1 for v in vals if v == x)
    return round(100 * (below + 0.5 * equal) / len(vals))


def peers(all_videos, v, min_n=3):
    """Matched comparison set: same format and duration bucket, excluding
    videos younger than 7 days (metrics still settling). Falls back to same
    format only, and says so."""
    def ok(o):
        return o["asset_id"] != v["asset_id"] and (o["age_days"] or 0) >= 7
    strict = [o for o in all_videos if ok(o) and o["format"] == v["format"]
              and o["duration_bucket"] == v["duration_bucket"]]
    if len(strict) >= min_n:
        return strict, f"same format ({v['format']}) and length ({v['duration_bucket']}), ≥7 days old"
    loose = [o for o in all_videos if ok(o) and o["format"] == v["format"]]
    if len(loose) >= min_n:
        return loose, f"same format ({v['format']}), ≥7 days old — too few same-length videos"
    return [], "fewer than 3 comparable videos — no peer comparison"


def peer_stats(all_videos, v):
    group, basis = peers(all_videos, v)
    out = {"basis": basis, "n": len(group), "metrics": {}}
    if not group:
        return out
    for key, getter in (
        ("ctr", lambda o: o["metrics"].get("videoThumbnailImpressionsClickRate")),
        ("avg_pct_viewed", lambda o: o["metrics"].get("averageViewPercentage")),
        ("views_per_day", lambda o: o["views_per_day"]),
        ("impressions", lambda o: o["metrics"].get("videoThumbnailImpressions")),
    ):
        vals = [getter(o) for o in group if getter(o) is not None]
        mine = getter(v)
        if len(vals) >= 3:
            out["metrics"][key] = {"value": mine, "peer_median": statistics.median(vals),
                                   "percentile": percentile_rank(vals + ([mine] if mine is not None else []), mine)}
    return out


# ── Thumbnail features (Pillow, local) ────────────────────────────────

def thumbnail_features(path):
    """Measurable image properties. Faces and on-image text need models we
    don't ship (no OCR / face detector installed) and are reported as unavailable."""
    from PIL import Image, ImageFilter, ImageStat

    im = Image.open(path).convert("RGB")
    im.thumbnail((320, 180))
    gray = im.convert("L")
    st = ImageStat.Stat(gray)
    lum = st.mean[0] / 255
    contrast = st.stddev[0] / 255
    px = list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())
    rg = [abs(r - g) for r, g, b in px]
    yb = [abs(0.5 * (r + g) - b) for r, g, b in px]
    colorfulness = (math.hypot(statistics.pstdev(rg), statistics.pstdev(yb))
                    + 0.3 * math.hypot(statistics.fmean(rg), statistics.fmean(yb))) / 255
    edges = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0] / 255
    sat = ImageStat.Stat(im.convert("HSV")).mean[1] / 255
    q = im.quantize(colors=4, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:12]
    counts = sorted(q.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)
    dominant = [{"hex": "#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]), "share": round(c / total, 3)}
                for c, i in counts]
    # Center-weighted contrast: is the middle third distinct from the edges?
    w, h = gray.size
    center = ImageStat.Stat(gray.crop((w // 3, h // 4, 2 * w // 3, 3 * h // 4))).mean[0]
    focal = abs(center - st.mean[0]) / 255
    return {
        "luminance": round(lum, 3), "contrast": round(contrast, 3), "colorfulness": round(colorfulness, 3),
        "saturation": round(sat, 3), "edge_density": round(edges, 3), "focal_contrast": round(focal, 3),
        "dominant_colors": dominant,
        "unavailable": ["faces (no face detector installed)", "on-image headline text (no OCR installed)"],
    }


def file_hash(path):
    from pathlib import Path

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


# ── Title checks ──────────────────────────────────────────────────────

def topic_keywords(conn, tenant_id):
    return [(r["keyword"], r["weight"]) for r in
            conn.execute("SELECT keyword, weight FROM tenant_topics WHERE tenant_id=? ORDER BY weight DESC", (tenant_id,))]


def title_checks(title, keywords, search_terms=()):
    t = title or ""
    low = t.lower()
    words = re.findall(r"[A-Za-z0-9']+", t)
    caps = [w for w in words if len(w) > 2 and w.isupper()]
    hits = [k for k, _ in keywords if k.lower() in low]
    first40 = low[:40]
    front = [k for k in hits if k.lower() in first40]
    st = [s for s in search_terms if s]
    covered = [s for s in st if all(w in low for w in s.lower().split())]
    checks = [
        {"id": "length", "label": "Length", "value": len(t),
         "status": "ok" if 30 <= len(t) <= 60 else "warn",
         "note": "Longer titles may be cut off in some views (roughly past 60 characters)." if len(t) > 60
         else "Very short. Room to add who or what the episode is about." if len(t) < 30 else "In a typical range."},
        {"id": "topic", "label": "Brand topic keywords", "value": hits,
         "status": "ok" if hits else "warn",
         "note": "No configured topic keyword appears in the title." if not hits else f"Mentions: {', '.join(hits)}"},
        {"id": "front", "label": "Keyword in first 40 chars", "value": bool(front),
         "status": "ok" if front or not hits else "warn",
         "note": "Topic appears early." if front else "Topic keyword appears late or not at all."},
        {"id": "episode_prefix", "label": "Episode-number prefix", "value": bool(re.match(r"^\s*(ep\.?|episode)\s*\d+", low)),
         "status": "warn" if re.match(r"^\s*(ep\.?|episode)\s*\d+", low) else "ok",
         "note": "Starts with an episode number, which uses the most visible characters." if re.match(r"^\s*(ep\.?|episode)\s*\d+", low) else "—"},
        {"id": "caps", "label": "ALL-CAPS words", "value": len(caps), "status": "warn" if len(caps) > 2 else "ok",
         "note": f"{len(caps)} all-caps words." if caps else "None."},
        {"id": "question", "label": "Question form", "value": t.strip().endswith("?"), "status": "info", "note": ""},
        {"id": "number", "label": "Contains a number", "value": bool(re.search(r"\d", t)), "status": "info", "note": ""},
    ]
    if st:
        checks.append({"id": "search", "label": "Top search terms covered", "value": f"{len(covered)}/{len(st)}",
                       "status": "ok" if covered else "warn", "note": ", ".join(covered) or "None of the top search terms appear."})
    else:
        checks.append({"id": "search", "label": "Top search terms covered", "value": None, "status": "na",
                       "note": "No YouTube search-term data for this video yet."})
    return checks


# ── Daily review / opportunity checks (write recommendations) ─────────

def _fingerprint(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def add_recommendation(conn, tenant_id, *, kind, basis, title, detail, evidence, asset_id=None, priority=2, key=None):
    fp = _fingerprint(kind, asset_id, key or title)
    cur = conn.execute(
        """INSERT OR IGNORE INTO recommendations (id, tenant_id, asset_id, kind, priority, basis, title, detail,
           evidence_json, fingerprint, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (new_id("rec_"), tenant_id, asset_id, kind, priority, basis, title, detail, json.dumps(evidence), fp, utcnow()))
    return cur.rowcount


def packaging_check(conn, tenant_id, min_impressions=1000):
    """Flag videos whose CTR or retention sits in the bottom quartile of
    matched peers, with enough impressions to mean something."""
    vids = videos(conn, tenant_id)
    added = 0
    for v in vids:
        ps = peer_stats(vids, v)
        ctr = ps["metrics"].get("ctr")
        ret = ps["metrics"].get("avg_pct_viewed")
        imp = v["metrics"].get("videoThumbnailImpressions") or 0
        if (v["age_days"] or 0) < 7 or imp < min_impressions:
            continue
        ev = [{"metric": "Impressions", "value": imp, "basis": "measured"}]
        if ctr:
            ev.append({"metric": "Impressions CTR", "value": ctr["value"], "peer_median": ctr["peer_median"],
                       "percentile": ctr["percentile"], "basis": "derived", "peers": ps["basis"], "n": ps["n"]})
        if ret:
            ev.append({"metric": "Avg % viewed", "value": ret["value"], "peer_median": ret["peer_median"],
                       "percentile": ret["percentile"], "basis": "derived"})
        low_ctr = ctr and ctr["percentile"] is not None and ctr["percentile"] <= 25
        ok_ret = ret and ret["percentile"] is not None and ret["percentile"] >= 50
        low_ret = ret and ret["percentile"] is not None and ret["percentile"] <= 25
        if low_ctr and ok_ret:
            added += add_recommendation(
                conn, tenant_id, kind="thumbnail_title_review", basis="derived", asset_id=v["asset_id"], priority=1,
                title=f"Review packaging: “{v['title']}”",
                detail="People who click watch well, but fewer people click than on comparable videos. "
                       "The thumbnail or title is the likelier lever. This is a correlation from observed data, not a test result.",
                evidence=ev)
        elif low_ctr:
            added += add_recommendation(
                conn, tenant_id, kind="thumbnail_title_review", basis="derived", asset_id=v["asset_id"], priority=2,
                title=f"Low click-through vs peers: “{v['title']}”",
                detail="CTR is in the bottom quartile of comparable videos. Check the thumbnail and title against the topic.",
                evidence=ev)
        elif low_ret and not low_ctr and ctr:
            added += add_recommendation(
                conn, tenant_id, kind="retention_review", basis="derived", asset_id=v["asset_id"], priority=2,
                title=f"Strong click, weak hold: “{v['title']}”",
                detail="Click-through is normal for its peers but average % viewed is in the bottom quartile. "
                       "Check that the opening delivers what the thumbnail/title promise.",
                evidence=ev)
    return added


def daily_review(conn, tenant_id):
    """Robust anomaly check on daily views: latest day vs trailing 28-day
    median, scaled by MAD. Writes at most one recommendation per day."""
    s = series(conn, tenant_id, "views", 35)
    if len(s) < 15:
        return {"checked": False, "reason": "fewer than 15 days of daily views"}
    hist = [r["v"] for r in s[:-1]][-28:]
    med = statistics.median(hist)
    mad = statistics.median([abs(x - med) for x in hist]) or 1
    last = s[-1]
    z = (last["v"] - med) / (1.4826 * mad)
    out = {"checked": True, "day": last["d"], "views": last["v"], "median": med, "robust_z": round(z, 2)}
    if abs(z) >= 3:
        direction = "above" if z > 0 else "below"
        add_recommendation(
            conn, tenant_id, kind="anomaly", basis="derived", priority=1 if z < 0 else 2, key=last["d"],
            title=f"Views on {last['d']} were unusually {direction} normal",
            detail=f"{int(last['v']):,} views vs a 28-day median of {int(med):,}. Check traffic sources for that day.",
            evidence=[{"metric": "Daily views", "value": last["v"], "baseline_median": med, "robust_z": round(z, 2),
                       "basis": "derived"}])
    return out


# ── Monetization (YouTube Partner Program) ─────────────────────────────
# Thresholds from YouTube Help (checked 2026-10-14):
#   https://support.google.com/youtube/answer/72851 (full YPP)
#   https://support.google.com/youtube/answer/13429240 (expanded YPP, fan funding + Shopping)
YPP_TIERS = [
    {"id": "expanded", "name": "Fan funding + Shopping (expanded YPP)",
     "unlocks": "Channel memberships, Super Chat/Stickers, Super Thanks, Shopping",
     "subs": 500, "uploads_90d": 3, "watch_hours_365d": 3000, "shorts_views_90d": 3_000_000},
    {"id": "full", "name": "Ad revenue sharing (full YPP)",
     "unlocks": "Ad revenue on long-form and Shorts, YouTube Premium revenue, plus everything above",
     "subs": 1000, "uploads_90d": None, "watch_hours_365d": 4000, "shorts_views_90d": 10_000_000},
]
LONG_FORM_TYPES = ("VIDEO_ON_DEMAND", "LIVE_STREAM")


def _ctype_sum(conn, tenant_id, metric, types, start, end):
    q = ",".join("?" * len(types))
    r = conn.execute(
        f"""SELECT COALESCE(SUM(value),0), COUNT(DISTINCT period_start) FROM metrics WHERE tenant_id=? AND platform='youtube'
            AND grain='day_ctype' AND metric_name=? AND asset_id IN ({q}) AND period_start BETWEEN ? AND ?""",
        (tenant_id, metric, *[f"ctype:{t}" for t in types], start, end)).fetchone()
    return float(r[0]), int(r[1])


def monetization(conn, tenant_id):
    end_row = conn.execute("SELECT MAX(period_start) FROM metrics WHERE tenant_id=? AND grain='day_ctype'",
                           (tenant_id,)).fetchone()[0]
    subs_row = conn.execute(
        """SELECT value, period_start FROM metrics WHERE tenant_id=? AND platform='youtube' AND metric_name='subscriberCount'
           AND grain='lifetime_snapshot' ORDER BY period_start DESC LIMIT 1""", (tenant_id,)).fetchone()
    subs = subs_row[0] if subs_row else None
    # Public uploads in the last 90 days: latest known privacy per video (unknown counts as public, flagged).
    priv = {}
    for r in conn.execute("SELECT asset_id, value FROM asset_history WHERE tenant_id=? AND field='privacy' ORDER BY observed_at",
                          (tenant_id,)):
        priv[r[0]] = r[1]
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    recent = [r for r in conn.execute("SELECT asset_id, published_at FROM assets WHERE tenant_id=? AND platform='youtube' "
                                      "AND published_at>=?", (tenant_id, cutoff))]
    uploads_90 = sum(1 for r in recent if priv.get(r[0], "public") == "public")
    out = {"available": bool(end_row), "as_of": end_row, "subscribers": subs,
           "subscribers_as_of": subs_row[1] if subs_row else None, "uploads_90d": uploads_90,
           "tiers": [], "sources": ["https://support.google.com/youtube/answer/72851",
                                    "https://support.google.com/youtube/answer/13429240"],
           "notes": ["Watch hours and Shorts views here come from YouTube Analytics. YouTube's official count only includes "
                     "public long-form videos and public Shorts in the Shorts feed, so YouTube Studio → Earn is the final word.",
                     "Shorts watch hours never count toward the watch-hour goal.",
                     "Also required: 2-Step Verification on the Google account, no active Community Guidelines strikes, "
                     "an AdSense account linked to the channel, and a channel based in an eligible country."]}
    if not end_row:
        return out
    end = date.fromisoformat(end_row)
    s365, s90, s28 = ((end - timedelta(days=d - 1)).isoformat() for d in (365, 90, 28))
    lf_min, lf_days = _ctype_sum(conn, tenant_id, "estimatedMinutesWatched", LONG_FORM_TYPES, s365, end_row)
    sh_views, sh_days = _ctype_sum(conn, tenant_id, "views", ("SHORTS",), s90, end_row)
    lf28, _ = _ctype_sum(conn, tenant_id, "estimatedMinutesWatched", LONG_FORM_TYPES, s28, end_row)
    sh28, _ = _ctype_sum(conn, tenant_id, "views", ("SHORTS",), s28, end_row)
    sh_min90, _ = _ctype_sum(conn, tenant_id, "estimatedMinutesWatched", ("SHORTS",), s90, end_row)
    watch_h = lf_min / 60
    out.update(long_form_watch_hours_365d=round(watch_h, 1), shorts_views_90d=int(sh_views),
               shorts_watch_hours_90d=round(sh_min90 / 60, 1),
               pace={"long_form_hours_per_day": round(lf28 / 60 / 28, 2), "shorts_views_per_day": round(sh28 / 28)},
               window_days={"watch_hours": lf_days, "shorts_views": sh_days})

    def eta(gap, per_day):
        return None if gap <= 0 else (round(gap / per_day) if per_day > 0 else None)

    for t in YPP_TIERS:
        subs_ok = subs is not None and subs >= t["subs"]
        up_ok = t["uploads_90d"] is None or uploads_90 >= t["uploads_90d"]
        wh_gap, sv_gap = t["watch_hours_365d"] - watch_h, t["shorts_views_90d"] - sh_views
        path = "watch_hours" if watch_h / t["watch_hours_365d"] >= sh_views / t["shorts_views_90d"] else "shorts_views"
        out["tiers"].append({
            **t, "subs_ok": subs_ok, "uploads_ok": up_ok,
            "subs_pct": round(min(100, 100 * (subs or 0) / t["subs"]), 1),
            "watch_hours_pct": round(min(100, 100 * watch_h / t["watch_hours_365d"]), 1),
            "shorts_views_pct": round(min(100, 100 * sh_views / t["shorts_views_90d"]), 1),
            "watch_hours_gap": round(max(0, wh_gap), 1), "shorts_views_gap": int(max(0, sv_gap)),
            "subs_gap": int(max(0, t["subs"] - (subs or 0))),
            "closest_path": path,
            "days_to_watch_hours_at_pace": eta(wh_gap, lf28 / 60 / 28),
            "days_to_shorts_views_at_pace": eta(sv_gap, sh28 / 28),
            "eligible_by_numbers": subs_ok and up_ok and (wh_gap <= 0 or sv_gap <= 0),
        })
    return out


def rewatch_summary(curve, avg_pct_viewed=None, fmt=None):
    """From an aggregate retention curve [{x, v}] (v = audienceWatchRatio).

    v > 1 at a point means that moment was watched more times than there were
    views: people scrubbed back or replayed it. For Shorts, an average % viewed
    over 100% means the Short looped. Neither identifies individual viewers.
    """
    out = {"has_curve": bool(curve)}
    if fmt == "short_heuristic" and avg_pct_viewed is not None:
        out["loops_pct"] = round(max(0.0, avg_pct_viewed - 100), 1)
    if not curve:
        return out
    peak = max(curve, key=lambda p: p["v"])
    rewatched = [p for p in curve if p["v"] > 1.0]
    drops = [(curve[i - 1]["x"], curve[i - 1]["v"] - curve[i]["v"]) for i in range(1, len(curve))]
    big = max(drops, key=lambda d: d[1]) if drops else None
    early = next((p["v"] for p in curve if p["x"] >= 0.1), None)
    half = next((p["v"] for p in curve if p["x"] >= 0.5), None)
    out.update(peak_ratio=round(peak["v"], 2), peak_at_pct=round(peak["x"] * 100),
               rewatched_share_pct=round(100 * len(rewatched) / len(curve)),
               biggest_drop_at_pct=round(big[0] * 100) if big else None,
               biggest_drop_pts=round(big[1] * 100, 1) if big else None,
               still_watching_at_10pct=round(early * 100, 1) if early is not None else None,
               still_watching_at_50pct=round(half * 100, 1) if half is not None else None)
    return out


AGE_LABELS = {"age13-17": "13-17", "age18-24": "18-24", "age25-34": "25-34", "age35-44": "35-44",
              "age45-54": "45-54", "age55-64": "55-64", "age65-": "65+"}


def audience(conn, tenant_id):
    """Last-90-day audience breakdowns stored by the sync (aggregates only)."""
    rows = conn.execute(
        """SELECT asset_id, period_start, metric_name, value, fetched_at FROM metrics
           WHERE tenant_id=? AND platform='youtube' AND grain='audience_90d'""", (tenant_id,)).fetchall()
    by = {}
    fetched = None
    for a, label, m, v, f in rows:
        by.setdefault(a[4:], {}).setdefault(label, {})[m] = v
        fetched = max(fetched or f, f)
    out = {"available": bool(rows), "window_days": 90, "fetched_at": fetched,
           "note": "Last 90 days. Shares are of views (age/gender: of signed-in viewers). "
                   "YouTube hides groups that are too small, so parts may not add to 100%."}
    ages, genders = {}, {}
    for label, ms in by.get("age_gender", {}).items():
        age, gender = (label.split("|") + [""])[:2]
        pctv = ms.get("viewerPercentage", 0)
        ages[AGE_LABELS.get(age, age)] = ages.get(AGE_LABELS.get(age, age), 0) + pctv
        genders[gender.lower()] = genders.get(gender.lower(), 0) + pctv
    out["age"] = [{"label": k, "pct": round(v, 1)} for k, v in sorted(ages.items())]
    out["gender"] = [{"label": k.replace("user_specified", "other"), "pct": round(v, 1)}
                     for k, v in sorted(genders.items(), key=lambda x: -x[1])]

    def table(key):
        items = by.get(key, {})
        total = sum(ms.get("views", 0) for ms in items.values()) or 1
        res = [{"label": label, "views": ms.get("views"), "share_pct": round(100 * (ms.get("views") or 0) / total, 1),
                "watch_hours": round((ms.get("estimatedMinutesWatched") or 0) / 60, 1),
                "avg_view_s": ms.get("averageViewDuration")} for label, ms in items.items()]
        return sorted(res, key=lambda r: -(r["views"] or 0))

    out["country"] = table("country")[:15]
    out["device"] = table("device")
    out["subscribed"] = table("subscribed")
    return out


# ── Retention explorer ─────────────────────────────────────────────────

def retention_curves(conn, tenant_id):
    """{asset_id: [{x, v, rel}]} from stored aggregate retention buckets."""
    out = {}
    for a, k, m, v in conn.execute(
            """SELECT asset_id, period_start, metric_name, value FROM metrics WHERE tenant_id=? AND platform='youtube'
               AND grain='retention_bucket' ORDER BY asset_id, period_start""", (tenant_id,)):
        x = float(k[6:])
        pts = out.setdefault(a, {})
        pts.setdefault(x, {"x": x})["v" if m == "audienceWatchRatio" else "rel"] = v
    return {a: [p for _, p in sorted(pts.items()) if "v" in p] for a, pts in out.items()}


def benchmark_curve(curves, asset_ids):
    """Bucket-wise median of other videos' curves (same cohort)."""
    peers = [curves[a] for a in asset_ids if a in curves]
    if len(peers) < 2:
        return [], len(peers)
    by = {}
    for c in peers:
        for p in c:
            by.setdefault(round(p["x"], 2), []).append(p["v"])
    return [{"x": x, "v": round(statistics.median(vs), 4)} for x, vs in sorted(by.items()) if len(vs) >= 2], len(peers)


def retention_events(curve, bench=None, duration_s=None, views=None, max_each=3):
    """Deterministic markers on an aggregate retention curve.

    Kinds: drop (steepest falls), replay (watch ratio rises: people scrubbed
    back or rewatched), weak (sustained stretch below typical for YouTube,
    relativeRetentionPerformance < 0.35), strong (> 0.65). Confidence follows
    the video's view count. Aggregate data: never per-viewer.
    """
    if not curve or len(curve) < 3:
        return []
    conf = "low" if (views or 0) < 300 else "medium" if (views or 0) < 3000 else "high"
    bmap = {round(p["x"], 2): p["v"] for p in (bench or [])}
    ts = (lambda x: round(x * duration_s)) if duration_s else (lambda x: None)

    def ev(kind, p, value, delta, label):
        b = bmap.get(round(p["x"], 2))
        return {"kind": kind, "x": p["x"], "t": ts(p["x"]), "value": round(value, 3), "delta": round(delta, 3),
                "baseline": round(b, 3) if b is not None else None, "confidence": conf, "label": label}

    out = []
    steps = [(curve[i - 1], curve[i], curve[i - 1]["v"] - curve[i]["v"]) for i in range(1, len(curve))]
    # Ignore the very start (everyone scrolls past in the first seconds) for "drop" ranking.
    drops = sorted([s for s in steps if s[0]["x"] >= 0.03 and s[1]["x"] <= 0.95 and s[2] > 0.02],
                   key=lambda s: -s[2])[:max_each]  # skip intro scroll-past and end screens
    for a, b, d in drops:
        out.append(ev("drop", b, b["v"], -d, f"Drop: {round(d * 100, 1)} pts of viewers leave here"))
    rises = sorted([s for s in steps if s[2] < -0.01], key=lambda s: s[2])[:max_each]
    for a, b, d in rises:
        out.append(ev("replay", b, b["v"], -d, f"Replay: watch ratio rises {round(-d * 100, 1)} pts (rewinds/rewatches)"))
    # Sustained weak / strong stretches by relative performance.
    for kind, test, word in (("weak", lambda r: r < 0.35, "Weak stretch: below typical YouTube retention for this length"),
                             ("strong", lambda r: r > 0.65, "Strong stretch: above typical YouTube retention for this length")):
        run = []
        for p in curve + [{"x": 2, "v": 0}]:
            r = p.get("rel")
            if r is not None and test(r):
                run.append(p)
                continue
            if len(run) >= 3:
                mid = run[len(run) // 2]
                out.append(ev(kind, mid, mid.get("rel", 0), 0, f"{word} ({round(run[0]['x'] * 100)}–{round(run[-1]['x'] * 100)}%)"))
            run = []
    return sorted(out, key=lambda e: e["x"])


# ── Growth review: evidence-backed, actionable recommendations (spec v4 §18) ──
WORKFLOW = ["suggested", "prepared", "awaiting_approval", "approved", "executed", "verified", "evaluated",
            "reverted", "dismissed"]
WORKFLOW_STATUS = {"suggested": "open", "prepared": "open", "awaiting_approval": "open", "approved": "accepted",
                   "executed": "done", "verified": "done", "evaluated": "done", "reverted": "done",
                   "dismissed": "dismissed"}
DAILY_NEW_LIMIT = 5  # top opportunities per run (spec §9: 3–5/day)


def _guest(title):
    parts = [p.strip() for p in re.split(r"[|]", title or "") if p.strip()]
    if len(parts) < 2:
        return None
    g = re.sub(r"[^\w\s'\"“”.-]", "", parts[-1]).strip().strip("\"“”")
    return g if 2 < len(g) < 60 else None


def upsert_rec(conn, tenant_id, *, kind, asset_id, key, title, detail, evidence, diagnosis, hypotheses, steps,
               test_plan, impact, effort, confidence, priority, alternatives=None, basis="derived"):
    """Insert once per fingerprint; refresh evidence on an open item, never resurrect a dismissed one."""
    fp = _fingerprint(kind, asset_id, key)
    row = conn.execute("SELECT id, workflow FROM recommendations WHERE tenant_id=? AND fingerprint=?", (tenant_id, fp)).fetchone()
    vals = (title, detail, json.dumps(evidence), diagnosis, json.dumps(hypotheses), json.dumps(steps),
            json.dumps(test_plan), json.dumps(alternatives or []), impact, effort, confidence, priority)
    if row:
        if row["workflow"] in ("suggested", "prepared"):
            conn.execute("""UPDATE recommendations SET title=?, detail=?, evidence_json=?, diagnosis=?, hypotheses_json=?,
                            steps_json=?, test_plan_json=?, alternatives_json=?, impact=?, effort=?, confidence=?, priority=?
                            WHERE id=?""", vals + (row["id"],))
        return 0
    conn.execute(
        """INSERT INTO recommendations (id, tenant_id, asset_id, kind, priority, basis, title, detail, evidence_json,
           fingerprint, created_at, diagnosis, hypotheses_json, steps_json, test_plan_json, alternatives_json, impact,
           effort, confidence, workflow) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'suggested')""",
        (new_id("rec_"), tenant_id, asset_id, kind, priority, basis, title, detail, json.dumps(evidence), fp, utcnow(),
         diagnosis, json.dumps(hypotheses), json.dumps(steps), json.dumps(test_plan), json.dumps(alternatives or []),
         impact, effort, confidence))
    return 1


def growth_review(conn, tenant_id, limit=DAILY_NEW_LIMIT):
    """Deterministic triage → ranked candidates → at most `limit` new cards.

    Classes (hypotheses, never proven by one metric): distribution (low
    impressions), packaging (impressions ok, CTR low), content/hold (CTR ok or
    unknown, % viewed low), double-down (a clear winner), funnel (Shorts with
    reach whose full episode lags). Cohorts: same format (+ length bucket).
    """
    vids = videos(conn, tenant_id)
    curves = retention_curves(conn, tenant_id)
    longs = [v for v in vids if v["format"] == "long_form"]
    cands = []
    for v in vids:
        if (v["age_days"] or 0) < 7:
            continue
        m, views = v["metrics"], v["metrics"].get("views") or 0
        ps = peer_stats(vids, v)
        pm = ps["metrics"]
        if ps["n"] < 3 or views < 100:
            continue  # insufficient evidence: observe, don't change
        conf = "low" if views < 500 else "medium" if views < 5000 else "high"
        fmt = "Short" if v["format"] == "short_heuristic" else "long-form episode"
        ret, ctr, vpd, imp = (pm.get(k) for k in ("avg_pct_viewed", "ctr", "views_per_day", "impressions"))
        base_ev = [{"metric": "Views", "value": views, "basis": "measured"},
                   {"metric": "Age (days)", "value": v["age_days"], "basis": "measured"},
                   {"metric": "Peer set", "value": f"{ps['basis']} (n={ps['n']})", "basis": "derived"}]
        test = {"baseline": None, "metric": None, "window_days": 14,
                "success": None, "reassess": "after 14 days or 1,000 new impressions, whichever is later"}
        guest = _guest(v["title"])
        # Content / hold problem
        if ret and ret["percentile"] is not None and ret["percentile"] <= 25 and not (ctr and ctr["percentile"] <= 25):
            ev = base_ev + [{"metric": "Avg % viewed", "value": ret["value"], "peer_median": ret["peer_median"],
                             "percentile": ret["percentile"], "basis": "derived"}]
            evs = retention_events(curves.get(v["asset_id"], []), None, v["duration_s"], views)
            drop = next((e for e in sorted(evs, key=lambda e: e["delta"]) if e["kind"] == "drop"), None)
            steps = []
            if drop and drop["t"] is not None:
                ev.append({"metric": "Biggest drop", "value": f"{round(-drop['delta'] * 100, 1)} pts at {drop['t'] // 60}:{drop['t'] % 60:02d}",
                           "basis": "derived"})
                steps.append(f"Watch {drop['t'] // 60}:{drop['t'] % 60:02d} on YouTube and note what happens there (topic change, long setup, audio issue).")
            steps += ["Check that the first 30 seconds deliver what the title promises; don't re-edit the published video.",
                      f"For the next {fmt}, open with the guest's strongest answer and cut setup before the first point.",
                      "If the drop is a natural chapter break, add chapters so viewers can jump instead of leaving."]
            gap = (ret["peer_median"] - ret["value"]) / max(ret["peer_median"], 1)
            cands.append(dict(score=vpd["value"] * gap if vpd else gap, kind="retention_review", v=v, key="hold",
                title=f"Viewers leave early: “{v['title']}”",
                detail=f"Average viewed is {ret['value']:.1f}% vs {ret['peer_median']:.1f}% for comparable {fmt}s.",
                evidence=ev, diagnosis="content", confidence=conf, impact="medium" if conf != "low" else "low", effort="medium",
                hypotheses=[{"cause": "The opening takes too long to reach the payoff the title promises", "confidence": "medium"},
                            {"cause": "Topic or guest fit is weaker for this audience", "confidence": "low"},
                            {"cause": "Length: longer videos naturally hold a smaller share", "confidence": "low"}],
                steps=steps, test=dict(test, baseline=ret["value"], metric="avg % viewed on the next 2 comparable uploads",
                                         success=f"above the peer median ({ret['peer_median']:.1f}%)")))
        # Packaging problem (needs impressions)
        if ctr and imp and ctr["percentile"] is not None and ctr["percentile"] <= 25 and (imp["value"] or 0) >= 1000:
            ev = base_ev + [{"metric": "Impressions", "value": imp["value"], "basis": "measured"},
                            {"metric": "Impressions CTR", "value": ctr["value"], "peer_median": ctr["peer_median"],
                             "percentile": ctr["percentile"], "basis": "derived"}]
            cands.append(dict(score=(imp["value"] or 0) * (ctr["peer_median"] - ctr["value"]) / 100, kind="thumbnail_title_review",
                v=v, key="packaging", title=f"Shown often, clicked less: “{v['title']}”",
                detail=f"CTR {ctr['value']:.1f}% vs {ctr['peer_median']:.1f}% for comparable {fmt}s on {int(imp['value']):,} impressions.",
                evidence=ev, diagnosis="packaging", confidence=conf, impact="high", effort="low",
                hypotheses=[{"cause": "Thumbnail isn't readable at phone size or lacks a clear face/focal point", "confidence": "medium"},
                            {"cause": "Title doesn't state the payoff or the guest's authority", "confidence": "medium"}],
                steps=["Draft 3 titles (search, curiosity, guest authority) with the button on the episode page.",
                       "Make 2 thumbnail variants from real frames: guest close-up + 2–4 word headline in white/gold.",
                       "Use YouTube Studio Test & Compare if available; otherwise change one thing and mark it executed here.",
                       "Keep the original title/thumbnail saved (the history panel already has it) for rollback."],
                test=dict(test, baseline=ctr["value"], metric="impressions CTR", success=f"≥ peer median ({ctr['peer_median']:.1f}%)")))
        # Distribution problem
        if imp and imp["percentile"] is not None and imp["percentile"] <= 25 and ctr and ctr["percentile"] >= 50:
            cands.append(dict(score=0.5, kind="distribution_review", v=v, key="distribution",
                title=f"Good clicks, little reach: “{v['title']}”",
                detail="People click when they see it, but YouTube shows it less than comparable videos.",
                evidence=base_ev + [{"metric": "Impressions", "value": imp["value"], "peer_median": imp["peer_median"],
                                     "percentile": imp["percentile"], "basis": "derived"}],
                diagnosis="distribution", confidence=conf, impact="medium", effort="low",
                hypotheses=[{"cause": "Few search/suggested entry points for this topic", "confidence": "medium"}],
                steps=["Cut 2–3 Shorts from its strongest moments and link each to this episode (related video).",
                       "Add it to a topic playlist and an end screen on your best-performing episode.",
                       "Rewrite the first two description lines around the main search phrase."],
                test=dict(test, baseline=imp["value"], metric="impressions per day", success="up vs the 14 days before")))
        # Double down on a clear winner
        if vpd and vpd["percentile"] is not None and vpd["percentile"] >= 90 and (ret is None or ret["percentile"] >= 50):
            cands.append(dict(score=vpd["value"] * 2, kind="double_down", v=v, key="winner",
                title=f"Winner: build on “{v['title']}”",
                detail=f"{vpd['value']:.0f} views/day vs a peer median of {vpd['peer_median']:.0f}.",
                evidence=base_ev + [{"metric": "Views per day", "value": vpd["value"], "peer_median": vpd["peer_median"],
                                     "percentile": vpd["percentile"], "basis": "derived"}],
                diagnosis="opportunity", confidence=conf, impact="high", effort="medium",
                hypotheses=[{"cause": "The topic/guest angle resonates with this audience", "confidence": "medium"}],
                steps=[f"Plan a follow-up on the same angle{f' (another conversation with {guest})' if guest else ''}.",
                       "Cut 2 more Shorts from the same recording if they exist.",
                       "Don't change this video's title or thumbnail: it's working."],
                test=dict(test, baseline=vpd["value"], metric="views/day of the follow-up", success="≥ peer median within 14 days")))
        # Shorts → full-episode funnel
        if v["format"] == "short_heuristic" and views >= 1500 and guest:
            full = next((l for l in longs if guest.lower() in (l["title"] or "").lower()), None)
            if full and (full["metrics"].get("views") or 0) < views / 5:
                cands.append(dict(score=views / 1000, kind="funnel", v=v, key=f"funnel:{full['asset_id']}",
                    title=f"Send Short viewers to the full {guest} episode",
                    detail=f"The Short has {int(views):,} views; the full episode “{full['title']}” has {int(full['metrics'].get('views') or 0):,}.",
                    evidence=base_ev + [{"metric": "Full-episode views", "value": full["metrics"].get("views") or 0, "basis": "measured"}],
                    diagnosis="distribution", confidence=conf, impact="medium", effort="low",
                    hypotheses=[{"cause": "Short viewers don't know the full conversation exists", "confidence": "medium"}],
                    steps=["In YouTube Studio, open the Short → Related video → choose the full episode.",
                           "Pin a comment on the Short: “Full conversation with {} → link”.".format(guest),
                           "Mark executed here; the app compares the full episode's views before/after."],
                    test=dict(test, baseline=full["metrics"].get("views") or 0, metric="full-episode views/day",
                              success="up vs the 14 days before")))
    cands.sort(key=lambda c: -c["score"])
    added = 0
    today_n = conn.execute("SELECT COUNT(*) FROM recommendations WHERE tenant_id=? AND created_at>=? AND diagnosis!=''",
                           (tenant_id, date.today().isoformat())).fetchone()[0]
    limit = max(0, limit - today_n)  # a cap per day, not per run
    for c in cands:
        if added >= limit:
            break
        added += upsert_rec(conn, tenant_id, kind=c["kind"], asset_id=c["v"]["asset_id"], key=c["key"], title=c["title"],
                            detail=c["detail"], evidence=c["evidence"], diagnosis=c["diagnosis"], hypotheses=c["hypotheses"],
                            steps=c["steps"], test_plan=c["test"], impact=c["impact"], effort=c["effort"],
                            confidence=c["confidence"], priority=1 if c["impact"] == "high" else 2)
    evaluated = evaluate_executed(conn, tenant_id)
    return {"candidates": len(cands), "new": added, "evaluated": evaluated}


def _asset_snapshot(conn, tenant_id, asset_id):
    if not asset_id:
        return {}
    v = next((x for x in videos(conn, tenant_id) if x["asset_id"] == asset_id), None)
    if not v:
        return {}
    keep = ("views", "estimatedMinutesWatched", "averageViewPercentage", "videoThumbnailImpressions",
            "videoThumbnailImpressionsClickRate", "subscribersGained")
    return {"at": utcnow(), "title": v["title"], "age_days": v["age_days"], "views_per_day": v["views_per_day"],
            **{k: v["metrics"].get(k) for k in keep}}


def move_rec(conn, tenant_id, rec_id, to, actor="owner", note=""):
    if to not in WORKFLOW:
        raise ValueError(f"unknown state {to}")
    r = conn.execute("SELECT * FROM recommendations WHERE id=? AND tenant_id=?", (rec_id, tenant_id)).fetchone()
    if not r:
        raise LookupError("recommendation not found")
    frm = r["workflow"] or "suggested"
    snap = {}
    sets = {"workflow": to, "status": WORKFLOW_STATUS[to]}
    if to == "approved":
        snap = _asset_snapshot(conn, tenant_id, r["asset_id"])
    if to == "executed":  # applied manually by the owner (write access is off): snapshot the baseline now
        snap = _asset_snapshot(conn, tenant_id, r["asset_id"])
        sets["baseline_json"] = json.dumps(snap)
        sets["evaluate_after"] = (date.today() + timedelta(days=14)).isoformat()
    conn.execute(f"UPDATE recommendations SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), rec_id))
    conn.execute("INSERT INTO action_ledger (tenant_id, rec_id, from_state, to_state, actor, note, snapshot_json, at) "
                 "VALUES (?,?,?,?,?,?,?,?)", (tenant_id, rec_id, frm, to, actor, note, json.dumps(snap), utcnow()))
    return {"id": rec_id, "from": frm, "to": to}


def evaluate_executed(conn, tenant_id):
    """Observational before/after for executed items past their evaluation date (no causal claims)."""
    n = 0
    for r in conn.execute("""SELECT id, asset_id, baseline_json FROM recommendations WHERE tenant_id=? AND workflow IN
                             ('executed','verified') AND evaluate_after IS NOT NULL AND evaluate_after<=?""",
                          (tenant_id, date.today().isoformat())).fetchall():
        before = json.loads(r["baseline_json"] or "{}")
        after = _asset_snapshot(conn, tenant_id, r["asset_id"])
        res = {"before": before, "after": after, "note": "Observational comparison; other factors also change over time."}
        conn.execute("UPDATE recommendations SET workflow='evaluated', status='done', result_json=? WHERE id=?",
                     (json.dumps(res), r["id"]))
        conn.execute("INSERT INTO action_ledger (tenant_id, rec_id, from_state, to_state, actor, note, snapshot_json, at) "
                     "VALUES (?,?,'executed','evaluated','analyst','auto-evaluated after 14 days',?,?)",
                     (tenant_id, r["id"], json.dumps(after), utcnow()))
        n += 1
    return n



# ── Format comparison, subscriber contribution, traffic over time ──────
def formats_compare(conn, tenant_id, days=28):
    end = conn.execute("SELECT MAX(period_start) FROM metrics WHERE tenant_id=? AND grain='day_ctype'", (tenant_id,)).fetchone()[0]
    vids = videos(conn, tenant_id)
    out = {"days": days, "as_of": end, "types": []}
    names = {"SHORTS": "Shorts", "VIDEO_ON_DEMAND": "Long-form", "LIVE_STREAM": "Live"}
    fmt_of = {"SHORTS": "short_heuristic", "VIDEO_ON_DEMAND": "long_form"}
    for ct, label in names.items():
        row = {"type": ct, "label": label}
        if end:
            start = (date.fromisoformat(end) - timedelta(days=days - 1)).isoformat()
            v, _ = _ctype_sum(conn, tenant_id, "views", (ct,), start, end)
            w, _ = _ctype_sum(conn, tenant_id, "estimatedMinutesWatched", (ct,), start, end)
            row.update(views=int(v), watch_hours=round(w / 60, 1))
        group = [x for x in vids if x["format"] == fmt_of.get(ct)]
        if not group and not row.get("views"):
            continue
        subs = sum((x["metrics"].get("subscribersGained") or 0) for x in group)
        pcts = [x["metrics"]["averageViewPercentage"] for x in group if x["metrics"].get("averageViewPercentage") is not None]
        durs = [x["metrics"]["averageViewDuration"] for x in group if x["metrics"].get("averageViewDuration") is not None]
        row.update(videos=len(group), subs_gained_lifetime=int(subs),
                   median_pct_viewed=round(statistics.median(pcts), 1) if pcts else None,
                   median_avg_view_s=round(statistics.median(durs)) if durs else None)
        out["types"].append(row)
    return out


def subscriber_contribution(conn, tenant_id, top=12):
    vids = [v for v in videos(conn, tenant_id) if v["metrics"].get("subscribersGained")]
    vids.sort(key=lambda v: -(v["metrics"]["subscribersGained"] or 0))
    total = sum(v["metrics"]["subscribersGained"] for v in vids)
    return {"total": int(total), "items": [{"asset_id": v["asset_id"], "title": v["title"], "format": v["format"],
                                            "subs": int(v["metrics"]["subscribersGained"]),
                                            "per_1k_views": round(1000 * v["metrics"]["subscribersGained"] / v["metrics"]["views"], 2)
                                            if v["metrics"].get("views") else None} for v in vids[:top]]}


def traffic_over_time(conn, tenant_id, days=90, top=5):
    end = conn.execute("SELECT MAX(period_start) FROM metrics WHERE tenant_id=? AND grain='day_traffic'", (tenant_id,)).fetchone()[0]
    if not end:
        return {"available": False, "series": []}
    start = (date.fromisoformat(end) - timedelta(days=days - 1)).isoformat()
    rows = conn.execute("""SELECT asset_id, period_start, value FROM metrics WHERE tenant_id=? AND grain='day_traffic'
                           AND metric_name='views' AND period_start BETWEEN ? AND ?""", (tenant_id, start, end)).fetchall()
    tot = {}
    for a, d, v in rows:
        tot[a] = tot.get(a, 0) + v
    keep = [a for a, _ in sorted(tot.items(), key=lambda x: -x[1])[:top]]
    # weekly buckets keep the lines readable
    weeks = {}
    for a, d, v in rows:
        if a not in keep:
            continue
        dt = date.fromisoformat(d)
        wk = (dt - timedelta(days=dt.weekday())).isoformat()
        weeks.setdefault(a, {}).setdefault(wk, 0)
        weeks[a][wk] += v
    allw = sorted({w for s in weeks.values() for w in s})
    return {"available": True, "as_of": end, "weeks": allw,
            "series": [{"source": a[8:], "total": int(tot[a]), "points": [{"d": w, "v": weeks[a].get(w, 0)} for w in allw]} for a in keep]}



def kpi_ctr(conn, tenant_id, days):
    """Channel impressions CTR over the window from reach-report rows (impression-weighted)."""
    end = conn.execute("""SELECT MAX(period_start) FROM metrics WHERE tenant_id=? AND grain='day_video'
                          AND metric_name='videoThumbnailImpressions'""", (tenant_id,)).fetchone()[0]
    if not end:
        return None

    def window(a, b):
        r = conn.execute("""SELECT SUM(i.value), SUM(i.value * COALESCE(c.value,0)) FROM metrics i LEFT JOIN metrics c
                            ON c.tenant_id=i.tenant_id AND c.asset_id=i.asset_id AND c.grain=i.grain AND c.period_start=i.period_start
                            AND c.metric_name='videoThumbnailImpressionsClickRate'
                            WHERE i.tenant_id=? AND i.grain='day_video' AND i.metric_name='videoThumbnailImpressions'
                            AND i.period_start BETWEEN ? AND ?""", (tenant_id, a, b)).fetchone()
        return (r[1] / r[0]) if r and r[0] else None
    e = date.fromisoformat(end)
    cur = window((e - timedelta(days=days - 1)).isoformat(), end)
    prev = window((e - timedelta(days=2 * days - 1)).isoformat(), (e - timedelta(days=days)).isoformat())
    return {"metric": "ctr", "label": "Impressions CTR", "unit": "pct", "days": days, "value": cur, "previous": prev,
            "change": ((cur - prev) / prev) if cur is not None and prev else None, "through": end, "quality": "verified"}
