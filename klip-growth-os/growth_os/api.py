"""Read models for the dashboard pages. Pure functions over a connection,
every one scoped by tenant_id. The HTTP layer (server.py) only routes."""

import json
import re
import statistics
from datetime import date, timedelta

from growth_os import thumbs as thumbs_mod, ai, analytics, prep, brands, reports, scheduler, trends, vault
from growth_os.db import get_setting, utcnow

PLATFORM_NOTES = {
    "youtube": "Google OAuth, read-only analytics scopes.",
    "instagram": "Needs a Meta developer app and an Instagram professional (Business/Creator) account linked to a Facebook Page.",
    "spotify": "No public analytics API. Verify the show, then import Spotify for Creators exports.",
    "apple_podcasts": "No public analytics API. Verify the show, then import Apple Podcasts Connect exports.",
}


def brand_json(b):
    d = dict(b)
    d["theme"] = json.loads(d.pop("theme_json") or "{}")
    d["is_demo"] = d.get("kind") == "demo"
    return d


def app_info(conn):
    return {
        "brands": [brand_json(b) for b in brands.list_brands(conn)],
        "ai": ai.status(conn),
        "alerts_open": conn.execute("SELECT COUNT(*) FROM alerts WHERE acked_at IS NULL").fetchone()[0],
        "running": [dict(r) for r in conn.execute(
            "SELECT run_id, kind, progress, message FROM job_runs WHERE state='running'")],
        "now": utcnow(),
    }


def _kpis(conn, t, days):
    """Spec v4 §20.1: views, watch hours, subscribers gained, CTR (when available), avg % viewed (when available)."""
    out = []
    for m in ("views", "estimatedMinutesWatched", "subscribersGained", "averageViewPercentage"):
        k = analytics.kpi(conn, t, m, days)
        if not k:
            continue
        if m == "estimatedMinutesWatched":
            k.update(label="Watch hours", value=k["value"] / 60 if k["value"] is not None else None,
                     previous=k["previous"] / 60 if k["previous"] is not None else None)
        if m == "averageViewPercentage":
            k.update(label="Avg % viewed", unit="pct")
        out.append(k)
    c = analytics.kpi_ctr(conn, t, days)
    if c:
        out.insert(3, c)
    return out


def _vid_card(v, extra=None):
    d = {k: v[k] for k in ("asset_id", "title", "published_at", "format", "duration_s", "age_days", "views_per_day",
                           "duration_bucket")}
    d["views"] = v["metrics"].get("views")
    d["ctr"] = v["metrics"].get("videoThumbnailImpressionsClickRate")
    d["impressions"] = v["metrics"].get("videoThumbnailImpressions")
    d["avg_pct_viewed"] = v["metrics"].get("averageViewPercentage")
    d["watch_minutes"] = v["metrics"].get("estimatedMinutesWatched")
    d["watch_hours"] = round(d["watch_minutes"] / 60, 1) if d["watch_minutes"] is not None else None
    d["avg_view_s"] = v["metrics"].get("averageViewDuration")
    d["quality"] = v["metrics"].get("_quality")
    d["thumb"] = f"/thumb/{v['tenant_id']}/{v['asset_id']}.jpg"
    if extra:
        d.update(extra)
    return d


def accounts_summary(conn, t):
    out = {}
    for p in brands.PLATFORMS:
        rows = [a for a in brands.accounts(conn, t, p) if a["state"] != brands.REJECTED]
        bound = next((a for a in rows if a["state"] in brands.BOUND), None)
        a = bound or (rows[-1] if rows else None)
        out[p] = {"state": a["state"] if a else brands.NOT_CONNECTED,
                  "name": a["account_name"] if a else None, "id": a["platform_account_id"] if a else None,
                  "data_as_of": a["data_as_of"] if a else None, "last_sync": a["last_successful_sync"] if a else None,
                  "error": a["last_error"] if a else None}
    return out


