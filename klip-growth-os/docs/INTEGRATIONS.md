# Integration status

Updated 2026-10-14. **Live** means verified against the real service with real data. Nothing here is marked live on the strength of tests alone.

| Integration | Status | Proof so far | What unblocks it |
|---|---|---|---|
| YouTube Data + Analytics API (RYJ) | **Built, not live.** Awaiting owner OAuth. | Offline tests against a simulated Google API: OAuth + PKCE, channel discovery, typed-ID verification, assignment conflicts, sample sync, incremental sync (etag skip, lag window, title history), refresh expiry → NEEDS_REAUTH, identity drift → paused, revoke. | Owner creates a free Google Cloud desktop OAuth client, saves `data/youtube_client.json`, clicks Connect and verifies the RYJ `UC…` ID (README → Connect RYJ YouTube). |
| YouTube impressions / CTR | Requested in the sync; not yet confirmed on the real API | The sync asks for `videoThumbnailImpressions` and `videoThumbnailImpressionsClickRate`. If YouTube rejects them, the run records "impressions/CTR not returned" and continues. | The first real sync shows whether these are returned for RYJ. |
| Instagram (Meta Graph API) | **Not built.** UI page explains requirements. | — | Instagram professional account linked to a Facebook Page, a Meta developer app, and owner authorization. |
| Spotify for Creators | **Import only** (no public analytics API) | CSV import tested: maps to the verified show, sha256 dedup, provenance in the audit log. | Owner verifies the show ID, then imports exports. |
| Apple Podcasts Connect | **Import only** | Same import path as Spotify. Public lookup via `itunes.apple.com` (blocked in the cloud dev container, works locally). | Owner enters the show ID, verifies it, imports exports. |
| Google News RSS | Built; **live status unknown** | Parser and scoring tested with fixtures. The cloud dev container's network policy blocks `news.google.com`, so it couldn't be verified here. | Runs on the owner's computer; the first daily run shows the result on the Jobs page. |
| Google Trends trending RSS | Built; **live status unknown** | Same as above (`trends.google.com` blocked in the container). | Same. |
| Competitor YouTube channel feeds (public RSS) | Built; **live status unknown** | Parser tested. | Add competitor channel IDs in Settings. |
| Claude Code CLI (AI drafts) | **Live** | Real call made from the app: six title alternatives for a demo video, cached on the second call, usage and tokens logged. | Needs `claude` on PATH and signed in on the owner's computer. If missing, AI drafts switch off and everything else works. |
| PDF export (Edge/Chrome headless) | **Live** in the container (Chromium) | Real 3-page PDF generated from a saved report. | On Windows it uses Edge or Chrome automatically; if neither is found, use Print → Save as PDF. |
| Metricool / Supermetrics (account connectors) | Not used | Metricool's only brand is Klip Studio (YouTube `UC-tWcFi3pHaBfjBGhCrFWzA`), **not RYJ**. Supermetrics' YouTube source is unauthenticated. | — |
| YouTube writes (title/description/thumbnail) | **Not enabled** | `preflight_public_action` gate built and tested (tenant + destination + scope + approval). | Owner approval to request the `youtube.force-ssl` scope; Operator execution comes after the RYJ pilot. |
| YouTube "Test & Compare" (thumbnail A/B) | Not available through the API | Thumbnail lab links the workflow to YouTube Studio. | — |

Never shown as data: guessed numbers, combined "audience" totals across platforms, and predicted CTR or virality.
