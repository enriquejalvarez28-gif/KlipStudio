"""Brand Manager: tenants, platform-account lifecycle and assignment rules.

Lifecycle (spec 15.2):
  NOT_CONNECTED -> CONNECTING -> AUTHORIZED_UNASSIGNED -> OWNER_VERIFIED
  -> ASSIGNED -> SYNCING -> ACTIVE
plus NEEDS_REAUTH, PERMISSION_LIMITED, IMPORT_ONLY, SYNC_FAILED,
DISCONNECTED, REVOKED.

All matching and permission checks are deterministic; no model is involved
in identity or tenant routing (spec 15.5).
"""

import hashlib
import re

from growth_os.db import audit, new_id, utcnow

PLATFORMS = ("youtube", "instagram", "spotify", "apple_podcasts")

NOT_CONNECTED = "NOT_CONNECTED"
CONNECTING = "CONNECTING"
AUTHORIZED_UNASSIGNED = "AUTHORIZED_UNASSIGNED"
OWNER_VERIFIED = "OWNER_VERIFIED"
ASSIGNED = "ASSIGNED"
SYNCING = "SYNCING"
ACTIVE = "ACTIVE"
NEEDS_REAUTH = "NEEDS_REAUTH"
PERMISSION_LIMITED = "PERMISSION_LIMITED"
IMPORT_ONLY = "IMPORT_ONLY"
SYNC_FAILED = "SYNC_FAILED"
DISCONNECTED = "DISCONNECTED"
REVOKED = "REVOKED"
REJECTED = "REJECTED"  # owner said "not this account"; nothing imported

# States in which the account is bound to the tenant and may sync.
BOUND = {ASSIGNED, SYNCING, ACTIVE, SYNC_FAILED, PERMISSION_LIMITED, IMPORT_ONLY}
# States in which no analytics or publishing job may run.
PAUSED = {NEEDS_REAUTH, DISCONNECTED, REVOKED, REJECTED, AUTHORIZED_UNASSIGNED, OWNER_VERIFIED, CONNECTING}

TRANSITIONS = {
    CONNECTING: {AUTHORIZED_UNASSIGNED, DISCONNECTED},
    AUTHORIZED_UNASSIGNED: {OWNER_VERIFIED, REJECTED, DISCONNECTED, REVOKED},
    OWNER_VERIFIED: {ASSIGNED, REJECTED, DISCONNECTED, REVOKED},
    ASSIGNED: {SYNCING, NEEDS_REAUTH, DISCONNECTED, REVOKED, PERMISSION_LIMITED, IMPORT_ONLY},
    SYNCING: {ACTIVE, SYNC_FAILED, NEEDS_REAUTH, PERMISSION_LIMITED, DISCONNECTED, REVOKED},
    ACTIVE: {SYNCING, NEEDS_REAUTH, PERMISSION_LIMITED, DISCONNECTED, REVOKED},
    SYNC_FAILED: {SYNCING, NEEDS_REAUTH, DISCONNECTED, REVOKED},
    PERMISSION_LIMITED: {SYNCING, NEEDS_REAUTH, DISCONNECTED, REVOKED},
    IMPORT_ONLY: {DISCONNECTED},
    NEEDS_REAUTH: {AUTHORIZED_UNASSIGNED, DISCONNECTED, REVOKED},
    REJECTED: set(),
    DISCONNECTED: {AUTHORIZED_UNASSIGNED, IMPORT_ONLY},
    REVOKED: {AUTHORIZED_UNASSIGNED},
}


