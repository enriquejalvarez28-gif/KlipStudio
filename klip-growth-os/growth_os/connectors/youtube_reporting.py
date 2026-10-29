"""YouTube Reporting API: thumbnail impressions + impressions CTR.

The YouTube Analytics API (v2 reports) refuses `videoThumbnailImpressions*`,
so these come from the bulk Reporting API "reach" report instead:

1. Once per channel, create a reporting job for the reach report type
   (read-only, same `yt-analytics.readonly` scope). Google then generates one
   CSV per day; the first files appear ~48 h after the job is created.
2. Every sync, list the job's reports newer than our cursor, download each
   CSV once, and store per-video daily impressions and CTR.
3. Roll the stored days up into `video_lifetime` metrics (impressions summed,
   CTR impression-weighted) so the thumbnail lab and packaging check can use
   them. The rollup only covers the days Google has delivered, and says so.

Nothing here writes to YouTube beyond creating the reporting job, which only
asks Google to prepare read-only analytics files.
"""

import csv
import io
from collections import defaultdict

from growth_os.connectors import youtube
from growth_os.connectors.youtube import ConnectorError, _access_token
from growth_os.db import utcnow
from growth_os.http import HttpError

REPORTING_API = "https://youtubereporting.googleapis.com/v1"
PREFERRED_TYPES = ("channel_reach_basic_a1", "channel_reach_combined_a1")
JOB_NAME = "Klip Growth OS reach"
SOURCE = "youtube.reporting.reach"


def _cursor(conn, tenant_id, row_id, name):
    r = conn.execute("SELECT value FROM sync_cursors WHERE tenant_id=? AND platform_account_row=? AND name=?",
                     (tenant_id, row_id, name)).fetchone()
    return r[0] if r else None


def _set_cursor(conn, tenant_id, row_id, name, value):
    conn.execute("INSERT OR REPLACE INTO sync_cursors VALUES (?,?,?,?,?)", (tenant_id, row_id, name, value, utcnow()))


def _call(http, conn, tenant_id, cred, client, method, url, *, params=None, json_body=None, raw=False):
    for attempt in (0, 1):
        token = _access_token(http, conn, tenant_id, cred, client, force=attempt == 1)
        headers = {"Authorization": f"Bearer {token}"}
        try:
            if raw:
                return http.download(url, headers=headers, log_name="youtube.reporting.download")
            return http.request(method, url, params=params, json_body=json_body, headers=headers,
                                log_name=url.split("?")[0])
        except HttpError as e:
            if e.status == 401 and attempt == 0:
                continue
            if e.status == 403:
                raise ConnectorError("permission_limited", str(e.body)[:300]) from None
            raise


def pick_report_type(types):
    ids = [t.get("id", "") for t in types]
    for want in PREFERRED_TYPES:
        if want in ids:
            return want
    reach = [i for i in ids if "reach" in i and not i.startswith("content_owner")]
    return sorted(reach)[0] if reach else None


def ensure_job(http, conn, tenant_id, row_id, cred, client, want=None, suffix=""):
    """Return (job_id, report_type_id, created_now). Reuses an existing job."""
    job_id = _cursor(conn, tenant_id, row_id, "reporting_job_id" + suffix)
    rtype = _cursor(conn, tenant_id, row_id, "reporting_report_type" + suffix)
    if job_id:
        return job_id, rtype, False
    types = _call(http, conn, tenant_id, cred, client, "GET", f"{REPORTING_API}/reportTypes").get("reportTypes", [])
    rtype = want if want and want in [t.get("id") for t in types] else (None if want else pick_report_type(types))
    if not rtype:
        raise ConnectorError("no_reach_report", "YouTube Reporting API offers no reach report for this channel")
    jobs = _call(http, conn, tenant_id, cred, client, "GET", f"{REPORTING_API}/jobs").get("jobs", [])
    existing = next((j for j in jobs if j.get("reportTypeId") == rtype), None)
    created = False
    if existing:
        job_id = existing["id"]
    else:
        job = _call(http, conn, tenant_id, cred, client, "POST", f"{REPORTING_API}/jobs",
                    json_body={"reportTypeId": rtype, "name": JOB_NAME})
        job_id, created = job["id"], True
    _set_cursor(conn, tenant_id, row_id, "reporting_job_id" + suffix, job_id)
    _set_cursor(conn, tenant_id, row_id, "reporting_report_type" + suffix, rtype)
    return job_id, rtype, created


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_reach_csv(text):
    """Aggregate a reach CSV to {(date, video_id): (impressions, ctr_fraction)}.

    Rows are split by dimensions (traffic source, device, ...); impressions add
    up and CTR is re-weighted by impressions.
    """
    rd = csv.DictReader(io.StringIO(text))
    imp_col = next((c for c in (rd.fieldnames or []) if c == "video_thumbnail_impressions"), None)
    ctr_col = next((c for c in (rd.fieldnames or []) if c == "video_thumbnail_impressions_ctr"), None)
    if not imp_col:
        return {}
    acc = defaultdict(lambda: [0.0, 0.0])  # impressions, clicks
    for row in rd:
        vid, day = row.get("video_id"), row.get("date")
        imp = _num(row.get(imp_col)) or 0.0
        if not vid or not day or imp <= 0:
            continue
        ctr = _num(row.get(ctr_col)) if ctr_col else None
        if ctr is not None and ctr > 1:  # tolerate percent-style values
            ctr /= 100
        a = acc[(f"{day[:4]}-{day[4:6]}-{day[6:8]}" if len(day) == 8 else day, vid)]
        a[0] += imp
        a[1] += imp * (ctr or 0.0)
    return {k: (imp, (clicks / imp if imp else None)) for k, (imp, clicks) in acc.items()}


