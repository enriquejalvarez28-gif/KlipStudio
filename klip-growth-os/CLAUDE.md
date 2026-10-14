# Klip Growth OS — instructions for Claude Code

This folder is a self-contained project. Open it directly in Claude Code for Growth OS work.
`../harvey-agent/` (sales agent) and `../index.html` (Klip website) are separate products; don't modify them for Growth OS.

## Before coding
Read `PROJECT_STATE.md` and `git log -5` / `git diff`. Re-audit only if the state file is stale. Reuse existing modules.

## Layout
- `growth_os/db.py`: SQLite schema with append-only migrations (`PRAGMA user_version`). `DATA_DIR` comes from `GROWTH_OS_DATA` (default `./data`).
- `growth_os/brands.py`: tenants, account lifecycle, assignment conflicts, `preflight_public_action` (gate for every public write).
- `growth_os/connectors/`: `youtube.py` (OAuth + sample), `youtube_sync.py` (incremental sync), `podcast.py` (Spotify/Apple identity + CSV import).
- `growth_os/analytics.py`: deterministic KPIs, peers, thumbnail features, title checks, recommendations. No model calls.
- `growth_os/ai.py`: the only module that calls a model (`claude -p`, no tools, cached, capped, logged).
- `growth_os/trends.py`: public RSS sources and the transparent heuristic score.
- `growth_os/scheduler.py` + `jobs.py`: persistent schedules, dedup keys, lease lock, retries, alerts.
- `growth_os/reports.py`: HTML/PDF/CSV.
- `growth_os/api.py` (read models) and `server.py` (stdlib HTTP, CSRF, local-only).
- `growth_os/web/`: vanilla JS SPA (`app.js`), `charts.js`, `app.css`, PWA files. No build step.

## Rules
- Order of work: see PROJECT_STATE.md → Next.
- COST: deterministic code for collection and maths; Claude only for interpretation. Compact JSON payloads, cache by input hash, never send full transcripts or datasets. Respect `ai.daily_calls` and `GROWTH_OS_DAILY_API_REQUESTS`.
- TRUTH: every metric has a source, a `data_quality` and an as-of date. Never write metrics for a client brand except from a verified connector or an owner import. The demo brand is `kind='demo'` and every one of its rows is `synthetic`.
- SAFETY: OAuth only; tokens encrypted; tenant_id on every query; no public change without approval plus `preflight_public_action`; no scraping of private data.
- AGENTS: exactly two logical roles, Analyst (scheduled jobs) and Operator (approved actions). Integrate any existing production agent; don't duplicate it.
- Don't build client portals, billing, registration or multi-user UI yet (owner-only app).
- Tests: `python -m unittest discover -s tests -t .` must pass before committing. UI changes: screenshot at 1366px and 390px.

## Output each run
(1) what changed, (2) proof/test, (3) blocker, (4) next task, (5) token/API usage. Max 12 lines unless an error needs detail.
STOP only for Google/Meta authorization, publishing approval, or a real blocking decision. No paid upgrades.
