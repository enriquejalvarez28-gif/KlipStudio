"""Scheduler job handlers. Each takes (conn, tenant_id|None, progress)."""

from growth_os import analytics, autopilot, concepts, reports, trends, vault
from growth_os.connectors import youtube_sync


def _tenants(conn, tenant_id, include_demo=True):
    if tenant_id:
        return [tenant_id]
    kinds = ("client", "demo") if include_demo else ("client",)
    return [r[0] for r in conn.execute(
        f"SELECT tenant_id FROM tenants WHERE kind IN ({','.join('?' * len(kinds))}) ORDER BY created_at", kinds)]


def analytics_sync(conn, tenant_id, progress):
    return youtube_sync.sync_all(conn, client=vault.load_client("youtube"), progress=progress)


def trend_research(conn, tenant_id, progress):
    out = {}
    ts = _tenants(conn, tenant_id)
    for i, t in enumerate(ts):
        progress(100 * i // max(len(ts), 1), f"researching {t}")
        out[t] = trends.research(conn, t)
    attempted = [r for r in out.values() if "errors" in r]
    if attempted and all(r["errors"] and not r["items_seen"] for r in attempted):
        raise RuntimeError("every trend source failed: " + "; ".join(attempted[0]["errors"])[:400])
    return out


def daily_review(conn, tenant_id, progress):
    out = {}
    for t in _tenants(conn, tenant_id):
        out[t] = analytics.daily_review(conn, t)
        out[t]["growth_review"] = analytics.growth_review(conn, t)
    return out


def packaging_check(conn, tenant_id, progress):
    return {t: {"new_recommendations": analytics.packaging_check(conn, t)} for t in _tenants(conn, tenant_id)}


def autopilot_daily(conn, tenant_id, progress):
    out = {}
    for t in _tenants(conn, tenant_id, include_demo=False):
        out[t] = autopilot.daily_run(conn, t)
        out[t]["thumbnail_concepts_for"] = concepts.for_new_episodes(conn, t)  # proposals only
    return out


def clean_tags(conn, tenant_id, progress):
    return {t: autopilot.clean_batch_tags(conn, t, since="2026-10-29T14:00", actor="owner (fix of approved batch 2026-10-29)",
                                          progress=progress)
            for t in ([tenant_id] if tenant_id else ["ryj-media"])}


def fill_missing(conn, tenant_id, progress):
    return {t: autopilot.fill_missing(conn, t, actor="owner (approved in chat 2026-10-29)", progress=progress)
            for t in _tenants(conn, tenant_id, include_demo=False)}


def _report(kind):
    def run(conn, tenant_id, progress):
        return {t: reports.generate(conn, t, kind) for t in _tenants(conn, tenant_id)}
    return run


REGISTRY = {
    "analytics_sync": analytics_sync,
    "trend_research": trend_research,
    "daily_review": daily_review,
    "packaging_check": packaging_check,
    "autopilot_daily": autopilot_daily,
    "fill_missing": fill_missing,
    "clean_tags": clean_tags,
    "weekly_report": _report("weekly"),
    "monthly_report": _report("monthly"),
}