def home(conn, t):
    b = brand_json(brands.get_brand(conn, t))
    vids = analytics.videos(conn, t)
    settled = [v for v in vids if v["views_per_day"] is not None and (v["age_days"] or 0) >= 7]
    ranked = sorted(settled, key=lambda v: v["views_per_day"], reverse=True)
    recs = [dict(r) for r in conn.execute(
        "SELECT * FROM recommendations WHERE tenant_id=? AND status='open' ORDER BY priority, created_at DESC LIMIT 5", (t,))]
    trs = [dict(r) for r in conn.execute(
        "SELECT id, title, source, url, score, uncertainty, published_at FROM trends WHERE tenant_id=? AND status IN ('new','saved') "
        "ORDER BY score DESC LIMIT 4", (t,))]
    pod = {}
    for p, metric in (("spotify", "plays"), ("apple_podcasts", "listeners")):
        k = analytics.kpi(conn, t, metric, 28, platform=p)
        if k:
            k["series"] = analytics.series(conn, t, metric, 90, platform=p)
            pod[p] = k
    sched = [dict(r) for r in conn.execute("SELECT name, next_run_at, last_status, last_success_at FROM schedules ORDER BY next_run_at")]
    return {
        "brand": b, "accounts": accounts_summary(conn, t),
        "kpis": {str(d): _kpis(conn, t, d) for d in (7, 28, 90)},
        "spark": {m: analytics.series(conn, t, m, 90) for m in ("views", "estimatedMinutesWatched", "subscribersGained")},
        "best": [_vid_card(v) for v in ranked[:3]], "worst": [_vid_card(v) for v in ranked[-3:]] if len(ranked) > 6 else [],
        "recommendations": recs, "trends": trs, "podcasts": pod, "schedules": sched,
        "alerts": [dict(r) for r in conn.execute(
            "SELECT * FROM alerts WHERE acked_at IS NULL AND (tenant_id=? OR tenant_id IS NULL) ORDER BY id DESC LIMIT 5", (t,))],
        "freshness": analytics.freshness(conn, t),
    }


def overview(conn, t, days=90):
    d = _overview(conn, t, days)
    d["formats_compare"] = analytics.formats_compare(conn, t, 28)
    d["subscriber_contribution"] = analytics.subscriber_contribution(conn, t)
    d["traffic_over_time"] = analytics.traffic_over_time(conn, t, days)
    d["ctype_trend"] = prep.ctype_trend(conn, t, days)
    d["freshness_strip"] = prep.freshness_strip(conn, t)
    return d


def _overview(conn, t, days=90):
    vids = analytics.videos(conn, t)
    fmt = {}
    for v in vids:
        if v["views_per_day"] is None or (v["age_days"] or 0) < 7:
            continue
        fmt.setdefault(v["format"], []).append(v)
    def _med(vals):
        vals = [x for x in vals if x is not None]
        return statistics.median(vals) if vals else None  # None renders as "—", never a fake 0%

    formats = [{"format": f, "count": len(vs), "median_views_per_day": statistics.median(x["views_per_day"] for x in vs),
                "median_ctr": _med(x["metrics"].get("videoThumbnailImpressionsClickRate") for x in vs),
                "median_avg_pct_viewed": _med(x["metrics"].get("averageViewPercentage") for x in vs)}
               for f, vs in fmt.items()]
    traffic = {}
    for r in conn.execute("""SELECT period_start src, SUM(value) v FROM metrics WHERE tenant_id=? AND platform='youtube'
                             AND grain='traffic_source' GROUP BY period_start ORDER BY v DESC""", (t,)):
        traffic[r["src"]] = r["v"]
    gained = {r["d"]: r["v"] for r in analytics.series(conn, t, "subscribersGained", days)}
    lost = {r["d"]: r["v"] for r in analytics.series(conn, t, "subscribersLost", days)}
    return {
        "days": days, "kpis": _kpis(conn, t, days),
        "series": {m: analytics.series(conn, t, m, days) for m in ("views", "estimatedMinutesWatched", "averageViewDuration")},
        "net_subscribers": [{"d": d, "v": gained[d] - lost.get(d, 0)} for d in sorted(gained)],
        "formats": formats, "traffic_sources": traffic,
        "traffic_note": "Summed over videos with a traffic-source breakdown (top changed videos per sync), not the whole channel.",
        "freshness": analytics.freshness(conn, t),
    }


