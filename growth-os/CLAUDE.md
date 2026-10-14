# Klip Growth OS — operating prompt (spec §10)

ROLE: Implement Klip Growth OS for RYJ first; reusable for Klip clients. Act, test and report. Do not endlessly plan.

BEFORE CODING: Read `../docs/PROJECT_STATE.md`, recent git diff and the current phase. Inventory only if state is missing or stale. Reuse existing work. `../harvey-agent/` is a separate product; don't modify it for Growth OS.

ORDER: YouTube OAuth → verified historical metrics → retention + transcript mapping → visual dashboard → Analyst → Instagram → permitted Spotify/Apple reporting → SEO/trends → approved Operator → secure sharing.

COST: Never paste full transcripts, history or raw analytics into LLM prompts. Use deterministic calculations, caching, changed-record IDs, short context windows and compact JSON. Enforce configured daily token/API budgets (`GROWTH_OS_DAILY_API_REQUESTS`, `usage_log`).

AGENTS: Exactly two logical roles, Analyst and Operator (`jobs.role`). Integrate any existing production agent instead of duplicating it.

SAFETY: OAuth only; no passwords in prompts. No public content modifications without approval; every one passes `brands.preflight_public_action`. No unauthorized scraping. Isolate clients (tenant_id on every query) and protect share links.

TRUTH: Every metric has a source and an as-of timestamp; report unavailable metrics and lag. Never mark work complete without verification.

OUTPUT EACH RUN: (1) what changed, (2) proof/test, (3) blocker if any, (4) next highest-value task, (5) token/API usage. Max 12 lines unless an error needs details.

STOP only for required Google/Meta account authorization, approval to publish, or a real blocking decision. No paid upgrades.
