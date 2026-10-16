"""Page-load health check for the running app (stdlib only).

Times every read endpoint the dashboard pages call. A page goes blank when one
of its calls errors or hangs, so this fails on any non-200 or any call slower
than the budget (default 3 s). Read-only: GET requests on 127.0.0.1 only.

    python tools/healthcheck.py                 # brand ryj-media, port 8765
    python tools/healthcheck.py --brand demo-synthetic --budget 2
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PAGES = {  # endpoint → dashboard page(s) that need it
    "home": "Home", "overview?days=90": "Analytics / YouTube", "videos": "Episodes / YouTube",
    "audience": "YouTube", "cohorts": "YouTube", "accounts": "YouTube / Accounts", "monetization": "Monetization",
    "discovery": "Discovery", "recommendations": "Recommendations", "thumbnails": "Thumbnail lab",
    "titles": "Title lab", "seo": "SEO", "trends": "Trend radar", "calendar": "Calendar", "reports": "Reports",
    "podcasts": "Podcasts", "settings": "Settings", "experiments": "Thumbnail lab",
}


def get(url, timeout):
    t = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
            return r.status, time.monotonic() - t, body
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t, e.read()
    except Exception as e:  # timeout / refused
        return 0, time.monotonic() - t, str(e).encode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", default="ryj-media")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--budget", type=float, default=3.0)
    a = ap.parse_args()
    base = f"http://127.0.0.1:{a.port}/api"
    st, _, _ = get(f"{base}/app", 5)
    if st != 200:
        print(f"App not reachable on port {a.port} (status {st}). Start it with Start-Klip-Growth-OS.bat or RESTART.cmd.")
        return 2
    bad = 0
    ep = list(PAGES)
    st, _, body = get(f"{base}/t/{a.brand}/videos", 30)
    if st == 200:
        vids = json.loads(body or b"[]")
        if vids:
            ep.append(f"video/{vids[0]['asset_id']}")
            PAGES[ep[-1]] = "Episode page"
    for e in ep:
        st, dt, body = get(f"{base}/t/{a.brand}/{e}", max(30, a.budget * 4))
        flag = "OK  " if st == 200 and dt <= a.budget else "SLOW" if st == 200 else "FAIL"
        bad += flag != "OK  "
        extra = "" if st == 200 else f"  {body[:160].decode('utf-8', 'replace')}"
        print(f"{flag} {dt:6.2f}s  {st}  {e:<28} {PAGES.get(e, '')}{extra}")
    print(f"\n{len(ep) - bad}/{len(ep)} endpoints healthy (budget {a.budget:.1f}s).")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