def video_list(conn, t):
    vids = analytics.videos(conn, t)
    hist = {r["asset_id"]: r["n"] for r in conn.execute(
        "SELECT asset_id, COUNT(*) n FROM asset_history WHERE tenant_id=? AND field='title' GROUP BY asset_id", (t,))}
    peaks = {r[0]: r[1] for r in conn.execute(
        """SELECT asset_id, MAX(value) FROM metrics WHERE tenant_id=? AND grain='retention_bucket'
           AND metric_name='audienceWatchRatio' GROUP BY asset_id""", (t,))}
    out = []
    for v in vids:
        ps = analytics.peer_stats(vids, v)
        out.append(_vid_card(v, {"title_versions": hist.get(v["asset_id"], 1),
                                 "rewatch_peak": round(peaks[v["asset_id"]], 2) if v["asset_id"] in peaks else None,
                                 "ctr_pctile": (ps["metrics"].get("ctr") or {}).get("percentile"),
                                 "ret_pctile": (ps["metrics"].get("avg_pct_viewed") or {}).get("percentile"),
                                 "vpd_pctile": (ps["metrics"].get("views_per_day") or {}).get("percentile")}))
    return out


def _history(conn, t, asset_id):
    return [dict(r) for r in conn.execute(
        "SELECT field, value, observed_at, source FROM asset_history WHERE tenant_id=? AND asset_id=? ORDER BY observed_at",
        (t, asset_id))]


def _ai_cached(conn, t, purpose_prefix):
    r = conn.execute("SELECT output_json, model, created_at FROM ai_cache WHERE tenant_id=? AND purpose=? ORDER BY created_at DESC LIMIT 1",
                     (t, purpose_prefix)).fetchone()
    return {"output": json.loads(r["output_json"]), "model": r["model"], "created_at": r["created_at"]} if r else None


def video_detail(conn, t, asset_id):
    vids = analytics.videos(conn, t)
    v = next((x for x in vids if x["asset_id"] == asset_id), None)
    if not v:
        raise brands.BrandError("not_found", "video not found for this brand")
    curves = analytics.retention_curves(conn, t)
    ret = curves.get(asset_id, [])
    cohort = [x["asset_id"] for x in vids if x["format"] == v["format"] and x["asset_id"] != asset_id]
    bench, bench_n = analytics.benchmark_curve(curves, cohort)
    events = analytics.retention_events(ret, bench, v["duration_s"], v["metrics"].get("views"))
    segs = prep.load_transcript(t, asset_id)
    prep.attach_windows(events, segs)
    ts = {r["period_start"]: r["value"] for r in conn.execute(
        "SELECT period_start, value FROM metrics WHERE tenant_id=? AND asset_id=? AND grain='traffic_source' ORDER BY value DESC",
        (t, asset_id))}
    terms = [{"term": r["period_start"], "views": r["value"]} for r in conn.execute(
        "SELECT period_start, value FROM metrics WHERE tenant_id=? AND asset_id=? AND grain='search_term' ORDER BY value DESC",
        (t, asset_id))]
    feat = conn.execute("SELECT features_json, computed_at FROM thumbnail_features WHERE tenant_id=? AND asset_id=? "
                        "ORDER BY computed_at DESC LIMIT 1", (t, asset_id)).fetchone()
    history = _history(conn, t, asset_id)
    latest = {}
    for h in history:
        latest[h["field"]] = h["value"]
    kw = analytics.topic_keywords(conn, t)
    recs = [dict(r) for r in conn.execute("SELECT * FROM recommendations WHERE tenant_id=? AND asset_id=? ORDER BY created_at DESC",
                                          (t, asset_id))]
    return {
        "video": _vid_card(v), "metrics": v["metrics"], "peers": analytics.peer_stats(vids, v),
        "retention": ret, "benchmark": bench, "benchmark_n": bench_n, "retention_events": events,
        "transcript": {"segments": len(segs), "file": prep.transcript_path(t, asset_id).name} if segs else None,
        "transcript_note": None if segs else (
            "Transcript not linked yet. In YouTube Studio → Subtitles, download the .srt for this video and save it as "
            f"data/transcripts/{asset_id}.srt; each retention marker then shows what was said there."),
        "rewatch": analytics.rewatch_summary(ret, v["metrics"].get("averageViewPercentage"), v["format"]),
        "retention_note": "Aggregate audience retention (share of viewers still watching at each point). "
                                            "It does not show individual viewers.",
        "traffic_sources": ts, "search_terms": terms,
        "thumbnail": {"features": json.loads(feat["features_json"]) if feat else None,
                      "computed_at": feat["computed_at"] if feat else None},
        "title_checks": analytics.title_checks(v["title"], kw, [x["term"] for x in terms[:8]]),
        "seo": seo_checks(latest, v["title"], kw),
        "history": [h for h in history if h["field"] in ("title", "thumbnail")],
        "recommendations": recs,
        "ai_titles": _ai_cached(conn, t, f"titles:{asset_id}"),
        "ai_thumbnail": _ai_cached(conn, t, f"thumbnail:{asset_id}"),
        "youtube_url": None if v["tenant_id"] == "demo-synthetic" else f"https://www.youtube.com/watch?v={asset_id}",
    }


