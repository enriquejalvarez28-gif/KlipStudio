# Klip Growth OS — Project State

Canonical state file. Read this plus `git diff` at session start; don't re-audit the repo.
Specs: Master Spec v3 (Oct 2026) + Owner App & Visual Intelligence directive (Oct 2026).

**Last updated:** 2026-10-14
**Current phase:** Owner app built and tested. **The next real-data step is blocked on the owner's Google OAuth consent** for the RYJ YouTube pilot.

## Repository map — KEEP / EXTEND / BUILD

| Component | Path | Decision |
|---|---|---|
| Klip Studio website | `../index.html` | KEEP, untouched |
| Harvey sales agent | `../harvey-agent/` | KEEP, untouched. Patterns reused (SQLite migrations, `claude -p` with no tools) |
| Growth OS | `klip-growth-os/` (renamed from `growth-os/`) | BUILT, see below |
| RYJ production/editing agent | not in this repo | OPEN: location and owner needed before Operator execution |
| Metricool connector | account-level | Only brand is **Theklipstudio** (YouTube `UC-tWcFi3pHaBfjBGhCrFWzA`): Klip's, **not RYJ's**. Not used for RYJ |
| Supermetrics connector | account-level | YouTube unauthenticated; not used |

## What exists

- **Owner app**: 16 pages (home, analytics, episodes + deep dive, YouTube, Instagram, podcasts, thumbnail lab, title lab, SEO, trends, recommendations, calendar, reports, jobs and integrations, accounts, settings). Vanilla JS with no build step; SVG chart kit; dark RYJ theme and a light theme; responsive down to 390px; installable PWA.
- **Backend**: stdlib HTTP server (local only, CSRF), SQLite schema v2, Brand Manager with 13 account states, YouTube OAuth + sample + incremental sync, podcast imports, deterministic analytics, trends, reports (HTML/PDF/CSV), AI layer via Claude Code CLI.
- **Scheduler** (in-process, persistent): analytics sync every 6 h, trends 06:30, daily review 07:00, packaging check 07:15, weekly Monday 08:00, monthly on the 1st at 08:30. Dedup per slot, lease lock, retries with backoff, alerts, Run now, pause.
- **Brands**: `ryj-media` (real config only: topics, theme, no metrics) and `demo-synthetic` ("Demo Studio", every row `synthetic`, banner on every page).
- **Launchers**: `Start-Klip-Growth-OS.bat`, `windows/Install-Shortcut.ps1 [-AutoStart]`, `windows/Stop-Klip-Growth-OS.ps1`, `start.sh`.

## Evidence (2026-10-14)

- 29 automated tests pass (`docs/TESTING.md` lists the coverage).
- Screenshots of all pages at 1366px and 390px: no JavaScript errors, no horizontal scroll.
- Real AI call through the app (title alternatives), then a cache hit; usage logged (~7k tokens, $0.0023 list-price equivalent).
- Real PDF export (3 pages). Launcher first-run and second-run behaviour verified on Linux.
- Jobs ran via the background scheduler and persisted across a restart. Trend research failed honestly in the container (network policy 403) and raised an alert.

## Blockers

1. **RYJ YouTube OAuth**: owner creates the free Google Cloud desktop client and connects (README).
2. **Windows launcher not run on real Windows** (written for it; the container is Linux). Owner's first double-click is the test.
3. Trend sources (Google News, Trends, YouTube feeds) and the Apple lookup are blocked in the cloud container. They're expected to work locally, but this isn't verified.
4. Instagram needs a Meta developer app and a professional account linked to a Facebook Page.
5. Location of any existing RYJ editing agent (Operator integration).

## Next, in order

1. RYJ OAuth pilot: verify the channel ID → first sync → record the channel ID, sample and freshness here. Confirm whether impressions/CTR come back.
2. Retention ↔ transcript mapping (bounded ±90 s windows) on the episode deep dive.
3. Instagram connector (Meta Graph), same Brand Manager flow.
4. Spotify/Apple discoverability audits; feed metadata.
5. Operator: approved YouTube metadata writes (`youtube.force-ssl`, dry-run → approve → write → re-fetch → log).
6. Report refinements; secure sharing later (`docs/DEPLOYMENT.md`).

## Decisions log

- 2026-10-14: stdlib + `cryptography` + `pillow` only. No web framework. Harvey untouched.
- 2026-10-14: Shorts are classified by length (≤180 s), labelled `short_heuristic`.
- 2026-10-14: `subscriberCount` is stored as `rounded_public`; retention is `aggregate_only`.
- 2026-10-14: Synthetic demo brand added so the UI and charts can be verified without inventing RYJ data; it is isolated as `kind='demo'`.
- 2026-10-14: AI runs on the owner's Claude Code CLI (no API key and no new billing); haiku by default, cached, 25 calls/day cap.
- 2026-10-14: Trend score = 0.4 relevance + 0.3 freshness (48 h half-life) + 0.2 momentum (distinct outlets) + 0.1 novelty. Labelled heuristic.
- 2026-10-14: Packaging flag = CTR in the bottom quartile of matched peers, ≥1k impressions, ≥7 days old. Correlation is never presented as cause.
