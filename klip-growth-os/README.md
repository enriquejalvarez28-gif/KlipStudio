# Klip Growth OS

An owner-operated growth dashboard for podcasts and video brands. RYJ Media is the first client; other Klip clients are added as separate brands.
It runs on your own computer: a local web app with a background scheduler. **Claude Code isn't needed to use it.**

- Project state, decisions, blockers: [`PROJECT_STATE.md`](PROJECT_STATE.md)
- What's connected and what isn't: [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md)
- How to test: [`docs/TESTING.md`](docs/TESTING.md)
- Future cloud hosting: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)

## Open the app (Windows)

One-time setup:

1. Install **Python 3.11 or newer** from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"** in the installer.
2. Put this `klip-growth-os` folder somewhere permanent, for example `C:\Users\<you>\KlipStudio\klip-growth-os`.
3. Right-click `windows\Install-Shortcut.ps1` → **Run with PowerShell**. This creates a **Klip Growth OS** shortcut on the Desktop and in the Start Menu.
   To have scheduled jobs run whenever the computer is on, run it with auto-start instead:
   `powershell -ExecutionPolicy Bypass -File windows\Install-Shortcut.ps1 -AutoStart`

Every day after that:

- Double-click **Klip Growth OS** on the Desktop (or `Start-Klip-Growth-OS.bat`). The dashboard opens at **http://127.0.0.1:8765/**.
- The first launch takes about a minute because it installs two Python packages (`cryptography`, `pillow`) into a private `.venv`.
- Closing the browser tab doesn't stop the app; background jobs keep running. To stop it, run `windows\Stop-Klip-Growth-OS.ps1`.
- To install it as an app window, open http://127.0.0.1:8765/ in Edge or Chrome, then menu → **Apps → Install this site as an app**.

Bookmark **http://127.0.0.1:8765/**. It works whenever the app is running.

### macOS / Linux

```bash
./start.sh            # sets up .venv on first run, starts in background, opens the browser
```

### Developer commands

```bash
python -m growth_os init          # RYJ Media (+ topics) and the synthetic demo brand
python -m growth_os serve --open  # app + scheduler in the foreground
python -m growth_os status        # brands, account states, schedules
python -m growth_os run <job>     # analytics_sync | trend_research | daily_review | packaging_check | weekly_report | monthly_report
python -m unittest discover -s tests -t .
```

## Pages

| Page | What it does |
|---|---|
| Home | KPIs with 7/28/90-day change, sparklines, freshness badge, strongest and weakest content, top recommendations, opportunity radar, automation health |
| Analytics overview | Each platform on its own scale; views, plays and listeners are never added together |
| Episode intelligence | Thumbnail grid with search, format filter and sort. Each episode opens a deep dive: retention curve, traffic sources, search terms, peer comparison, title/thumbnail/SEO checks, history, AI drafts |
| YouTube | Channel KPIs, traffic sources, click vs hold scatter, format comparison, full video table |
| Instagram | Connection requirements and status (connector not built yet) |
| Podcasts | Spotify and Apple data from imported reports |
| Thumbnail lab | Measured image features vs CTR, association with CTR, videos flagged for review with the evidence, AI concept drafts |
| Title lab | Title checks, search-term coverage, length vs CTR, competitor title patterns, revision history, AI alternatives in six strategies |
| SEO & discoverability | Description, chapters, keywords, tags and captions per video |
| Trend radar | Google News, Google Trends and competitor feeds, scored transparently with source, date and uncertainty; AI episode angles; add to calendar |
| Recommendations | Each item labelled **measured**, **derived** or **ai**, with evidence; accept, dismiss or mark done |
| Content calendar | Month view of planned items next to what actually published |
| Reports | Weekly and monthly reports generate automatically; generate on demand; HTML preview, PDF and CSV |
| Jobs & integrations | Schedules, next run, last success, Run now, pause, recent runs with progress, alerts, API/AI usage and cost |
| Manage accounts | Connect, verify by typing the ID back, assign, test, disconnect, revoke, import reports |
| Settings | Brand topics, competitor channels, AI on/off and daily cap |

## Data and truth rules

- All data stays in `data/` on this computer (SQLite database, encrypted tokens, cached thumbnails, reports). `data/` is git-ignored.
- **RYJ Media shows no numbers until its accounts are connected and verified.** Nothing is estimated or filled in.
- **Demo Studio** is a *synthetic* brand for exercising the software. Every row it stores is marked `synthetic`, and every page and report for it shows a banner saying so.
- Every number carries its source and an as-of date. YouTube Analytics lags 2–3 days.
- AI output is labelled **ai**, cached, capped per day, and never presented as a measurement or a prediction.

## Connect RYJ YouTube (one time, free)

1. In <https://console.cloud.google.com/>, create a project (e.g. "Klip Growth OS").
2. **APIs & Services → Library**: enable **YouTube Data API v3** and **YouTube Analytics API**.
3. **OAuth consent screen**: External, Testing. Add the Google account that manages the RYJ channel as a test user.
4. **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON and save it as `klip-growth-os\data\youtube_client.json`.
   Never commit this file or paste it into a chat.
5. Open the app → **Manage accounts** (brand: RYJ Media) → YouTube **Connect**. In Google's chooser, pick the RYJ channel; if RYJ is a Brand Account, choose it there.
6. Check the channel name and `UC…` ID. If it's RYJ, click **Verify identity**, type the ID, then **Assign to brand** → **Test connection**.
7. After that, the 6-hourly sync backfills history and keeps it current.

Scopes are read-only (`youtube.readonly`, `yt-analytics.readonly`, plus `openid email` to show which Google login authorized it).
Write access for approved title/description changes is a separate, later step.
