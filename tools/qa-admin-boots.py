#!/usr/bin/env python3
"""
KLIP — check that /admin actually starts.

qa-admin-keys.py checks what the editor would *save*. It cannot tell you
whether the editor runs at all. Those are different failures, and the
second one is worse: a config Sveltia refuses leaves /admin showing

    There is an error in the CMS configuration.

and nobody can change a word on the site until someone edits YAML by hand
— which is the one thing /admin exists to avoid.

That is not hypothetical. A folder collection was once pasted into
another collection's `files:` list, where every entry must name a `file:`.
The site built fine, every page rendered, every key check passed, and the
editor was dead.

    python3 tools/qa-admin-boots.py

Starts a local server, opens /admin in a real browser, and fails if the
config error appears or the sign-in screen never does.
"""
import os
import subprocess
import sys
import threading
import http.server
import socketserver
import functools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8911

# What a working editor shows before anyone signs in. Sveltia offers an
# access-token path as well as GitHub, so KLIP needs no OAuth service.
WANT = 'Sign In'
BAD = 'error in the CMS configuration'


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=ROOT)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(('127.0.0.1', PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('playwright is not installed; skipping the boot check.')
        return 0

    httpd = serve()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            errors = []
            pg.on('pageerror', lambda e: errors.append(str(e)[:200]))
            pg.goto('http://127.0.0.1:%d/admin/' % PORT, wait_until='load')
            pg.wait_for_timeout(5000)
            text = pg.evaluate('() => document.body.innerText')
            b.close()
    finally:
        httpd.shutdown()

    print('/admin reported:\n  ' + '\n  '.join(
        l for l in text.splitlines() if l.strip())[:600])
    print()

    fails = []
    if BAD in text:
        fails.append('Sveltia refused the config — /admin cannot be used')
    if WANT not in text:
        fails.append('no sign-in option appeared')
    for e in errors[:3]:
        fails.append('javascript error: %s' % e)

    if fails:
        print('FAILURES: %d' % len(fails))
        for f in fails:
            print('  - %s' % f)
        return 1
    print('/admin starts and offers sign-in. 0 failures.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