class BrandError(Exception):
    """A refused operation. code is stable for the UI and tests."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ── Tenants ───────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "brand"


def create_brand(conn, display_name: str, owner: str, *, tenant_id: str | None = None,
                 timezone: str = "America/New_York", contact: str = "", logo_url: str = "",
                 theme_json: str = "{}") -> str:
    tenant_id = tenant_id or slugify(display_name)
    if conn.execute("SELECT 1 FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone():
        raise BrandError("brand_exists", f"brand {tenant_id!r} already exists")
    conn.execute(
        "INSERT INTO tenants VALUES (?,?,?,?,?,?,?,?)",
        (tenant_id, display_name, logo_url, timezone, owner, contact, theme_json, utcnow()),
    )
    audit(conn, tenant_id, owner, "brand.created", {"display_name": display_name})
    return tenant_id


def get_brand(conn, tenant_id: str):
    row = conn.execute("SELECT * FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
    if not row:
        raise BrandError("no_brand", f"unknown brand {tenant_id!r}")
    return row


def list_brands(conn):
    return conn.execute("SELECT * FROM tenants ORDER BY created_at").fetchall()


# ── Platform accounts ─────────────────────────────────────────────────

def scope_fingerprint(scopes: str) -> str:
    return hashlib.sha256(" ".join(sorted(scopes.split())).encode()).hexdigest()[:16]


def accounts(conn, tenant_id: str, platform: str | None = None):
    sql = "SELECT * FROM platform_accounts WHERE tenant_id=?"
    args = [tenant_id]
    if platform:
        sql += " AND platform=?"
        args.append(platform)
    return conn.execute(sql + " ORDER BY created_at", args).fetchall()


def get_account(conn, tenant_id: str, row_id: str):
    """Tenant-scoped fetch: a row id from another tenant is simply not found."""
    row = conn.execute(
        "SELECT * FROM platform_accounts WHERE id=? AND tenant_id=?", (row_id, tenant_id)
    ).fetchone()
    if not row:
        raise BrandError("not_found", "account not found for this brand")
    return row


def _set_state(conn, tenant_id, row, new_state, actor, **fields):
    old = row["state"]
    if new_state != old and new_state not in TRANSITIONS.get(old, set()):
        raise BrandError("bad_transition", f"cannot go from {old} to {new_state}")
    fields["state"] = new_state
    fields["updated_at"] = utcnow()
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE platform_accounts SET {cols} WHERE id=? AND tenant_id=?",
        (*fields.values(), row["id"], tenant_id),
    )
    audit(conn, tenant_id, actor, "account.state", {
        "account_row": row["id"], "platform": row["platform"],
        "platform_account_id": row["platform_account_id"], "from": old, "to": new_state,
    })
    if new_state in PAUSED:
        pause_jobs(conn, tenant_id, row["platform"], row["platform_account_id"], reason=new_state)


def record_discovered(conn, tenant_id: str, platform: str, *, platform_account_id: str,
                      account_name: str = "", handle: str = "", avatar_url: str = "",
                      connected_identity: str = "", scopes: str = "", credential_id: str | None = None,
                      state: str = AUTHORIZED_UNASSIGNED, actor: str = "system") -> str:
    """Store an account returned by an authorization or a public lookup.

    It starts unassigned: discovery is never proof of ownership, and the
    first returned channel is never assumed to be the brand's (spec 15.1).
    """
    get_brand(conn, tenant_id)
    if platform not in PLATFORMS:
        raise BrandError("bad_platform", platform)
    existing = conn.execute(
        "SELECT * FROM platform_accounts WHERE tenant_id=? AND platform=? AND platform_account_id=?",
        (tenant_id, platform, platform_account_id),
    ).fetchone()
    now = utcnow()
    fp = scope_fingerprint(scopes)
    if existing:
        changed = existing["scope_fingerprint"] != fp
        conn.execute(
            """UPDATE platform_accounts SET account_name=?, handle=?, avatar_url=?, connected_identity=?,
               scopes=?, scope_fingerprint=?, credential_id=COALESCE(?, credential_id), last_error='',
               updated_at=? WHERE id=?""",
            (account_name, handle, avatar_url, connected_identity, scopes, fp, credential_id, now, existing["id"]),
        )
        row = get_account(conn, tenant_id, existing["id"])
        # Reconnect after reauth/disconnect/revoke: back to unassigned, so
        # the owner re-verifies. A scope change also forces re-verification.
        if row["state"] in (NEEDS_REAUTH, DISCONNECTED, REVOKED) or (changed and row["state"] in BOUND):
            if row["state"] in BOUND:
                _set_state(conn, tenant_id, row, NEEDS_REAUTH, actor)
                row = get_account(conn, tenant_id, row["id"])
            _set_state(conn, tenant_id, row, AUTHORIZED_UNASSIGNED, actor,
                       verified_by=None, verified_at=None, assigned_at=None)
        return existing["id"]
    row_id = new_id("acct_")
    conn.execute(
        """INSERT INTO platform_accounts (id, tenant_id, platform, platform_account_id, account_name, handle,
           avatar_url, connected_identity, scopes, scope_fingerprint, state, credential_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (row_id, tenant_id, platform, platform_account_id, account_name, handle, avatar_url,
         connected_identity, scopes, fp, state, credential_id, now, now),
    )
    audit(conn, tenant_id, actor, "account.discovered", {
        "account_row": row_id, "platform": platform, "platform_account_id": platform_account_id,
        "account_name": account_name, "state": state,
    })
    return row_id


