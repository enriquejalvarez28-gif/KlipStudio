# Klip Growth OS — Project State

Canonical state file (spec §9). Read this + `git diff` at session start; don't re-audit the repo.
Spec: KLIP Growth OS Complete Master Spec v3 (Oct 2026).

**Current phase:** P1 code done and tested offline. **Blocked on the owner's Google OAuth consent** (live RYJ channel ID not yet proven).
**Last updated:** 2026-10-14

## P0 inventory — KEEP / EXTEND / BUILD

| Component | Where | Decision | Notes |
|---|---|---|---|
| Klip Studio website | `index.html` | KEEP | Marketing site. Unrelated to Growth OS. |
| Harvey sales agent | `harvey-agent/` | KEEP (separate) | Email prospecting for Klip. Its patterns are reused here: SQLite + append-only migrations, local dashboard, approval gate, usage logging. No code is shared, so Harvey is not destabilized. |
| YouTube integration | none in repo | BUILD | `growth-os/growth_os/connectors/youtube.py` |
| Analytics store | none | BUILD | `growth-os/data/growth_os.db` (SQLite, git-ignored) |
| Dashboard | none for analytics | BUILD | Manage Accounts screen built first. Analytics dashboard is P3. |
| RYJ production / editing agent | not in this repo | OPEN | Spec §6 says to integrate it, not duplicate it. Need its location or owner before P8. |
| Metricool connector (MCP) | account-level | KEEP / EXTEND later | Only brand is **Theklipstudio**: YouTube `UC-tWcFi3pHaBfjBGhCrFWzA`, IG `theklipstudio`, FB `928765893663614`, LinkedIn org `113270081`. That is **Klip, not RYJ**, and must not be attributed to RYJ. |
| Supermetrics connector (MCP) | account-level | not used | YouTube sources `NOT_AUTHENTICATED`. Direct OAuth is used instead (no new subscription). |
| OpusClip connector (MCP) | account-level | candidate for P8 Operator | Clip creation. Not inspected yet. |

## What exists now (`growth-os/`)

- `growth_os/db.py`: schema. Every table is tenant-scoped (§15.3). Includes the normalized `metrics` table (§2), `jobs` ledger with unique idempotency_key, `audit_log` and `usage_log`.
- `growth_os/brands.py`: Brand Manager. 13-state lifecycle (§15.2); verify requires typing back the immutable ID; blocks silent reassignment across brands; disconnect, reject and revoke pause jobs; `preflight_public_action` is the Operator gate (§15.3/15.6).
- `growth_os/vault.py`: Fernet encryption of tokens at rest. Key comes from env or a 0600 file.
- `growth_os/http.py`: stdlib client with a daily request budget, 429/5xx backoff, per-run cache and usage logging.
- `growth_os/connectors/youtube.py`: installed-app OAuth with PKCE; read-only scopes; channel discovery; identity re-check before every sync; first-sample sync (channel stats, 5 latest uploads, 28-day daily analytics, retention curve of the latest long-form video); refresh and revoke.
- `growth_os/connectors/podcast.py`: public Spotify/Apple identity (never treated as proof of ownership); IMPORT_ONLY CSV import with sha256 dedup and provenance.
- `growth_os/server.py` + `web/`: Manage Accounts UI on 127.0.0.1:8765. Brand selector, 4 tiles, diagnostics, audit log. CSRF token and local-Host check.
- `tests/test_brand_manager.py`: 10 offline tests covering §15.6 against a fake Google.

## Evidence

- `python3 -m unittest discover -s tests -t .` → 10 passed.
- Browser click-through (Playwright, fixture DB): wrong ID refused; correct ID → OWNER_VERIFIED; wrong channel rejected and hidden; ASSIGNED. No horizontal scroll at 390px.
- Real DB: brand `ryj-media` created; all 4 platforms NOT_CONNECTED.
- **Not yet proven:** a real RYJ channel ID, real metrics, data freshness. Requires owner consent.

## Blockers

1. Owner needs to create a Google Cloud OAuth **Desktop** client (free), enable YouTube Data API v3 + YouTube Analytics API, save the JSON to `growth-os/data/youtube_client.json`, then run locally and click Connect (see `growth-os/README.md`).
2. The cloud dev container's network policy blocks `itunes.apple.com`. Apple lookup has to run locally.
3. Location and owner of any existing RYJ editing/production agent (needed before P8).

## Next highest-value tasks

1. Owner connects YouTube → verify RYJ channel → Test connection → record channel ID + sample here.
2. P2: historical backfill (once) + delta cursors for the delayed-metric window; Shorts vs long-form.
3. P3: retention + transcript mapping and the visual overview/episode views.

## Decisions log

- 2026-10-14: stdlib + `cryptography` only (both already installed). No FastAPI/httpx added. Harvey is untouched.
- 2026-10-14: Shorts classification is a ≤180s duration heuristic, labelled `short_heuristic`. The API has no Shorts flag.
- 2026-10-14: subscriberCount is stored as `rounded_public` quality. Retention is `aggregate_only` and is never presented per-person.
