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
DEFAULT_DB = ROOT / "data" / "growth_os.db"

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
