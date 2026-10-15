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
