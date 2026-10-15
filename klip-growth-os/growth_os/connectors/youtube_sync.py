"""Incremental YouTube sync used by the scheduler (P2).

Delta rules: daily channel metrics re-fetch only from the cursor minus a
3-day lag window; video metadata is skipped when the etag is unchanged;
per-video traffic/search breakdowns run only for the top videos whose views
changed; thumbnails are downloaded and analysed only when their URL/bytes
change.
"""

import hashlib
import re
import json
from datetime import date, timedelta

from growth_os import analytics, brands
from growth_os.connectors import youtube, youtube_reporting
from growth_os.connectors.youtube import ANALYTICS_API, DATA_API, ConnectorError, _get, parse_duration
from growth_os.db import DATA_DIR, utcnow
from growth_os.http import Client

LAG_DAYS = 3
BACKFILL_START = "2005-02-14"
MAX_VIDEOS = 250
BREAKDOWN_TOP_N = 10
RETENTION_PER_SYNC = 15   # retention curves fetched per sync (new/changed first), 1 quota unit each
CTYPE_BACKFILL_DAYS = 400  # monetization windows need 365 days of long-form watch time


def _cursor(conn, tenant_id, row_id, name):
    r = conn.execute("SELECT value FROM sync_cursors WHERE tenant_id=? AND platform_account_row=? AND name=?",
                     (tenant_id, row_id, name)).fetchone()
    return r[0] if r else None


def _set_cursor(conn, tenant_id, row_id, name, value):
    conn.execute("INSERT OR REPLACE INTO sync_cursors VALUES (?,?,?,?,?)", (tenant_id, row_id, name, value, utcnow()))


def record_history(conn, tenant_id, platform, asset_id, field, value, source):
    h = hashlib.sha256((value or "").encode()).hexdigest()[:16]
    cur = conn.execute("INSERT OR IGNORE INTO asset_history VALUES (?,?,?,?,?,?,?,?)",
                       (tenant_id, platform, asset_id, field, value, h, utcnow(), source))
    return cur.rowcount == 1


def cache_thumbnail(conn, tenant_id, asset_id, url, http_get=None):
    """Download once per distinct URL, then compute features once per image hash."""
    if not url:
        return None
    d = DATA_DIR / "thumbs" / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{asset_id}.jpg"
    url_key = DATA_DIR / "thumbs" / tenant_id / f"{asset_id}.url"
    if not path.exists() or not url_key.exists() or url_key.read_text() != url:
        if http_get is None:
            import urllib.request
            with urllib.request.urlopen(url, timeout=20) as r:
                data = r.read()
        else:
            data = http_get(url)
        path.write_bytes(data)
        url_key.write_text(url)
    h = analytics.file_hash(path)
    if not conn.execute("SELECT 1 FROM thumbnail_features WHERE tenant_id=? AND asset_id=? AND image_hash=?",
                        (tenant_id, asset_id, h)).fetchone():
        conn.execute("INSERT INTO thumbnail_features VALUES (?,?,?,?,?)",
                     (tenant_id, asset_id, h, json.dumps(analytics.thumbnail_features(path)), utcnow()))
        record_history(conn, tenant_id, "youtube", asset_id, "thumbnail", h, "thumbnail bytes")
    return h