def verify_identity(conn, tenant_id: str, row_id: str, *, confirmed_platform_account_id: str, owner: str):
    """Owner confirms the exact immutable ID they were shown.

    Requiring the ID back (not just a click) makes a wrong-channel
    confirmation a deliberate act rather than a misclick.
    """
    row = get_account(conn, tenant_id, row_id)
    if confirmed_platform_account_id.strip() != row["platform_account_id"]:
        audit(conn, tenant_id, owner, "account.verify_mismatch", {
            "account_row": row_id, "shown": row["platform_account_id"],
            "typed": confirmed_platform_account_id.strip(),
        })
        raise BrandError("id_mismatch", "confirmed ID does not match the discovered account")
    _set_state(conn, tenant_id, row, OWNER_VERIFIED, owner, verified_by=owner, verified_at=utcnow())


def reject(conn, tenant_id: str, row_id: str, *, owner: str):
    """Owner says this is not the brand's account. Nothing is imported and
    the credential that discovered it is dropped if nothing else uses it."""
    row = get_account(conn, tenant_id, row_id)
    _set_state(conn, tenant_id, row, REJECTED, owner)
    _drop_credential_if_unused(conn, tenant_id, row["credential_id"])
    conn.execute("DELETE FROM metrics WHERE tenant_id=? AND platform_account_id=?",
                 (tenant_id, row["platform_account_id"]))


def assignment_conflicts(conn, tenant_id: str, platform: str, platform_account_id: str):
    return conn.execute(
        f"""SELECT tenant_id, id, state FROM platform_accounts
            WHERE platform=? AND platform_account_id=? AND tenant_id<>?
            AND state IN ({",".join("?" * len(BOUND))})""",
        (platform, platform_account_id, tenant_id, *BOUND),
    ).fetchall()


def assign(conn, tenant_id: str, row_id: str, *, owner: str, override_review_id: str | None = None):
    row = get_account(conn, tenant_id, row_id)
    if row["state"] not in (OWNER_VERIFIED,):
        raise BrandError("not_verified", "owner must verify the account identity before assignment")
    conflicts = assignment_conflicts(conn, tenant_id, row["platform"], row["platform_account_id"])
    if conflicts:
        # Never silently reassign. Historical attribution stays with the
        # other brand; the owner has to disconnect it there first.
        audit(conn, tenant_id, owner, "account.assign_blocked", {
            "account_row": row_id, "platform_account_id": row["platform_account_id"],
            "already_assigned_to": [c["tenant_id"] for c in conflicts],
        })
        raise BrandError(
            "assigned_elsewhere",
            "this account is already assigned to another brand; disconnect it there first (owner review)",
        )
    # A brand holds one bound account per platform; replacing is explicit.
    current = [a for a in accounts(conn, tenant_id, row["platform"])
               if a["state"] in BOUND and a["id"] != row_id]
    if current:
        raise BrandError("slot_taken", "brand already has an assigned account on this platform; use Replace Account")
    _set_state(conn, tenant_id, row, ASSIGNED, owner, assigned_at=utcnow())