def seo_checks(latest, title, kw):
    desc = latest.get("description") or ""
    tags = json.loads(latest.get("tags") or "[]") if latest.get("tags") else []
    chapters = len(re.findall(r"(?m)^\s*\d{1,2}:\d{2}", desc))
    words = len(desc.split())
    kws = [k for k, _ in kw if k.lower() in desc.lower()]
    known = "description" in latest
    out = [
        {"label": "Description length", "value": f"{words} words" if known else None,
         "status": "na" if not known else "ok" if words >= 120 else "warn",
         "note": "Not synced yet." if not known else "Short descriptions give search less context." if words < 120 else ""},
        {"label": "Chapters", "value": chapters if known else None,
         "status": "na" if not known else "ok" if chapters >= 3 else "warn",
         "note": "" if chapters >= 3 else "YouTube needs 3+ timestamps starting at 00:00 to show chapters."},
        {"label": "Topic keywords in description", "value": ", ".join(kws) if known else None,
         "status": "na" if not known else "ok" if kws else "warn", "note": ""},
        {"label": "Tags", "value": len(tags) if "tags" in latest else None,
         "status": "na" if "tags" not in latest else "info", "note": "Tags have minor weight; mainly helps misspellings."},
        {"label": "Captions", "value": latest.get("captions"),
         "status": "na" if "captions" not in latest else "ok" if latest.get("captions") == "true" else "warn",
         "note": "" if latest.get("captions") == "true" else "Uploaded or corrected captions improve accessibility and search."},
    ]
    return out


def thumbnails(conn, t):
    vids = analytics.videos(conn, t)
    feats = {r["asset_id"]: json.loads(r["features_json"]) for r in conn.execute(
        """SELECT asset_id, features_json FROM thumbnail_features f WHERE tenant_id=? AND computed_at =
           (SELECT MAX(computed_at) FROM thumbnail_features g WHERE g.tenant_id=f.tenant_id AND g.asset_id=f.asset_id)""", (t,))}
    changes = {r["asset_id"]: r["n"] for r in conn.execute(
        "SELECT asset_id, COUNT(*) n FROM asset_history WHERE tenant_id=? AND field='thumbnail' GROUP BY asset_id", (t,))}
    flagged = {r["asset_id"]: r["title"] for r in conn.execute(
        "SELECT asset_id, title FROM recommendations WHERE tenant_id=? AND kind='thumbnail_title_review' AND status='open'", (t,))}
    items = []
    for v in vids:
        ps = analytics.peer_stats(vids, v)
        f = feats.get(v["asset_id"])
        items.append(_vid_card(v, {
            "features": {k: f[k] for k in ("luminance", "contrast", "colorfulness", "saturation", "edge_density", "focal_contrast")} if f else None,
            "dominant": f["dominant_colors"] if f else None, "versions": changes.get(v["asset_id"], 1 if f else 0),
            "ctr_pctile": (ps["metrics"].get("ctr") or {}).get("percentile"),
            "ctr_peer_median": (ps["metrics"].get("ctr") or {}).get("peer_median"),
            "peer_basis": ps["basis"], "review": flagged.get(v["asset_id"])}))
    # Feature ↔ CTR association across long-form videos (descriptive only).
    assoc = {}
    lf = [i for i in items if i["features"] and i["ctr"] is not None and i["format"] == "long_form" and (i["age_days"] or 0) >= 7]
    for k in ("luminance", "contrast", "colorfulness", "saturation", "edge_density", "focal_contrast"):
        if len(lf) >= 8:
            assoc[k] = round(statistics.correlation([i["features"][k] for i in lf], [i["ctr"] for i in lf]), 2)
    tg = thumbs_mod.tags(conn, t)
    for i in items:
        i["thumb_format"] = tg.get(i["asset_id"])
        i["thumb_format_suggested"], i["thumb_format_why"] = thumbs_mod.suggest_format(i["title"])
    return {"items": items, "association": assoc, "association_n": len(lf),
            "format_performance": thumbs_mod.format_performance(conn, t), "formats": thumbs_mod.FORMATS,
            "experiments": thumbs_mod.experiments(conn, t),
            "association_note": "Correlation across this brand's long-form videos (Pearson r). Descriptive only: it is "
                                "not a test result and many other factors affect CTR.",
            "experiments_note": "To compare thumbnails properly, use YouTube Studio's Test & Compare where available. "
                                "This app never replaces a published thumbnail without your approval."}


