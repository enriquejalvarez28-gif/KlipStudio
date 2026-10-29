"""YouTube connector: one implementation, tenant-specific credentials.

Read-only scopes only (READ_ANALYTICS). WRITE_METADATA (youtube.force-ssl)
is requested later, separately, when the owner enables approved SEO writes.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from datetime import date, timedelta

from growth_os import brands, vault
from growth_os.db import new_id, utcnow
from growth_os.http import Client, HttpError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"

READ_SCOPES = " ".join([
    "openid",
    "email",  # to show which Google identity authorized; nothing else
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
])

WRITE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"  # titles, descriptions, tags, thumbnails

SHORTS_MAX_SECONDS = 180  # heuristic only: the API has no Shorts flag
SAMPLE_VIDEOS = 5


class ConnectorError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ── OAuth (installed-app loopback + PKCE) ─────────────────────────────

def begin_auth(conn, tenant_id: str, redirect_uri: str, client: dict, write: bool = False) -> str:
    brands.get_brand(conn, tenant_id)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    conn.execute(
        "INSERT INTO oauth_pending VALUES (?,?,?,?,?,?)",
        (state, tenant_id, "youtube", vault.seal({"v": verifier}), redirect_uri, utcnow()),
    )
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": READ_SCOPES + (" " + WRITE_SCOPE if write else ""),
        "access_type": "offline",
        # select_account: the owner must pick the Google identity / brand
        # channel deliberately rather than inheriting a signed-in default.
        "prompt": "consent select_account",
        "state": state,
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def finish_auth(conn, *, state: str, code: str, client: dict, http: Client | None = None,
                transport=None) -> tuple[str, list[str]]:
    """Exchange the code, store the encrypted token for the initiating tenant,
    discover channels. Returns (tenant_id, [account_row_ids]) — all unassigned."""
    pending = conn.execute("SELECT * FROM oauth_pending WHERE state=?", (state,)).fetchone()
    if not pending:
        raise ConnectorError("bad_state", "unknown or already-used OAuth state")
    conn.execute("DELETE FROM oauth_pending WHERE state=?", (state,))
    tenant_id = pending["tenant_id"]
    http = http or Client(conn, tenant_id, transport=transport)
    verifier = vault.unseal(pending["verifier_ct"])["v"]
    tok = http.request("POST", TOKEN_URL, form={
        "code": code, "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
        "redirect_uri": pending["redirect_uri"], "grant_type": "authorization_code", "code_verifier": verifier,
    }, log_name="oauth.token")
    granted = tok.get("scope", "")
    missing = {s for s in READ_SCOPES.split() if s.startswith("https://")} - set(granted.split())
    identity = _id_token_email(tok.get("id_token", ""))
    cred_id = new_id("cred_")
    conn.execute(
        "INSERT INTO credentials VALUES (?,?,?,?,?,?,?)",
        (cred_id, tenant_id, "youtube", vault.seal(_token_record(tok)), granted, utcnow(), None),
    )
    channels = _get(http, conn, tenant_id, cred_id, client, f"{DATA_API}/channels",
                    {"part": "snippet,contentDetails,statistics", "mine": "true", "maxResults": 50})
    rows = []
    for ch in channels.get("items", []):
        sn = ch.get("snippet", {})
        rows.append(brands.record_discovered(
            conn, tenant_id, "youtube",
            platform_account_id=ch["id"], account_name=sn.get("title", ""),
            handle=sn.get("customUrl", ""), avatar_url=sn.get("thumbnails", {}).get("default", {}).get("url", ""),
            connected_identity=identity, scopes=granted, credential_id=cred_id, actor="oauth",
        ))
        conn.execute("UPDATE platform_accounts SET access_level=? WHERE id=?",
                     ("WRITE_METADATA" if WRITE_SCOPE in granted.split() else "READ_ANALYTICS", rows[-1]))
        if missing:
            brands.mark(conn, tenant_id, rows[-1], brands.DISCONNECTED, actor="oauth",
                        error="consent screen did not grant: " + " ".join(sorted(missing)))
    if not rows:
        conn.execute("DELETE FROM credentials WHERE credential_id=?", (cred_id,))
        raise ConnectorError("no_channel", f"Google account {identity or '(unknown)'} has no YouTube channel")
    return tenant_id, rows


def _id_token_email(id_token: str) -> str:
    # Came straight from Google's token endpoint over TLS; only read for display.
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("email", "")
    except Exception:
        return ""


def _token_record(tok: dict, previous: dict | None = None) -> dict:
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token") or (previous or {}).get("refresh_token"),
        "expires_at": time.time() + int(tok.get("expires_in", 3600)) - 60,
    }


def _access_token(http, conn, tenant_id, cred_id, client, force=False) -> str:
    row = conn.execute("SELECT * FROM credentials WHERE credential_id=? AND tenant_id=?",
                       (cred_id, tenant_id)).fetchone()
    if not row:
        raise ConnectorError("no_credential", "no stored credential for this brand; reconnect")
    rec = vault.unseal(row["ciphertext"])
    if not force and rec["expires_at"] > time.time():
        return rec["access_token"]
    if not rec.get("refresh_token"):
        raise ConnectorError("needs_reauth", "no refresh token; reconnect")
    try:
        tok = http.request("POST", TOKEN_URL, form={
            "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
            "refresh_token": rec["refresh_token"], "grant_type": "refresh_token",
        }, log_name="oauth.refresh")
    except HttpError as e:
        if e.status in (400, 401) and isinstance(e.body, dict) and e.body.get("error") in ("invalid_grant", "unauthorized_client"):
            raise ConnectorError("needs_reauth", "refresh token expired or revoked") from None
        raise
    rec = _token_record(tok, rec)
    conn.execute("UPDATE credentials SET ciphertext=?, rotated_at=? WHERE credential_id=?",
                 (vault.seal(rec), utcnow(), cred_id))
    return rec["access_token"]


def _get(http, conn, tenant_id, cred_id, client, url, params, quota_units=1):
    for attempt in (0, 1):
        token = _access_token(http, conn, tenant_id, cred_id, client, force=attempt == 1)
        try:
            return http.request("GET", url, params=params, quota_units=quota_units,
                                headers={"Authorization": f"Bearer {token}"}, cache=True)
        except HttpError as e:
            if e.status == 401 and attempt == 0:
                continue
            if e.status == 403:
                reason = json.dumps(e.body)[:300]
                if "quotaExceeded" in reason or "rateLimitExceeded" in reason:
                    raise ConnectorError("quota", "YouTube API quota exhausted; retry after reset") from None
                raise ConnectorError("permission_limited", reason) from None
            raise


# ── Sync ──────────────────────────────────────────────────────────────

def sync_sample(conn, tenant_id: str, row_id: str, *, client: dict, transport=None, today: date | None = None):
    """First, small verification sync (spec 15.4 step 3).

    Re-checks that the token still resolves to the assigned channel, then
    stores channel stats, the 5 latest uploads, 28 days of daily channel
    analytics and the retention curve of the latest long-form upload.
    """
    acct = brands.get_account(conn, tenant_id, row_id)
    if acct["state"] not in (brands.ASSIGNED, brands.ACTIVE, brands.SYNC_FAILED, brands.PERMISSION_LIMITED):
        raise ConnectorError("not_assigned", f"account is {acct['state']}; verify and assign it first")
    run_id = new_id("run_")
    http = Client(conn, tenant_id, run_id=run_id, transport=transport)
    channel_id = acct["platform_account_id"]
    cred = acct["credential_id"]
    today = today or date.today()
    brands.mark(conn, tenant_id, row_id, brands.SYNCING)
    report = {"run_id": run_id, "channel_id": channel_id, "unavailable": []}
    try:
        chs = _get(http, conn, tenant_id, cred, client, f"{DATA_API}/channels",
                   {"part": "snippet,contentDetails,statistics", "mine": "true", "maxResults": 50})
        mine = {c["id"]: c for c in chs.get("items", [])}
        if channel_id not in mine:
            brands.mark(conn, tenant_id, row_id, brands.NEEDS_REAUTH,
                        error=f"identity mismatch: token now resolves to {sorted(mine)}")
            raise ConnectorError("identity_mismatch", "authorized channel changed; jobs paused, reconnect required")
        ch = mine[channel_id]
        fetched = utcnow()
        stats = ch.get("statistics", {})
        report["channel_title"] = ch["snippet"]["title"]
        for name, unit in (("subscriberCount", "subscribers"), ("viewCount", "views"), ("videoCount", "videos")):
            if name == "subscriberCount" and stats.get("hiddenSubscriberCount"):
                report["unavailable"].append("subscriberCount (hidden by channel)")
                continue
            if name in stats:
                _put_metric(conn, tenant_id, channel_id, channel_id, name, float(stats[name]), unit,
                            "lifetime_snapshot", today.isoformat(), "youtube.data.channels", fetched,
                            today.isoformat(), "rounded_public" if name == "subscriberCount" else "verified")

        uploads = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        videos = []
        if uploads:
            pl = _get(http, conn, tenant_id, cred, client, f"{DATA_API}/playlistItems",
                      {"part": "contentDetails", "playlistId": uploads, "maxResults": SAMPLE_VIDEOS})
            ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
            if ids:
                vs = _get(http, conn, tenant_id, cred, client, f"{DATA_API}/videos",
                          {"part": "snippet,contentDetails,statistics", "id": ",".join(ids)})
                for v in vs.get("items", []):
                    dur = parse_duration(v["contentDetails"].get("duration", ""))
                    fmt = "short_heuristic" if dur is not None and dur <= SHORTS_MAX_SECONDS else "long_form"
                    sn = v["snippet"]
                    # Sample never overwrites a known asset and stores no etag, so the
                    # full sync still records first-seen title/thumbnail history.
                    conn.execute(
                        """INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (tenant_id, "youtube", channel_id, v["id"], sn.get("title"), sn.get("publishedAt"),
                         dur, fmt, sn.get("thumbnails", {}).get("medium", {}).get("url"), None, fetched),
                    )
                    for name in ("viewCount", "likeCount", "commentCount"):
                        if name in v.get("statistics", {}):
                            _put_metric(conn, tenant_id, channel_id, v["id"], name, float(v["statistics"][name]),
                                        name.replace("Count", "s").lower(), "lifetime_snapshot", today.isoformat(),
                                        "youtube.data.videos", fetched, today.isoformat(), "verified",
                                        published_at=sn.get("publishedAt"))
                    videos.append({"id": v["id"], "title": sn.get("title"), "format": fmt, "duration_s": dur})
        report["videos"] = videos

        start = (today - timedelta(days=28)).isoformat()
        daily = _get(http, conn, tenant_id, cred, client, ANALYTICS_API, {
            "ids": "channel==MINE", "startDate": start, "endDate": today.isoformat(),
            "metrics": "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
            "dimensions": "day", "sort": "day",
        })
        cols = [h["name"] for h in daily.get("columnHeaders", [])]
        rows = daily.get("rows", [])
        units = {"views": "views", "estimatedMinutesWatched": "minutes", "averageViewDuration": "seconds",
                 "subscribersGained": "subscribers", "subscribersLost": "subscribers"}
        through = rows[-1][0] if rows else None
        for r in rows:
            rec = dict(zip(cols, r))
            for m, unit in units.items():
                if m in rec:
                    _put_metric(conn, tenant_id, channel_id, channel_id, m, float(rec[m]), unit, "day", rec["day"],
                                "youtube.analytics.reports", fetched, through, "verified")
        report["daily_rows"] = len(rows)
        report["available_through"] = through
        if not rows:
            report["unavailable"].append("daily channel analytics: no rows yet for the last 28 days")

        target = next((v for v in videos if v["format"] == "long_form"), None)
        if target:
            ret = _get(http, conn, tenant_id, cred, client, ANALYTICS_API, {
                "ids": "channel==MINE", "startDate": "2005-02-14", "endDate": today.isoformat(),
                "metrics": "audienceWatchRatio,relativeRetentionPerformance",
                "dimensions": "elapsedVideoTimeRatio", "filters": f"video=={target['id']}",
            })
            rcols = [h["name"] for h in ret.get("columnHeaders", [])]
            buckets = ret.get("rows", [])
            for r in buckets:
                rec = dict(zip(rcols, r))
                key = f"ratio:{float(rec['elapsedVideoTimeRatio']):.2f}"
                for m in ("audienceWatchRatio", "relativeRetentionPerformance"):
                    if m in rec:
                        _put_metric(conn, tenant_id, channel_id, target["id"], m, float(rec[m]), "ratio",
                                    "retention_bucket", key, "youtube.analytics.reports", fetched, through,
                                    "aggregate_only")
            report["retention"] = {"video_id": target["id"], "buckets": len(buckets)}
            if not buckets:
                report["unavailable"].append(f"retention for {target['id']}: not enough views or still processing")
        else:
            report["unavailable"].append("retention: no long-form video among the latest uploads")

        brands.mark(conn, tenant_id, row_id, brands.ACTIVE, last_successful_sync=fetched,
                    data_as_of=through or fetched[:10], last_error="")
        report["api_requests"] = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(quota_units),0) FROM usage_log WHERE run_id=? AND cache_hit=0",
            (run_id,)).fetchone()[:]
        return report
    except ConnectorError as e:
        state = {"needs_reauth": brands.NEEDS_REAUTH, "permission_limited": brands.PERMISSION_LIMITED}.get(e.code)
        acct = brands.get_account(conn, tenant_id, row_id)
        if acct["state"] == brands.SYNCING:
            brands.mark(conn, tenant_id, row_id, state or brands.SYNC_FAILED, error=f"{e.code}: {e}")
        raise
    except Exception as e:
        acct = brands.get_account(conn, tenant_id, row_id)
        if acct["state"] == brands.SYNCING:
            brands.mark(conn, tenant_id, row_id, brands.SYNC_FAILED, error=str(e)[:300])
        raise