def sync(conn, tenant_id, row_id, *, client, transport=None, today=None, progress=lambda p, m: None):
    acct = brands.get_account(conn, tenant_id, row_id)
    if acct["state"] not in (brands.ACTIVE, brands.SYNC_FAILED, brands.ASSIGNED):
        return {"skipped": f"account is {acct['state']}"}
    # Re-run the identity check + small sample first; it also flips SYNCING/ACTIVE.
    sample = youtube.sync_sample(conn, tenant_id, row_id, client=client, transport=transport, today=today)
    http = Client(conn, tenant_id, run_id=sample["run_id"], transport=transport)
    cred, ch_id = acct["credential_id"], acct["platform_account_id"]
    today = today or date.today()
    g = lambda url, params: _get(http, conn, tenant_id, cred, client, url, params)  # noqa: E731
    out = {"channel_id": ch_id, "unavailable": list(sample["unavailable"])}

    # 1. Daily channel metrics, delta from cursor with a lag window.
    progress(15, "daily channel metrics")
    cur = _cursor(conn, tenant_id, row_id, "daily_through")
    has_pct = conn.execute("SELECT 1 FROM metrics WHERE tenant_id=? AND grain='day' AND metric_name='averageViewPercentage' LIMIT 1",
                           (tenant_id,)).fetchone()
    start = BACKFILL_START if (not cur or not has_pct) else (date.fromisoformat(cur) - timedelta(days=LAG_DAYS)).isoformat()
    daily = g(ANALYTICS_API, {"ids": "channel==MINE", "startDate": start, "endDate": today.isoformat(),
                              "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                                         "subscribersGained,subscribersLost",
                              "dimensions": "day", "sort": "day"})
    cols = [h["name"] for h in daily.get("columnHeaders", [])]
    fetched = utcnow()
    through = None
    for r in daily.get("rows", []):
        rec = dict(zip(cols, r))
        through = rec["day"]
        for m in cols[1:]:
            youtube._put_metric(conn, tenant_id, ch_id, ch_id, m, float(rec[m]), "", "day", rec["day"],
                                "youtube.analytics.reports", fetched, None, "verified")
    if through:
        conn.execute("UPDATE metrics SET available_through=? WHERE tenant_id=? AND platform='youtube' AND grain='day'",
                     (through, tenant_id))
        _set_cursor(conn, tenant_id, row_id, "daily_through", through)
    out["daily_rows"] = len(daily.get("rows", []))

    # 2. Uploads + metadata (etag skip) + title/description/thumbnail history.
    progress(35, "video metadata")
    chs = g(f"{DATA_API}/channels", {"part": "contentDetails", "mine": "true"})
    uploads = chs["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while len(ids) < MAX_VIDEOS:
        params = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
        if token:
            params["pageToken"] = token
        pl = g(f"{DATA_API}/playlistItems", params)
        ids += [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        token = pl.get("nextPageToken")
        if not token:
            break
    known = {r["asset_id"]: r["etag"] for r in conn.execute(
        "SELECT asset_id, etag FROM assets WHERE tenant_id=? AND platform='youtube'", (tenant_id,))}
    changed_meta = 0
    for i in range(0, len(ids), 50):
        vs = g(f"{DATA_API}/videos", {"part": "snippet,contentDetails,statistics,status", "id": ",".join(ids[i:i + 50])})
        for v in vs.get("items", []):
            sn = v["snippet"]
            thumb = (sn.get("thumbnails", {}).get("maxres") or sn.get("thumbnails", {}).get("high")
                     or sn.get("thumbnails", {}).get("medium") or {}).get("url")
            if known.get(v["id"]) == v.get("etag"):
                continue
            changed_meta += 1
            dur = parse_duration(v["contentDetails"].get("duration", ""))
            fmt = "short_heuristic" if dur is not None and dur <= youtube.SHORTS_MAX_SECONDS else "long_form"
            conn.execute("INSERT OR REPLACE INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (tenant_id, "youtube", ch_id, v["id"], sn.get("title"), sn.get("publishedAt"), dur, fmt,
                          thumb, v.get("etag"), fetched))
            record_history(conn, tenant_id, "youtube", v["id"], "title", sn.get("title"), "youtube.data.videos")
            record_history(conn, tenant_id, "youtube", v["id"], "description", sn.get("description", ""), "youtube.data.videos")
            record_history(conn, tenant_id, "youtube", v["id"], "tags", json.dumps(sn.get("tags", [])), "youtube.data.videos")
            record_history(conn, tenant_id, "youtube", v["id"], "privacy",
                           v.get("status", {}).get("privacyStatus", ""), "youtube.data.videos")
            record_history(conn, tenant_id, "youtube", v["id"], "captions",
                           v["contentDetails"].get("caption", "false"), "youtube.data.videos")
            try:
                cache_thumbnail(conn, tenant_id, v["id"], thumb)
            except Exception as e:  # thumbnail CDN hiccup must not fail the sync
                out["unavailable"].append(f"thumbnail {v['id']}: {str(e)[:80]}")
    out["videos"], out["metadata_changed"] = len(ids), changed_meta

    # 3. Per-video lifetime analytics in one report. Impressions metrics are
    # requested and, if the API refuses them, recorded as unavailable.
    progress(60, "per-video analytics")
    base = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,subscribersGained"
    params = {"ids": "channel==MINE", "startDate": BACKFILL_START, "endDate": today.isoformat(),
              "dimensions": "video", "sort": "-views", "maxResults": 200}
    try:
        rep = g(ANALYTICS_API, {**params, "metrics": base + ",videoThumbnailImpressions,videoThumbnailImpressionsClickRate"})
    except Exception as e:
        out["unavailable"].append(f"impressions/CTR not returned by YouTube Analytics API ({str(e)[:80]})")
        rep = g(ANALYTICS_API, {**params, "metrics": base})
    cols = [h["name"] for h in rep.get("columnHeaders", [])]
    prev_views = {r["asset_id"]: r["value"] for r in conn.execute(
        "SELECT asset_id, value FROM metrics WHERE tenant_id=? AND grain='video_lifetime' AND metric_name='views'",
        (tenant_id,))}
    changed = []
    for r in rep.get("rows", []):
        rec = dict(zip(cols, r))
        vid = rec["video"]
        if prev_views.get(vid) != float(rec["views"]):
            changed.append(vid)
        for m in cols[1:]:
            youtube._put_metric(conn, tenant_id, ch_id, vid, m, float(rec[m]), "", "video_lifetime", "lifetime",
                                "youtube.analytics.reports", fetched, through, "verified")

    # 3b. Impressions + CTR from the Reporting API reach report (bulk CSVs).
    progress(70, "impressions and CTR (reach reports)")
    try:
        out["reach"] = youtube_reporting.sync(conn, http, tenant_id, row_id, cred=cred, ch_id=ch_id, client=client)
        out["unavailable"] += out["reach"].pop("unavailable", [])
        if out["reach"]["rollup"]["videos"]:
            out["unavailable"] = [u for u in out["unavailable"] if not u.startswith("impressions/CTR not returned")]
    except Exception as e:  # reach data is additive; never fail the core sync over it
        out["unavailable"].append(f"impressions/CTR (Reporting API): {str(e)[:120]}")

    # 4. Traffic sources + search terms only for the top changed videos.
    progress(80, "traffic sources and search terms")
    done_breakdowns = []
    for vid in changed[:BREAKDOWN_TOP_N]:
        try:
            ts = g(ANALYTICS_API, {"ids": "channel==MINE", "startDate": BACKFILL_START, "endDate": today.isoformat(),
                                   "metrics": "views", "dimensions": "insightTrafficSourceType", "filters": f"video=={vid}"})
            conn.execute("DELETE FROM metrics WHERE tenant_id=? AND asset_id=? AND grain='traffic_source'", (tenant_id, vid))
            for src, views in ts.get("rows", []):
                youtube._put_metric(conn, tenant_id, ch_id, vid, "views", float(views), "views", "traffic_source", src,
                                    "youtube.analytics.reports", fetched, through, "verified")
            st = g(ANALYTICS_API, {"ids": "channel==MINE", "startDate": BACKFILL_START, "endDate": today.isoformat(),
                                   "metrics": "views", "dimensions": "insightTrafficSourceDetail",
                                   "filters": f"video=={vid};insightTrafficSourceType==YT_SEARCH",
                                   "maxResults": 15, "sort": "-views"})
            conn.execute("DELETE FROM metrics WHERE tenant_id=? AND asset_id=? AND grain='search_term'", (tenant_id, vid))
            for term, views in st.get("rows", []):
                youtube._put_metric(conn, tenant_id, ch_id, vid, "views", float(views), "views", "search_term", term,
                                    "youtube.analytics.reports", fetched, through, "verified")
            done_breakdowns.append(vid)
        except Exception as e:  # one slow video must not lose the whole sync
            out["unavailable"].append(f"traffic sources {vid}: {str(e)[:80]}")
    out["breakdowns_for"] = done_breakdowns

    # 5. Views + watch time split by content type (Shorts vs long-form vs live),
    # daily, for the monetization tracker (YPP counts long-form watch hours and
    # Shorts-feed views separately).
    progress(88, "Shorts vs long-form watch time")
    try:
        out["content_type_days"] = sync_content_types(conn, g, tenant_id, row_id, ch_id, today, fetched)
    except Exception as e:
        out["unavailable"].append(f"Shorts vs long-form split: {str(e)[:100]}")

    # 5a. Channel traffic sources by day (for the traffic-over-time chart).
    try:
        out["traffic_days"] = sync_traffic_days(conn, g, tenant_id, row_id, ch_id, today, fetched)
    except Exception as e:
        out["unavailable"].append(f"traffic sources by day: {str(e)[:100]}")

    # 5b. Audience breakdowns for the last 90 days (age/gender, country, device,
    # subscribed vs not). Aggregates only; YouTube withholds small groups.
    progress(91, "audience breakdowns")
    try:
        out["audience"] = sync_audience(conn, g, tenant_id, ch_id, today, fetched, through)
    except Exception as e:
        out["unavailable"].append(f"audience breakdowns: {str(e)[:100]}")

    # 6. Retention curves (incl. rewatch peaks) for every video, a few per sync.
    progress(94, "retention curves")
    have = {r[0] for r in conn.execute(
        "SELECT DISTINCT asset_id FROM metrics WHERE tenant_id=? AND grain='retention_bucket'", (tenant_id,))}
    queue = [v for v in changed if v not in have] + [v for v in ids if v not in have and v not in changed] \
        + [v for v in changed if v in have]
    got = []
    for vid in queue[:RETENTION_PER_SYNC]:
        try:
            if fetch_retention(conn, g, tenant_id, ch_id, vid, today, fetched, through):
                got.append(vid)
        except Exception as e:
            out["unavailable"].append(f"retention {vid}: {str(e)[:80]}")
    out["retention_fetched"] = got

    # 7. Per-video daily views for launch cohorts (day 1/3/7/28 since publish).
    progress(97, "launch cohorts")
    try:
        out["cohort_videos"] = sync_video_days(conn, g, tenant_id, ch_id, today, fetched)
    except Exception as e:
        out["unavailable"].append(f"launch cohorts: {str(e)[:100]}")
    out["available_through"] = through
    progress(100, "done")
    return out


def sync_content_types(conn, g, tenant_id, row_id, ch_id, today, fetched):
    cur = _cursor(conn, tenant_id, row_id, "ctype_through")
    start = (today - timedelta(days=CTYPE_BACKFILL_DAYS)) if not cur else (date.fromisoformat(cur) - timedelta(days=LAG_DAYS))
    rep = g(ANALYTICS_API, {"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": today.isoformat(),
                            "metrics": "views,estimatedMinutesWatched", "dimensions": "day,creatorContentType",
                            "sort": "day"})
    cols = [h["name"] for h in rep.get("columnHeaders", [])]
    last = None
    n = 0
    for r in rep.get("rows", []):
        rec = dict(zip(cols, r))
        # API returns camelCase ("videoOnDemand", "shorts", "liveStream"); store UPPER_SNAKE.
        ct = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", rec.get("creatorContentType") or "UNSPECIFIED").upper()
        last = rec["day"]
        for m in ("views", "estimatedMinutesWatched"):
            if m in rec:
                youtube._put_metric(conn, tenant_id, ch_id, f"ctype:{ct}", m, float(rec[m]), "", "day_ctype",
                                    rec["day"], "youtube.analytics.reports", fetched, None, "verified")
        n += 1
    if last:
        _set_cursor(conn, tenant_id, row_id, "ctype_through", last)
    return n


def fetch_retention(conn, g, tenant_id, ch_id, vid, today, fetched, through):
    ret = g(ANALYTICS_API, {"ids": "channel==MINE", "startDate": BACKFILL_START, "endDate": today.isoformat(),
                            "metrics": "audienceWatchRatio,relativeRetentionPerformance",
                            "dimensions": "elapsedVideoTimeRatio", "filters": f"video=={vid}"})
    cols = [h["name"] for h in ret.get("columnHeaders", [])]
    rows = ret.get("rows", [])
    if not rows:
        return False
    conn.execute("DELETE FROM metrics WHERE tenant_id=? AND asset_id=? AND grain='retention_bucket'", (tenant_id, vid))
    for r in rows:
        rec = dict(zip(cols, r))
        key = f"ratio:{float(rec['elapsedVideoTimeRatio']):.2f}"
        for m in ("audienceWatchRatio", "relativeRetentionPerformance"):
            if m in rec:
                youtube._put_metric(conn, tenant_id, ch_id, vid, m, float(rec[m]), "ratio", "retention_bucket", key,
                                    "youtube.analytics.reports", fetched, through, "aggregate_only")
    return True


def sync_all(conn, *, client, progress=lambda p, m: None):
    """Scheduler entry: every ACTIVE YouTube account of every client brand."""
    rows = conn.execute(
        """SELECT pa.tenant_id, pa.id FROM platform_accounts pa JOIN tenants t USING (tenant_id)
           WHERE pa.platform='youtube' AND pa.state IN ('ACTIVE','SYNC_FAILED') AND t.kind='client'""").fetchall()
    if not rows:
        return {"skipped": "no active YouTube accounts yet (owner authorization pending)"}
    if not client:
        raise ConnectorError("no_client", "YouTube OAuth client file missing")
    results = {}
    for i, r in enumerate(rows):
        results[r["tenant_id"]] = sync(conn, r["tenant_id"], r["id"], client=client,
                                       progress=lambda p, m, i=i: progress(int((i + p / 100) * 100 / len(rows)), m))
    return results



AUDIENCE_REPORTS = [
    # (key, dimensions, metrics, sort)
    ("age_gender", "ageGroup,gender", "viewerPercentage", None),
    ("country", "country", "views,estimatedMinutesWatched,averageViewDuration", "-views"),
    ("device", "deviceType", "views,estimatedMinutesWatched,averageViewDuration", "-views"),
    ("subscribed", "subscribedStatus", "views,estimatedMinutesWatched,averageViewDuration", None),
]
AUDIENCE_DAYS = 90


def sync_audience(conn, g, tenant_id, ch_id, today, fetched, through):
    start = (today - timedelta(days=AUDIENCE_DAYS)).isoformat()
    done = {}
    for key, dims, metrics, sort in AUDIENCE_REPORTS:
        params = {"ids": "channel==MINE", "startDate": start, "endDate": today.isoformat(),
                  "metrics": metrics, "dimensions": dims}
        if sort:
            params.update(sort=sort, maxResults=25)
        rep = g(ANALYTICS_API, params)
        cols = [h["name"] for h in rep.get("columnHeaders", [])]
        ndim = len(dims.split(","))
        conn.execute("DELETE FROM metrics WHERE tenant_id=? AND asset_id=? AND grain='audience_90d'",
                     (tenant_id, f"aud:{key}"))
        for r in rep.get("rows", []):
            rec = dict(zip(cols, r))
            label = "|".join(str(rec[c]) for c in cols[:ndim])
            for m in cols[ndim:]:
                youtube._put_metric(conn, tenant_id, ch_id, f"aud:{key}", m, float(rec[m]), "", "audience_90d",
                                    label, "youtube.analytics.reports", fetched, through, "aggregate_only")
        done[key] = len(rep.get("rows", []))
    return done


def sync_traffic_days(conn, g, tenant_id, row_id, ch_id, today, fetched):
    cur = _cursor(conn, tenant_id, row_id, "traffic_through")
    start = (today - timedelta(days=120)) if not cur else (date.fromisoformat(cur) - timedelta(days=LAG_DAYS))
    rep = g(ANALYTICS_API, {"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": today.isoformat(),
                            "metrics": "views,estimatedMinutesWatched", "dimensions": "day,insightTrafficSourceType",
                            "sort": "day"})
    cols = [h["name"] for h in rep.get("columnHeaders", [])]
    last, n = None, 0
    for r in rep.get("rows", []):
        rec = dict(zip(cols, r))
        last = rec["day"]
        for m in ("views", "estimatedMinutesWatched"):
            youtube._put_metric(conn, tenant_id, ch_id, f"traffic:{rec['insightTrafficSourceType']}", m, float(rec[m]), "",
                                "day_traffic", rec["day"], "youtube.analytics.reports", fetched, None, "verified")
        n += 1
    if last:
        _set_cursor(conn, tenant_id, row_id, "traffic_through", last)
    return n


COHORT_PER_SYNC = 8   # videos per sync (each is one Analytics call)
COHORT_DAYS = 29      # publish day + 28


def sync_video_days(conn, g, tenant_id, ch_id, today, fetched):
    """Daily views/watch time for each video's first 29 days (grain video_day).

    Complete videos (older than 31 days with data stored) are skipped; recent
    ones are refreshed so day-1/3/7 points fill in as they happen.
    """
    rows = conn.execute("SELECT asset_id, published_at FROM assets WHERE tenant_id=? AND platform='youtube' "
                        "AND published_at IS NOT NULL ORDER BY published_at DESC", (tenant_id,)).fetchall()
    have = {r[0] for r in conn.execute("SELECT DISTINCT asset_id FROM metrics WHERE tenant_id=? AND grain='video_day'",
                                       (tenant_id,))}
    todo = [r for r in rows if r["asset_id"] not in have or
            (today - date.fromisoformat(r["published_at"][:10])).days <= COHORT_DAYS + LAG_DAYS]
    done = []
    for r in todo[:COHORT_PER_SYNC]:
        pub = date.fromisoformat(r["published_at"][:10])
        end = min(today, pub + timedelta(days=COHORT_DAYS - 1))
        rep = g(ANALYTICS_API, {"ids": "channel==MINE", "startDate": pub.isoformat(), "endDate": end.isoformat(),
                                "metrics": "views,estimatedMinutesWatched", "dimensions": "day",
                                "filters": f"video=={r['asset_id']}", "sort": "day"})
        cols = [h["name"] for h in rep.get("columnHeaders", [])]
        for row in rep.get("rows", []):
            rec = dict(zip(cols, row))
            for m in ("views", "estimatedMinutesWatched"):
                if m in rec:
                    youtube._put_metric(conn, tenant_id, ch_id, r["asset_id"], m, float(rec[m]), "", "video_day",
                                        rec["day"], "youtube.analytics.reports", fetched, None, "verified")
        done.append(r["asset_id"])
    return done
