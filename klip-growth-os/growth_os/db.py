"""SQLite store for Klip Growth OS.

Every tenant-owned table carries tenant_id, and every read/write helper takes
tenant_id explicitly, so isolation happens here on the server side and not
in UI filters (spec 15.3). Migrations are append-only and tracked in
PRAGMA user_version, the same approach as harvey/state.py.
"""

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# All local state (DB, key, thumbnails, reports) lives under one folder.
DATA_DIR = Path(os.environ.get("GROWTH_OS_DATA", ROOT / "data"))
DEFAULT_DB = DATA_DIR / "growth_os.db"

MIGRATIONS = [
    """
    CREATE TABLE tenants (
        tenant_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        logo_url TEXT DEFAULT '',
        timezone TEXT NOT NULL DEFAULT 'America/New_York',
        owner TEXT NOT NULL,
        contact TEXT DEFAULT '',
        theme_json TEXT DEFAULT '{}',
        created_at TEXT NOT NULL
    );

    -- One row per (tenant, platform, discovered account). A platform account
    -- may appear under two tenants only as a candidate; assignment is unique
    -- (enforced in brands.assign with an owner-review conflict).
    CREATE TABLE platform_accounts (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
        platform TEXT NOT NULL,
        platform_account_id TEXT NOT NULL,
        account_name TEXT DEFAULT '',
        handle TEXT DEFAULT '',
        avatar_url TEXT DEFAULT '',
        connected_identity TEXT DEFAULT '',
        scopes TEXT DEFAULT '',
        scope_fingerprint TEXT DEFAULT '',
        access_level TEXT DEFAULT 'READ_ANALYTICS',
        state TEXT NOT NULL,
        verified_by TEXT,
        verified_at TEXT,
        assigned_at TEXT,
        last_successful_sync TEXT,
        data_as_of TEXT,
        last_error TEXT DEFAULT '',
        credential_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (tenant_id, platform, platform_account_id)
    );

    -- OAuth material, encrypted at rest. Bound to exactly one tenant: a
    -- token minted while connecting brand A is never usable for brand B.
    CREATE TABLE credentials (
        credential_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
        platform TEXT NOT NULL,
        ciphertext BLOB NOT NULL,
        scopes TEXT NOT NULL,
        created_at TEXT NOT NULL,
        rotated_at TEXT
    );

    -- Pending OAuth handshakes (state -> tenant + PKCE verifier).
    CREATE TABLE oauth_pending (
        state TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        verifier_ct BLOB NOT NULL,
        redirect_uri TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    -- Normalized metrics (spec section 2). Views, plays and listeners stay
    -- separate metric_names and are never summed.
    CREATE TABLE metrics (
        tenant_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        platform_account_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        episode_id TEXT,
        published_at TEXT,
        metric_name TEXT NOT NULL,
        value REAL,
        unit TEXT NOT NULL,
        grain TEXT NOT NULL,
        period_start TEXT NOT NULL,
        source TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        available_through TEXT,
        data_quality TEXT NOT NULL DEFAULT 'verified',
        PRIMARY KEY (tenant_id, platform, asset_id, metric_name, grain, period_start)
    );

    CREATE TABLE assets (
        tenant_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        platform_account_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        title TEXT,
        published_at TEXT,
        duration_s INTEGER,
        format TEXT,
        thumbnail_url TEXT,
        etag TEXT,
        fetched_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, platform, asset_id)
    );

    CREATE TABLE sync_cursors (
        tenant_id TEXT NOT NULL,
        platform_account_row TEXT NOT NULL,
        name TEXT NOT NULL,
        value TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, platform_account_row, name)
    );

    -- Job/approval ledger. idempotency_key is unique so a retried or
    -- duplicated schedule can never execute twice.
    CREATE TABLE jobs (
        job_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('analyst', 'operator')),
        kind TEXT NOT NULL,
        target_platform TEXT,
        target_account_id TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}',
        state TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        approved_by TEXT,
        approved_at TEXT,
        result_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        event TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}',
        at TEXT NOT NULL
    );

    -- Connector requests + AI usage for the diagnostics view (spec 9, 15.5).
    CREATE TABLE usage_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        run_id TEXT,
        kind TEXT NOT NULL,          -- 'api' or 'llm'
        name TEXT NOT NULL,          -- endpoint or model
        quota_units INTEGER DEFAULT 0,
        tokens_in INTEGER DEFAULT 0,
        tokens_out INTEGER DEFAULT 0,
        cache_hit INTEGER DEFAULT 0,
        status INTEGER,
        duration_ms INTEGER DEFAULT 0,
        at TEXT NOT NULL
    );
    CREATE INDEX usage_by_day ON usage_log (tenant_id, kind, at);
    """,
    # ── v2: owner app — scheduler, labs, trends, calendar, reports ──
    """
    ALTER TABLE tenants ADD COLUMN kind TEXT NOT NULL DEFAULT 'client';  -- 'client' | 'demo'

    -- What the brand is about; drives trend relevance and keyword coverage.
    CREATE TABLE tenant_topics (
        tenant_id TEXT NOT NULL, keyword TEXT NOT NULL, weight REAL NOT NULL DEFAULT 1,
        PRIMARY KEY (tenant_id, keyword)
    );
    -- Public competitor channels whose RSS feeds we read (no auth, no scraping).
    CREATE TABLE competitors (
        tenant_id TEXT NOT NULL, platform TEXT NOT NULL, ref TEXT NOT NULL, name TEXT DEFAULT '',
        PRIMARY KEY (tenant_id, platform, ref)
    );

    -- Every observed title / thumbnail / description value, so revisions and
    -- their later performance can be shown without claiming causality.
    CREATE TABLE asset_history (
        tenant_id TEXT NOT NULL, platform TEXT NOT NULL, asset_id TEXT NOT NULL,
        field TEXT NOT NULL, value TEXT, value_hash TEXT NOT NULL,
        observed_at TEXT NOT NULL, source TEXT NOT NULL,
        PRIMARY KEY (tenant_id, platform, asset_id, field, value_hash)
    );
    CREATE TABLE thumbnail_features (
        tenant_id TEXT NOT NULL, asset_id TEXT NOT NULL, image_hash TEXT NOT NULL,
        features_json TEXT NOT NULL, computed_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, asset_id, image_hash)
    );

    CREATE TABLE schedules (
        name TEXT PRIMARY KEY, kind TEXT NOT NULL, spec_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        retry_max INTEGER NOT NULL DEFAULT 3, next_run_at TEXT, last_run_at TEXT, last_success_at TEXT,
        last_status TEXT, last_error TEXT
    );
    CREATE TABLE job_runs (
        run_id TEXT PRIMARY KEY, schedule_name TEXT, kind TEXT NOT NULL, tenant_id TEXT,
        trigger TEXT NOT NULL, dedup_key TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
        attempt INTEGER NOT NULL DEFAULT 0, progress INTEGER NOT NULL DEFAULT 0, message TEXT DEFAULT '',
        queued_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, next_retry_at TEXT, result_json TEXT
    );
    CREATE INDEX job_runs_recent ON job_runs (queued_at);
    CREATE TABLE locks (name TEXT PRIMARY KEY, holder TEXT NOT NULL, expires_at TEXT NOT NULL);
    CREATE TABLE alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, level TEXT NOT NULL, source TEXT NOT NULL,
        message TEXT NOT NULL, created_at TEXT NOT NULL, acked_at TEXT
    );

    CREATE TABLE trends (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, cluster_key TEXT NOT NULL, title TEXT NOT NULL,
        url TEXT, source TEXT NOT NULL, source_type TEXT NOT NULL, published_at TEXT, fetched_at TEXT NOT NULL,
        matched_keywords TEXT DEFAULT '', score REAL, score_json TEXT DEFAULT '{}', uncertainty TEXT,
        status TEXT NOT NULL DEFAULT 'new', ai_json TEXT,
        UNIQUE (tenant_id, url)
    );
    CREATE TABLE recommendations (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, asset_id TEXT, kind TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 2, basis TEXT NOT NULL CHECK (basis IN ('measured','derived','ai')),
        title TEXT NOT NULL, detail TEXT DEFAULT '', evidence_json TEXT NOT NULL DEFAULT '[]',
        fingerprint TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL,
        UNIQUE (tenant_id, fingerprint)
    );
    CREATE TABLE calendar_items (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, day TEXT NOT NULL, title TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'episode', status TEXT NOT NULL DEFAULT 'idea', notes TEXT DEFAULT '',
        trend_id TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE reports (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, kind TEXT NOT NULL, period_start TEXT NOT NULL,
        period_end TEXT NOT NULL, title TEXT NOT NULL, html_path TEXT NOT NULL, input_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE ai_cache (
        key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, purpose TEXT NOT NULL, model TEXT NOT NULL,
        output_json TEXT NOT NULL, tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0,
        cost_usd REAL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # v3 (2026-10-15): recommendation engine v2 + action ledger (spec v4 §18, §22).
    """
    ALTER TABLE recommendations ADD COLUMN diagnosis TEXT DEFAULT '';
    ALTER TABLE recommendations ADD COLUMN hypotheses_json TEXT DEFAULT '[]';
    ALTER TABLE recommendations ADD COLUMN steps_json TEXT DEFAULT '[]';
    ALTER TABLE recommendations ADD COLUMN test_plan_json TEXT DEFAULT '{}';
    ALTER TABLE recommendations ADD COLUMN alternatives_json TEXT DEFAULT '[]';
    ALTER TABLE recommendations ADD COLUMN impact TEXT DEFAULT '';
    ALTER TABLE recommendations ADD COLUMN effort TEXT DEFAULT '';
    ALTER TABLE recommendations ADD COLUMN confidence TEXT DEFAULT '';
    ALTER TABLE recommendations ADD COLUMN workflow TEXT DEFAULT 'suggested';
    ALTER TABLE recommendations ADD COLUMN baseline_json TEXT DEFAULT '{}';
    ALTER TABLE recommendations ADD COLUMN evaluate_after TEXT;
    ALTER TABLE recommendations ADD COLUMN result_json TEXT DEFAULT '{}';
    CREATE TABLE action_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, rec_id TEXT NOT NULL,
        from_state TEXT, to_state TEXT NOT NULL, actor TEXT NOT NULL, note TEXT DEFAULT '',
        snapshot_json TEXT DEFAULT '{}', at TEXT NOT NULL
    );
    CREATE INDEX action_ledger_rec ON action_ledger (tenant_id, rec_id);
    """,
    # v4 (2026-10-15): thumbnail experiments (native Test & Compare results entered by the owner, or sequential tests).
    """
    CREATE TABLE thumb_experiments (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, asset_id TEXT NOT NULL,
        method TEXT NOT NULL CHECK (method IN ('native','sequential')), status TEXT NOT NULL DEFAULT 'planned',
        started_at TEXT, ended_at TEXT, variants_json TEXT DEFAULT '[]', result_json TEXT DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    """,
    # v5 (2026-10-15): discovery (distribution checks, manual AI-visibility samples, saved episode plans).
    """
    CREATE TABLE distribution_checks (
        tenant_id TEXT NOT NULL, platform TEXT NOT NULL, status TEXT NOT NULL, detail_json TEXT DEFAULT '{}',
        checked_at TEXT NOT NULL, PRIMARY KEY (tenant_id, platform)
    );
    CREATE TABLE ai_visibility_samples (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, sampled_on TEXT NOT NULL, engine TEXT NOT NULL,
        query TEXT NOT NULL, mentioned INTEGER NOT NULL DEFAULT 0, cited_url TEXT DEFAULT '', note TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE TABLE episode_plans (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, topic TEXT NOT NULL, guest TEXT DEFAULT '',
        plan_json TEXT NOT NULL, sources_json TEXT DEFAULT '[]', created_at TEXT NOT NULL
    );
    """,
    # v6 (2026-10-15): content types were stored as ctype:VIDEOONDEMAND (camelCase upper-cased); normalize.
    """
    UPDATE OR REPLACE metrics SET asset_id='ctype:VIDEO_ON_DEMAND' WHERE asset_id='ctype:VIDEOONDEMAND';
    UPDATE OR REPLACE metrics SET asset_id='ctype:LIVE_STREAM' WHERE asset_id='ctype:LIVESTREAM';
    """,
    # v7 (2026-10-15): read-path index (KPI, CTR, cohort and freshness queries filter by grain/metric/date).
    """
    CREATE INDEX IF NOT EXISTS metrics_by_grain ON metrics (tenant_id, grain, metric_name, period_start);
    """,
]


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:16]


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(path or os.environ.get("GROWTH_OS_DB", DEFAULT_DB))
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def get_setting(conn, key, default=None):
    import json

    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(conn, key, value):
    import json

    conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript("BEGIN;" + script + f"; PRAGMA user_version = {i}; COMMIT;")


def audit(conn, tenant_id: str, actor: str, event: str, detail: dict | None = None) -> None:
    import json

    conn.execute(
        "INSERT INTO audit_log (tenant_id, actor, event, detail_json, at) VALUES (?,?,?,?,?)",
        (tenant_id, actor, event, json.dumps(detail or {}, sort_keys=True), utcnow()),
    )