def titles(conn, t):
    vids = analytics.videos(conn, t)
    kw = analytics.topic_keywords(conn, t)
    terms = {}
    for r in conn.execute("SELECT asset_id, period_start FROM metrics WHERE tenant_id=? AND grain='search_term' ORDER BY value DESC", (t,)):
        terms.setdefault(r["asset_id"], []).append(r["period_start"])
    hist = {}
    for r in conn.execute("SELECT asset_id, value, observed_at FROM asset_history WHERE tenant_id=? AND field='title' ORDER BY observed_at", (t,)):
        hist.setdefault(r["asset_id"], []).append({"title": r["value"], "observed_at": r["observed_at"]})
    items = []
    for v in vids:
        checks = analytics.title_checks(v["title"], kw, terms.get(v["asset_id"], [])[:8])
        ps = analytics.peer_stats(vids, v)
        items.append(_vid_card(v, {"checks": checks, "warnings": sum(1 for c in checks if c["status"] == "warn"),
                                   "revisions": hist.get(v["asset_id"], []),
                                   "ctr_pctile": (ps["metrics"].get("ctr") or {}).get("percentile"),
                                   "search_terms": terms.get(v["asset_id"], [])[:5], "length": len(v["title"] or "")}))
    # Competitor title patterns from public feeds.
    comp = [r["title"] for r in conn.execute(
        "SELECT title FROM trends WHERE tenant_id=? AND source_type='youtube_competitor' ORDER BY published_at DESC LIMIT 50", (t,))]
    patterns = None
    if comp:
        patterns = {"n": len(comp), "median_length": statistics.median(len(c) for c in comp),
                    "share_question": round(sum(c.strip().endswith("?") for c in comp) / len(comp), 2),
                    "share_number": round(sum(bool(re.search(r"\d", c)) for c in comp) / len(comp), 2),
                    "share_pipe": round(sum("|" in c for c in comp) / len(comp), 2)}
    return {"items": items, "competitor_patterns": patterns, "strategies": ai.TITLE_STRATEGIES}


def trend_page(conn, t, status=None):
    sql = "SELECT * FROM trends WHERE tenant_id=?"
    args = [t]
    if status:
        sql += " AND status=?"
        args.append(status)
    else:
        sql += " AND status!='dismissed'"
    rows = []
    for r in conn.execute(sql + " ORDER BY score DESC LIMIT 80", args):
        d = dict(r)
        d["score_parts"] = json.loads(d.pop("score_json") or "{}")
        d["ai"] = json.loads(d["ai_json"]) if d.get("ai_json") else None
        rows.append(d)
    last = conn.execute("SELECT state, finished_at, message, result_json FROM job_runs WHERE kind='trend_research' "
                        "ORDER BY queued_at DESC LIMIT 1").fetchone()
    return {"items": rows, "keywords": [{"keyword": k, "weight": w} for k, w in analytics.topic_keywords(conn, t)],
            "gaps": trends.competitor_gaps(conn, t), "weights": trends.WEIGHTS,
            "last_run": dict(last) if last else None,
            "note": "Opportunity score is a heuristic from relevance, freshness, corroboration and novelty. "
                    "It is not search volume and not a prediction of views."}


