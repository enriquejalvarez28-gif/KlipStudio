# Testing

## Automated (offline, about 15 seconds)

```bash
cd klip-growth-os
python -m unittest discover -s tests -t .
```

Tests write only to a throwaway temp folder (`tests/__init__.py` sets `GROWTH_OS_DATA`), never to `data/`.

| Area | Tests |
|---|---|
| Brand Manager (spec §15.6) | `test_brand_manager.py`: real-channel flow, wrong channel rejected, disconnect/reconnect/revoke, expired token, identity drift, encrypted tokens, brand isolation, duplicate assignment blocked, Operator refuses a mismatched destination, podcast import |
| Scheduler | slot maths, dedup per slot and for manual runs, missed slots collapse to one run, retry → alert, lease blocks a second instance, crash recovery, background thread executes and logs |
| Persistence | database, schedules and calendar survive a reopen |
| Truth | RYJ gets zero metrics, assets, recommendations or features from the demo seed or the checks; all demo rows are `synthetic`; RYJ report says "No platform data yet" |
| Evidence | every derived recommendation has peer median, percentile and peer basis; fingerprint dedup |
| HTTP isolation | every page responds for both brands; cross-brand video, thumbnail, report, recommendation and CSV access return 404 or are empty; CSRF and Host checks |
| Trends | fixture RSS: unrelated items dropped, sources and dates kept, duplicates counted once, uncertainty label, Google Trends traffic kept |
| AI | cache hit avoids a second call, daily cap, disabled switch, token logging |
| Incremental sync | etag skip, unchanged videos skip breakdowns, title revision history, cursor with lag window, search terms |
| Reports | regeneration reused when inputs are unchanged, synthetic banner, SVG chart, embedded thumbnails, CSV, weekly period |

## Manual checks done for this release

- All 16 pages rendered in Chromium at 1366px and 390px with no JavaScript errors and no horizontal scroll (demo and RYJ).
- Episode deep dive, thumbnail lab, title lab and calendar checked visually.
- Real AI title draft generated via the app, then served from cache.
- Launcher (`start.sh`, the Linux equivalent of the `.bat`): the first run created `.venv` and the database; a second run didn't start a duplicate server.
- Jobs queued via Run now ran in the background thread; results survived a server restart.
- PDF export produced a 3-page PDF.

## Not yet verified

- The Windows `.bat` and `.ps1` launchers on a real Windows machine (written for Windows; the cloud container is Linux).
- Live Google News, Google Trends and competitor feeds (blocked by the container's network policy).
- The real YouTube OAuth pilot (needs the owner's consent).

## Check it yourself (5 minutes)

1. Double-click the shortcut. The dashboard opens without Claude.
2. Switch the brand to **Demo Studio (synthetic demo)**. Charts, filters (Episodes search/format/sort, Analytics 28d/90d/1yr) and thumbnails all work. Each page shows the synthetic banner.
3. Switch to **RYJ Media**. Every page says there's no data yet; there are no numbers anywhere.
4. Jobs & integrations → **Run now** on "Daily performance review". Watch the progress pill, then check the run in "Recent runs".
5. Close the app (`windows\Stop-Klip-Growth-OS.ps1`), start it again, and confirm the runs, reports and calendar items are still there.
