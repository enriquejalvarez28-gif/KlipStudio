# Klip Growth OS — Project State

Canonical state file. Read this plus `git diff` at session start; don't re-audit the repo.
Specs: Master Spec v3 (Oct 2026) + Owner App & Visual Intelligence directive (Oct 2026).

**Last updated:** 2026-10-14
**Current phase:** RYJ YouTube is LIVE on the owner's PC (channel `UCPqVudVSoLHqVV834Mg6JhA`, Respect Your Journey, @respectyourjourney). First full sync 2026-10-15: 55 videos, daily history through 2026-10-12, per-video lifetime metrics, traffic sources, search terms.

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

## Live setup (2026-10-15)

- App runs on the owner's Windows PC from `C:\Users\enriq\Documents\KlipStudio\klip-growth-os` (desktop shortcut + auto-start at sign-in). Windows launcher verified on real Windows.
- Google Cloud project `ryj-media-analytics` (OAuth client "Klip Growth OS (PC)", Testing mode). Owners: jumpshotgope@gmail.com and enriquejalvarez28@gmail.com (owner wants Enrique as the controlling owner). Test users: both.
- Channel lives on jumpshotgope@gmail.com (personal account, not a Brand Account). Plan: move to a Brand Account with Enrique as Owner, then reconnect with Enrique's login.
- Enabled APIs: YouTube Data v3, YouTube Analytics, YouTube Reporting.
- Impressions/CTR: Analytics API returns HTTP 400 for `videoThumbnailImpressions*`. Now sourced from the Reporting API reach report (`connectors/youtube_reporting.py`): one job per channel, daily CSVs downloaded once, impression-weighted CTR rolled up to `video_lifetime`. Google starts delivering files ~48 h after job creation, so the window starts then.
- Owner rule: read-only. Never change titles, thumbnails, posts or Instagram designs; give suggestions with evidence only. Jamar runs his own bots on the channel/IG; don't interfere.

## Blockers

1. Instagram: RYJ IG is linked to Jamar's Facebook. Waiting for Jamar to add Enrique to the Page/IG in Meta Business Suite; then a Meta app under Enrique's account.
3. Trend sources (Google News, Trends, YouTube feeds) and the Apple lookup are blocked in the cloud container. They're expected to work locally, but this isn't verified.
4. Instagram needs a Meta developer app and a professional account linked to a Facebook Page.
5. Location of any existing RYJ editing agent (Operator integration).

## Next, in order

1. Confirm the reach reporting job delivers CSVs (~48 h) and the thumbnail lab fills in.
2. Retention ↔ transcript mapping (bounded ±90 s windows) on the episode deep dive.
3. Instagram connector (Meta Graph), same Brand Manager flow.
4. Spotify/Apple discoverability audits; feed metadata.
5. Operator: approved YouTube metadata writes (`youtube.force-ssl`, dry-run → approve → write → re-fetch → log).
6. Report refinements; secure sharing later (`docs/DEPLOYMENT.md`).

## Spec v4 progress (2026-10-15)

- Done: self-update (code watcher relaunches the app; Restart app button), retention explorer (drop/replay/weak/strong markers, peer median overlay, YouTube deep links), recommendation engine v2 (diagnosis classes, evidence, hypotheses, steps, test plan, daily cap 5, dedup) with approval workflow + action_ledger (migration v3), home 5 KPI cards, Shorts vs long-form table, subscribers by video, weekly traffic sources over time, audience (age/gender/country/device/subscribed), monetization tracker.
- Pending: transcript mapping (needs local transcripts; caption download needs a write-class scope), episode cohort comparison (first 7/28 days), CTR x impressions scatter + thumbnail gallery once reach CSVs land, PDF report refresh, Instagram (Meta access), Operator writes (off until approved), secure share links (needs hosted auth; PDF export is the sharing path now).
- Owner action still needed: one manual restart via Desktop "Klip Growth OS - restart" so the self-update code loads.

## Spec v5 progress (2026-10-15)
- Recommendation cards: "Prepare assets" (3 titles search/curiosity/hybrid via cached ai.ask or rule-based drafts, 2 RYJ thumbnail previews, SEO first lines + transcript chapters) → PREVIEW_READY. v5 state labels (ANALYZED…OUTCOME_REVIEWED, BLOCKED, FAILED), 7/14/28-day checkpoints, cap 3 new/day. (`prep.py`, `analytics.py`)
- YouTube page: source freshness strip, daily Shorts vs long-form views + watch hours, launch cohorts day 1/3/7/28 (new sync step, grain `video_day`, 8 videos/sync).
- Transcripts: drop YouTube Studio .srt/.vtt in `data/transcripts/<video_id>.srt`; retention markers show the ±30–60 s excerpt.
- Discovery page (`discovery.py`, migration v5): distribution statuses (iTunes Search + RSS), keyword workspace (observed search terms, no volumes), manual AI-visibility log, competitor library, episode planner (cited trend-radar sources; AI optional).
- Operator dry run: refuses wrong channel or unapproved card; BLOCKED "awaiting authorization" without youtube.force-ssl. Weekly report: approved actions + outcomes, 3 proposed changes.

## Decisions log

- 2026-10-15: Impressions/CTR come from the YouTube Reporting API reach report, not the Analytics API (which rejects them). Network timeouts are retried as 504; a failing per-video breakdown no longer fails the sync.

- 2026-10-14: stdlib + `cryptography` + `pillow` only. No web framework. Harvey untouched.
- 2026-10-14: Shorts are classified by length (≤180 s), labelled `short_heuristic`.
- 2026-10-14: `subscriberCount` is stored as `rounded_public`; retention is `aggregate_only`.
- 2026-10-14: Synthetic demo brand added so the UI and charts can be verified without inventing RYJ data; it is isolated as `kind='demo'`.
- 2026-10-14: AI runs on the owner's Claude Code CLI (no API key and no new billing); haiku by default, cached, 25 calls/day cap.
- 2026-10-14: Trend score = 0.4 relevance + 0.3 freshness (48 h half-life) + 0.2 momentum (distinct outlets) + 0.1 novelty. Labelled heuristic.
- 2026-10-14: Packaging flag = CTR in the bottom quartile of matched peers, ≥1k impressions, ≥7 days old. Correlation is never presented as cause.