def seo(conn, t):
    kw = analytics.topic_keywords(conn, t)
    latest = {}
    for r in conn.execute("SELECT asset_id, field, value FROM asset_history WHERE tenant_id=? ORDER BY observed_at", (t,)):
        latest.setdefault(r["asset_id"], {})[r["field"]] = r["value"]
    out = []
    for v in analytics.videos(conn, t):
        checks = seo_checks(latest.get(v["asset_id"], {}), v["title"], kw)
        out.append(_vid_card(v, {"checks": checks, "issues": sum(1 for c in checks if c["status"] == "warn")}))
    return {"items": out}


def recommendations(conn, t):
    rows = []
    ledger = {}
    for r in conn.execute("SELECT rec_id, from_state, to_state, actor, note, at FROM action_ledger WHERE tenant_id=? ORDER BY id", (t,)):
        ledger.setdefault(r["rec_id"], []).append(dict(r))
    titles = {r[0]: r[1] for r in conn.execute("SELECT asset_id, title FROM assets WHERE tenant_id=?", (t,))}
    for r in conn.execute("SELECT * FROM recommendations WHERE tenant_id=? ORDER BY status='open' DESC, priority, created_at DESC LIMIT 200", (t,)):
        d = dict(r)
        d["evidence"] = json.loads(d.pop("evidence_json"))
        for k in ("hypotheses", "steps", "test_plan", "alternatives", "baseline", "result"):
            raw = d.pop(f"{k}_json", None)
            d[k] = json.loads(raw) if raw else ({} if k in ("test_plan", "baseline", "result") else [])
        d["workflow"] = d.get("workflow") or ("dismissed" if d["status"] == "dismissed" else "suggested")
        d["state_label"] = analytics.STATE_LABELS.get(d["workflow"], d["workflow"].upper())
        alts = d.get("alternatives")
        d["prepared"] = alts.get("prepared") if isinstance(alts, dict) and d["kind"] not in prep.NO_REPACKAGE else None
        d["ledger"] = ledger.get(d["id"], [])
        d["asset_title"] = titles.get(d["asset_id"])
        rows.append(d)
    yt = conn.execute("SELECT platform_account_id FROM platform_accounts WHERE tenant_id=? AND platform='youtube' "
                      "AND state!='REJECTED' LIMIT 1", (t,)).fetchone()
    return {"items": rows, "workflow": analytics.WORKFLOW, "state_labels": analytics.STATE_LABELS,
            "checkpoints": analytics.CHECKPOINTS, "channel_id": yt[0] if yt else None, "write_access": False,
            "write_note": "Write access to YouTube is off (read-only). Approved items are applied by you in YouTube Studio, "
                          "then marked Executed here so the app can compare before/after."}


def calendar(conn, t, month):
    start = date.fromisoformat(month + "-01")
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    items = [dict(r) for r in conn.execute("SELECT * FROM calendar_items WHERE tenant_id=? AND day>=? AND day<? ORDER BY day",
                                           (t, start.isoformat(), end.isoformat()))]
    published = [{"day": r["published_at"][:10], "title": r["title"], "asset_id": r["asset_id"], "format": r["format"]}
                 for r in conn.execute("SELECT * FROM assets WHERE tenant_id=? AND published_at>=? AND published_at<?",
                                       (t, start.isoformat(), end.isoformat()))]
    return {"month": month, "items": items, "published": published}


def podcasts(conn, t):
    out = {}
    for p in ("spotify", "apple_podcasts"):
        metrics = [r[0] for r in conn.execute("SELECT DISTINCT metric_name FROM metrics WHERE tenant_id=? AND platform=? AND grain='day'", (t, p))]
        out[p] = {"account": accounts_summary(conn, t)[p], "note": PLATFORM_NOTES[p],
                  "series": {m: analytics.series(conn, t, m, 120, platform=p) for m in metrics},
                  "kpis": [analytics.kpi(conn, t, m, 28, platform=p) for m in metrics]}
    return out


