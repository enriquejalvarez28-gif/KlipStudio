"""Spotify / Apple Podcasts: public identity discovery + authorized imports.

Neither platform offers an unrestricted analytics API to show owners, so:
  * discovery uses public identifiers only (Apple lookup id, Spotify show id,
    RSS feed) and is NEVER treated as proof of ownership (spec 15.1);
  * once the owner verifies + assigns the show, the account becomes
    IMPORT_ONLY and metrics arrive from exports the owner downloads from
    Spotify for Creators / Apple Podcasts Connect.
Imported numbers keep platform-specific metric names (plays, listeners,
engaged listeners...) and are never summed with YouTube views.
"""

import csv
import hashlib
import io
import re
from pathlib import Path

from growth_os import brands
from growth_os.db import audit, utcnow
from growth_os.http import Client

APPLE_LOOKUP = "https://itunes.apple.com/lookup"


def discover_apple(conn, tenant_id: str, apple_id: str, *, transport=None) -> str:
    data = Client(conn, tenant_id, transport=transport).request(
        "GET", APPLE_LOOKUP, params={"id": apple_id, "entity": "podcast"}, log_name="apple.lookup")
    hits = [r for r in data.get("results", []) if str(r.get("collectionId")) == str(apple_id)]
    if not hits:
        raise brands.BrandError("not_found", f"no Apple Podcasts show with id {apple_id}")
    show = hits[0]
    return brands.record_discovered(
        conn, tenant_id, "apple_podcasts", platform_account_id=str(show["collectionId"]),
        account_name=show.get("collectionName", ""), handle=show.get("feedUrl", ""),
        avatar_url=show.get("artworkUrl100", ""), connected_identity="public lookup (not proof of ownership)",
        actor="public_lookup",
    )


def discover_spotify(conn, tenant_id: str, show_url_or_id: str, *, name: str = "") -> str:
    m = re.search(r"show[/:]([A-Za-z0-9]{22})", show_url_or_id) or re.fullmatch(r"([A-Za-z0-9]{22})", show_url_or_id)
    if not m:
        raise brands.BrandError("bad_id", "expected an open.spotify.com/show/<id> URL or a 22-char show id")
    return brands.record_discovered(
        conn, tenant_id, "spotify", platform_account_id=m.group(1), account_name=name,
        connected_identity="public show id (not proof of ownership)", actor="public_lookup",
    )


def enable_import(conn, tenant_id: str, row_id: str, *, owner: str):
    """After verify + assign: analytics come only from owner-supplied exports."""
    brands.mark(conn, tenant_id, row_id, brands.IMPORT_ONLY, actor=owner)


def import_csv(conn, tenant_id: str, row_id: str, path: str | Path, *, owner: str) -> dict:
    acct = brands.get_account(conn, tenant_id, row_id)
    if acct["state"] != brands.IMPORT_ONLY:
        raise brands.BrandError("not_import_ready", "verify and assign the show, then enable import first")
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    seen = conn.execute(
        "SELECT 1 FROM audit_log WHERE tenant_id=? AND event='import.applied' AND detail_json LIKE ?",
        (tenant_id, f'%"{digest}"%')).fetchone()
    if seen:
        return {"skipped": "identical file already imported", "sha256": digest}
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    cols = reader.fieldnames or []
    date_col = next((c for c in cols if c.strip().lower() in ("date", "day")), None)
    if not date_col:
        raise brands.BrandError("bad_file", f"no Date column; columns were {cols}")
    ep_col = next((c for c in cols if c.strip().lower() in ("episode", "episode title", "title", "episode name")), None)
    platform = acct["platform"]
    fetched = utcnow()
    n = 0
    max_day = None
    for rec in reader:
        day = (rec.get(date_col) or "").strip()[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        max_day = max(max_day or day, day)
        asset = (rec.get(ep_col) or "").strip() if ep_col else acct["platform_account_id"]
        for c in cols:
            if c in (date_col, ep_col):
                continue
            v = (rec.get(c) or "").replace(",", "").strip()
            try:
                value = float(v)
            except ValueError:
                continue
            metric = re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_")
            conn.execute(
                """INSERT OR REPLACE INTO metrics (tenant_id, platform, platform_account_id, asset_id, episode_id,
                   published_at, metric_name, value, unit, grain, period_start, source, fetched_at,
                   available_through, data_quality) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tenant_id, platform, acct["platform_account_id"], asset or acct["platform_account_id"], None, None,
                 metric, value, metric, "day", day, f"import:{Path(path).name}", fetched, None, "imported"),
            )
            n += 1
    conn.execute("UPDATE metrics SET available_through=? WHERE tenant_id=? AND platform_account_id=? AND fetched_at=?",
                 (max_day, tenant_id, acct["platform_account_id"], fetched))
    conn.execute("UPDATE platform_accounts SET last_successful_sync=?, data_as_of=?, updated_at=? WHERE id=?",
                 (fetched, max_day, fetched, row_id))
    audit(conn, tenant_id, owner, "import.applied", {
        "account_row": row_id, "file": Path(path).name, "sha256": digest, "values": n, "through": max_day})
    return {"values": n, "available_through": max_day, "sha256": digest}