def replace_account(conn, tenant_id: str, old_row_id: str, new_row_id: str, *, owner: str):
    old = get_account(conn, tenant_id, old_row_id)
    _set_state(conn, tenant_id, old, DISCONNECTED, owner)
    assign(conn, tenant_id, new_row_id, owner=owner)


def mark(conn, tenant_id: str, row_id: str, state: str, *, actor: str = "system", error: str = "", **fields):
    row = get_account(conn, tenant_id, row_id)
    if error:
        fields["last_error"] = error[:500]
    _set_state(conn, tenant_id, row, state, actor, **fields)


def disconnect(conn, tenant_id: str, row_id: str, *, owner: str):
    """Stop syncing and delete stored tokens. History is kept for attribution."""
    row = get_account(conn, tenant_id, row_id)
    _set_state(conn, tenant_id, row, DISCONNECTED, owner, credential_id=None)
    _drop_credential_if_unused(conn, tenant_id, row["credential_id"])


def _drop_credential_if_unused(conn, tenant_id, credential_id):
    if not credential_id:
        return
    still = conn.execute(
        f"""SELECT 1 FROM platform_accounts WHERE tenant_id=? AND credential_id=?
            AND state NOT IN ('{REJECTED}','{DISCONNECTED}','{REVOKED}')""",
        (tenant_id, credential_id),
    ).fetchone()
    if not still:
        conn.execute("DELETE FROM credentials WHERE credential_id=? AND tenant_id=?", (credential_id, tenant_id))


# ── Jobs / operator preflight ─────────────────────────────────────────

def pause_jobs(conn, tenant_id, platform, platform_account_id, *, reason):
    conn.execute(
        """UPDATE jobs SET state='blocked', result_json=?, updated_at=?
           WHERE tenant_id=? AND target_platform=? AND target_account_id=?
           AND state IN ('queued','running','awaiting_approval')""",
        ('{"error_code":"account_' + reason.lower() + '"}', utcnow(), tenant_id, platform, platform_account_id),
    )


PERMISSIONS = {
    "READ_ANALYTICS": 0,
    "WRITE_METADATA": 1,
    "PUBLISH": 2,
}


def preflight_public_action(conn, *, tenant_id: str, platform: str, platform_account_id: str,
                            required_permission: str, approval: dict | None):
    """Gate for every Growth Operator public mutation (spec 15.3, 15.6).

    Refuses unless: the target account is bound to exactly this tenant, its
    state allows work, its access level covers the permission, and an
    approval exists that names this same tenant + destination account.
    Returns the account row on success.
    """
    row = conn.execute(
        "SELECT * FROM platform_accounts WHERE tenant_id=? AND platform=? AND platform_account_id=?",
        (tenant_id, platform, platform_account_id),
    ).fetchone()
    if not row or row["state"] not in (ASSIGNED, ACTIVE, SYNCING):
        raise BrandError("destination_not_bound", "destination account is not assigned and active for this brand")
    if PERMISSIONS.get(row["access_level"], -1) < PERMISSIONS[required_permission]:
        raise BrandError("insufficient_scope", f"account is {row['access_level']}; {required_permission} not authorized")
    if not approval or not approval.get("approved_by") or not approval.get("approval_timestamp"):
        raise BrandError("no_approval", "no approval record")
    if approval.get("tenant_id") != tenant_id or approval.get("platform_account_id") != platform_account_id:
        raise BrandError("destination_mismatch", "approval was given for a different brand or account")
    return row