def jobs(conn):
    scheds = []
    for s in conn.execute("SELECT * FROM schedules ORDER BY name"):
        d = dict(s)
        d["spec"] = json.loads(d.pop("spec_json"))
        d["describe"] = scheduler.describe(d["spec"])
        d["description"] = scheduler.DESCRIPTIONS.get(d["name"], d["kind"])
        scheds.append(d)
    runs = [dict(r) for r in conn.execute(
        "SELECT run_id, schedule_name, kind, tenant_id, trigger, state, attempt, progress, message, queued_at, started_at, "
        "finished_at, next_retry_at FROM job_runs ORDER BY queued_at DESC LIMIT 40")]
    today = utcnow()[:10]
    usage = [dict(r) for r in conn.execute(
        """SELECT kind, name, COUNT(*) calls, SUM(cache_hit) cache_hits, SUM(quota_units) quota_units, SUM(tokens_in) tokens_in,
           SUM(tokens_out) tokens_out, SUM(CASE WHEN status>=400 THEN 1 ELSE 0 END) errors
           FROM usage_log WHERE at>=? GROUP BY kind, name ORDER BY calls DESC""", (today,))]
    cost = conn.execute("SELECT COALESCE(SUM(cost_usd),0), COUNT(*) FROM ai_cache WHERE created_at>=?", (today,)).fetchone()
    lock = conn.execute("SELECT holder, expires_at FROM locks WHERE name='scheduler'").fetchone()
    integrations = []
    for b in brands.list_brands(conn):
        for p, a in accounts_summary(conn, b["tenant_id"]).items():
            integrations.append({"brand": b["display_name"], "tenant_id": b["tenant_id"], "kind": b["kind"], "platform": p, **a})
    return {
        "schedules": scheds, "runs": runs, "usage": usage,
        "ai": ai.status(conn) | {"cost_estimate_today_usd": round(cost[0], 4), "fresh_calls_today": cost[1]},
        "alerts": [dict(r) for r in conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 30")],
        "scheduler_alive": bool(lock and lock["expires_at"] > utcnow()),
        "integrations": integrations,
        "env": {"youtube_client": bool(vault.load_client("youtube")), "pdf_browser": bool(reports.find_browser()),
                "api_budget_per_day": int(__import__("growth_os.http", fromlist=["x"]).DEFAULT_DAILY_REQUESTS)},
    }


def settings(conn, t):
    return {"topics": [{"keyword": k, "weight": w} for k, w in analytics.topic_keywords(conn, t)],
            "competitors": [dict(r) for r in conn.execute("SELECT ref, name FROM competitors WHERE tenant_id=? AND platform='youtube'", (t,))],
            "ai": ai.status(conn), "ai_daily_calls": get_setting(conn, "ai.daily_calls", ai.DEFAULT_DAILY_CALLS)}


def thumb_studio(conn, t, asset_id):
    rec = thumbs_mod.recommend_format(conn, t, asset_id)
    title = conn.execute("SELECT title FROM assets WHERE tenant_id=? AND asset_id=?", (t, asset_id)).fetchone()[0]
    prev = [json.loads(r[0]) | {"at": r[1]} for r in conn.execute(
        "SELECT value, observed_at FROM asset_history WHERE tenant_id=? AND asset_id=? AND field='thumb_preview' "
        "ORDER BY observed_at DESC LIMIT 6", (t, asset_id))]
    for p_ in prev:
        for v in p_["variants"]:
            v.setdefault("url", f"/preview/{t}/{asset_id}/{v['file']}")
        p_["sheet_url"] = f"/preview/{t}/{asset_id}/{p_['sheet']}"
    return {**rec, "formats": thumbs_mod.FORMATS, "default_headlines": thumbs_mod.default_headlines(title),
            "previews": prev, "experiments": [e for e in thumbs_mod.experiments(conn, t) if e["asset_id"] == asset_id],
            "rules": ["Previews reuse this video's own photo and logo; faces are never changed.",
                      "Nothing is uploaded. Changing the live thumbnail needs your approval (done in YouTube Studio).",
                      "Use YouTube Studio Test & Compare when available, then record the result here.",
                      "Hosts are only suggested when their reaction or debate strengthens the hook."]}
