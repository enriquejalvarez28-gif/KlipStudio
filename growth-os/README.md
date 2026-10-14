# Klip Growth OS

Multi-brand growth OS. RYJ Media is the first tenant; Klip clients onboard through the same Brand Manager.
State, decisions and blockers: [`../docs/PROJECT_STATE.md`](../docs/PROJECT_STATE.md).

Dependencies: Python 3.11+ and `cryptography`. Nothing else.

```bash
cd growth-os
python3 -m growth_os init            # creates the RYJ Media brand
python3 -m growth_os serve           # Manage Accounts → http://127.0.0.1:8765
python3 -m growth_os status
python3 -m unittest discover -s tests -t .
```

## Connect RYJ YouTube (one time, free)

1. In <https://console.cloud.google.com/>, create a project (e.g. "Klip Growth OS").
2. **APIs & Services → Library**: enable **YouTube Data API v3** and **YouTube Analytics API**.
3. **OAuth consent screen**: External, Testing. Add the Google account that manages the RYJ channel as a test user.
4. **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON to `growth-os/data/youtube_client.json`.
   This file is git-ignored. Never commit it or paste it into chat.
5. Run `python3 -m growth_os serve` **on your own computer**, open http://127.0.0.1:8765 and click **Connect** on the YouTube tile.
   Google's account chooser opens. If RYJ is a Brand Account, choose the RYJ channel there.
6. Back in the app, Google returns the channel(s). Check the name and the `UC…` ID. If it's RYJ, click **Verify identity** and type the ID; if not, click **Not this account**.
7. Click **Assign to brand**, then **Test connection**. This runs a small sample sync (about 6 API requests) and shows what is unavailable.

The app requests read-only scopes only (`youtube.readonly`, `yt-analytics.readonly`, plus `openid email` to show which Google login authorized it).
Write scopes for approved SEO changes are requested separately, later.

## Spotify / Apple Podcasts

Neither platform has an open analytics API. Find the show from its public ID (a match is **not** proof of ownership), verify it, assign it, then **Enable import**.
After that, bring in exports from Spotify for Creators or Apple Podcasts Connect:

```bash
python3 -m growth_os import ryj-media <account_row> spotify_export.csv
```

The CSV needs a `Date` column (YYYY-MM-DD). Numeric columns become platform-specific metrics. The same file is never imported twice.

## Safety model

- Tokens are encrypted at rest (`data/.secret.key` or `GROWTH_OS_SECRET_KEY`) and bound to the brand that authorized them.
- An account is never assigned to two brands at once. Attempts are blocked and logged in the audit log.
- Every public action has to pass `brands.preflight_public_action`: same tenant, same destination account, enough scope, and an approval record.
- Disconnect, revoke, reauth or identity drift pauses all jobs for that account.