def rollup(conn, tenant_id, ch_id):
    """Write video_lifetime impressions + CTR (%) from stored daily reach rows."""
    rows = conn.execute(
        """SELECT i.asset_id, SUM(i.value), SUM(i.value * COALESCE(c.value, 0)), MIN(i.period_start), MAX(i.period_start)
           FROM metrics i LEFT JOIN metrics c
             ON c.tenant_id=i.tenant_id AND c.platform=i.platform AND c.asset_id=i.asset_id
            AND c.grain=i.grain AND c.period_start=i.period_start AND c.metric_name='videoThumbnailImpressionsClickRate'
           WHERE i.tenant_id=? AND i.platform='youtube' AND i.grain='day_video'
             AND i.metric_name='videoThumbnailImpressions'
           GROUP BY i.asset_id""", (tenant_id,)).fetchall()
    fetched = utcnow()
    first = last = None
    for vid, imp, weighted, d0, d1 in rows:
        if not imp:
            continue
        first = min(first or d0, d0)
        last = max(last or d1, d1)
        youtube._put_metric(conn, tenant_id, ch_id, vid, "videoThumbnailImpressions", float(imp), "impressions",
                            "video_lifetime", "lifetime", SOURCE, fetched, d1, "verified")
        # Daily CTR is stored as a percent; the impression-weighted mean stays a percent.
        youtube._put_metric(conn, tenant_id, ch_id, vid, "videoThumbnailImpressionsClickRate",
                            round(weighted / imp, 2), "percent", "video_lifetime", "lifetime", SOURCE,
                            fetched, d1, "verified")
    return {"videos": len(rows), "window": [first, last]}


def sync(conn, http, tenant_id, row_id, *, cred, ch_id, client, max_reports=60):
    out = {"unavailable": []}
    job_id, rtype, created = ensure_job(http, conn, tenant_id, row_id, cred, client)
    out.update(job_id=job_id, report_type=rtype, job_created=created)
    after = _cursor(conn, tenant_id, row_id, "reporting_created_after")
    params = {"createdAfter": after} if after else {}
    reports, token = [], None
    while True:
        p = dict(params, **({"pageToken": token} if token else {}))
        page = _call(http, conn, tenant_id, cred, client, "GET", f"{REPORTING_API}/jobs/{job_id}/reports", params=p)
        reports += page.get("reports", [])
        token = page.get("nextPageToken")
        if not token or len(reports) >= max_reports:
            break
    done = {r[0] for r in conn.execute(
        "SELECT value FROM asset_history WHERE tenant_id=? AND platform='youtube' AND asset_id=? AND field='reach_report'",
        (tenant_id, job_id))}
    reports.sort(key=lambda r: r.get("startTime", ""))
    fetched = utcnow()
    new = 0
    for rep in reports[:max_reports]:
        if rep["id"] in done or not rep.get("downloadUrl"):
            continue
        raw = _call(http, conn, tenant_id, cred, client, "GET", rep["downloadUrl"], raw=True)
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        for (day, vid), (imp, ctr) in parse_reach_csv(text).items():
            youtube._put_metric(conn, tenant_id, ch_id, vid, "videoThumbnailImpressions", imp, "impressions",
                                "day_video", day, SOURCE, fetched, day, "verified")
            if ctr is not None:
                youtube._put_metric(conn, tenant_id, ch_id, vid, "videoThumbnailImpressionsClickRate",
                                    round(ctr * 100, 4), "percent", "day_video", day, SOURCE, fetched, day, "verified")
        conn.execute("INSERT OR IGNORE INTO asset_history VALUES (?,?,?,?,?,?,?,?)",
                     (tenant_id, "youtube", job_id, "reach_report", rep["id"], rep["id"][:16], fetched, SOURCE))
        new += 1
        if rep.get("createTime"):
            _set_cursor(conn, tenant_id, row_id, "reporting_created_after", rep["createTime"])
    out["reports_downloaded"] = new
    out["rollup"] = rollup(conn, tenant_id, ch_id)
    if not reports:
        out["unavailable"].append(
            "impressions/CTR: reach reporting job is set up; Google delivers the first daily files ~48 h after creation")
    return out