def revoke(conn, tenant_id: str, row_id: str, *, owner: str, transport=None):
    """Revoke the token at Google, then forget it locally."""
    acct = brands.get_account(conn, tenant_id, row_id)
    cred = conn.execute("SELECT * FROM credentials WHERE credential_id=? AND tenant_id=?",
                        (acct["credential_id"], tenant_id)).fetchone()
    if cred:
        rec = vault.unseal(cred["ciphertext"])
        http = Client(conn, tenant_id, transport=transport)
        try:
            http.request("POST", REVOKE_URL, form={"token": rec.get("refresh_token") or rec["access_token"]},
                         log_name="oauth.revoke")
        except HttpError as e:
            if e.status != 400:  # 400 = already invalid; still fine to forget it
                raise
        conn.execute("DELETE FROM credentials WHERE credential_id=?", (cred["credential_id"],))
    brands.mark(conn, tenant_id, row_id, brands.REVOKED, actor=owner, credential_id=None)


def _put_metric(conn, tenant_id, account_id, asset_id, name, value, unit, grain, period_start, source,
                fetched_at, available_through, quality, published_at=None):
    conn.execute(
        """INSERT OR REPLACE INTO metrics (tenant_id, platform, platform_account_id, asset_id, episode_id,
           published_at, metric_name, value, unit, grain, period_start, source, fetched_at, available_through,
           data_quality) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tenant_id, "youtube", account_id, asset_id, None, published_at, name, value, unit, grain, period_start,
         source, fetched_at, available_through, quality),
    )


def parse_duration(iso: str) -> int | None:
    """ISO-8601 duration (PT1H2M3S) to seconds."""
    import re

    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", iso or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s