# ── Impressions + CTR by traffic source (combined reach report) ───────

COMBINED = "channel_reach_combined_a1"
SRC_GRAIN = "day_video_src"


def parse_reach_by_source(text):
    """{(date, video_id, traffic_source): (impressions, clicks)} from a combined reach CSV."""
    rd = csv.DictReader(io.StringIO(text))
    cols = rd.fieldnames or []
    if "video_thumbnail_impressions" not in cols or "traffic_source_type" not in cols:
        return {}
    acc = defaultdict(lambda: [0.0, 0.0])
    for row in rd:
        vid, day, src = row.get("video_id"), row.get("date"), row.get("traffic_source_type") or "UNKNOWN"
        imp = _num(row.get("video_thumbnail_impressions")) or 0.0
        if not vid or not day or imp <= 0:
            continue
        ctr = _num(row.get("video_thumbnail_impressions_ctr")) or 0.0
        if ctr > 1:
            ctr /= 100
        a = acc[(f"{day[:4]}-{day[4:6]}-{day[6:8]}" if len(day) == 8 else day, vid, src)]
        a[0] += imp
        a[1] += imp * ctr
    return dict(acc)


def sync_by_source(conn, http, tenant_id, row_id, *, cred, ch_id, client, max_reports=30):
    job_id, rtype, created = ensure_job(http, conn, tenant_id, row_id, cred, client, want=COMBINED, suffix="_combined")
    if not job_id:
        return {"unavailable": "combined reach report not offered for this channel"}
    after = _cursor(conn, tenant_id, row_id, "reporting_created_after_combined")
    reports = _call(http, conn, tenant_id, cred, client, "GET", f"{REPORTING_API}/jobs/{job_id}/reports",
                    params={"createdAfter": after} if after else {}).get("reports", [])
    done = {r[0] for r in conn.execute("SELECT value FROM asset_history WHERE tenant_id=? AND platform='youtube' "
                                       "AND asset_id=? AND field='reach_report'", (tenant_id, job_id))}
    fetched, new = utcnow(), 0
    for rep in sorted(reports, key=lambda r: r.get("startTime", ""))[:max_reports]:
        if rep["id"] in done or not rep.get("downloadUrl"):
            continue
        raw = _call(http, conn, tenant_id, cred, client, "GET", rep["downloadUrl"], raw=True)
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        for (day, vid, src), (imp, clicks) in parse_reach_by_source(text).items():
            youtube._put_metric(conn, tenant_id, ch_id, vid, "videoThumbnailImpressions", imp, "impressions",
                                SRC_GRAIN, f"{day}|{src}", SOURCE, fetched, day, "verified")
            youtube._put_metric(conn, tenant_id, ch_id, vid, "clicks", clicks, "clicks", SRC_GRAIN, f"{day}|{src}",
                                SOURCE, fetched, day, "verified")
        conn.execute("INSERT OR IGNORE INTO asset_history VALUES (?,?,?,?,?,?,?,?)",
                     (tenant_id, "youtube", job_id, "reach_report", rep["id"], rep["id"][:16], fetched, SOURCE))
        new += 1
        if rep.get("createTime"):
            _set_cursor(conn, tenant_id, row_id, "reporting_created_after_combined", rep["createTime"])
    return {"job_id": job_id, "job_created": created, "reports_downloaded": new}
