#!/usr/bin/env python3
"""
KLIP — sweep every built page for the faults that survive a good build.

    python3 tools/qa-pages.py

Opens each page at phone and desktop width and reports: failed requests,
JavaScript errors, horizontal overflow, missing title / description /
canonical, the wrong number of <h1>s, images with no alt text, links that
go nowhere, and placeholder text left in the HTML.

Two notes on reading its output, both learned the hard way.

The specials popup is dismissed by CLICKING its close button, never by
removing the element. An earlier version deleted the node; the popup is
scroll-triggered, so scrolling to the foot of the page then ran its open
handler against a node that was gone and threw. That produced a tidy,
convincing "JavaScript error on all 12 pages" that existed only inside
the test. A check that breaks the page to inspect it reports its own
damage.

`href="#"` is not automatically a dead link. #booking-fallback starts
that way and JS writes the real booking URL into it when the modal
opens, and work tiles carrying data-video open the player instead of
navigating. The ones worth fixing are cards and buttons that look
clickable and do nothing — six amenity cards on the Studio page were
exactly that, which is why this file exists. So treat this list as
suspects, and confirm each one before changing anything.
"""
import glob
import os
import sys
import threading
import http.server
import socketserver
import functools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8912
# a 404 page is deliberately not canonical
ALLOW_NO_CANONICAL = {'404.html'}


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=ROOT)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(('127.0.0.1', PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


META = """() => ({
  t: document.title,
  d: (document.querySelector('meta[name=description]') || {}).content || '',
  c: (document.querySelector('link[rel=canonical]') || {}).href || '',
  h1: document.querySelectorAll('h1').length,
  noAlt: [...document.querySelectorAll('img')].filter(i => !i.alt).length,
  dead: [...document.querySelectorAll('a[href="#"], a[href=""]')]
          .filter(a => !a.hasAttribute('data-video') && a.id !== 'booking-fallback')
          .length
})"""


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('playwright is not installed; skipping.')
        return 0

    pages = sorted(os.path.basename(p)
                   for p in glob.glob(os.path.join(ROOT, '*.html')))
    issues = []
    httpd = serve()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            for w, h, tag in ((390, 844, 'phone'), (1440, 900, 'desktop')):
                pg = b.new_page(viewport={'width': w, 'height': h})
                for name in pages:
                    bad, errs = [], []
                    pg.on('response', lambda r, bad=bad:
                          bad.append((r.status, r.url.split('/')[-1]))
                          if r.status >= 400 else None)
                    pg.on('pageerror', lambda e, errs=errs:
                          errs.append(str(e)[:120]))
                    pg.goto('http://127.0.0.1:%d/%s' % (PORT, name),
                            wait_until='load')
                    pg.wait_for_timeout(700)
                    close = pg.locator('#sp-close')
                    if close.count():
                        try:
                            close.click(timeout=2000)
                        except Exception:
                            pass
                    pg.evaluate('() => window.scrollTo(0, document.body.scrollHeight)')
                    pg.wait_for_timeout(500)
                    if pg.evaluate('() => document.documentElement.scrollWidth'
                                   ' > document.documentElement.clientWidth + 1'):
                        issues.append('%s %s: horizontal overflow' % (tag, name))
                    for s, u in bad:
                        issues.append('%s %s: HTTP %s %s' % (tag, name, s, u))
                    for e in errs:
                        issues.append('%s %s: JS error %s' % (tag, name, e))
                    if tag != 'desktop':
                        continue
                    m = pg.evaluate(META)
                    if not m['t']:
                        issues.append('%s: no <title>' % name)
                    if not m['d']:
                        issues.append('%s: no meta description' % name)
                    if not m['c'] and name not in ALLOW_NO_CANONICAL:
                        issues.append('%s: no canonical' % name)
                    if m['h1'] != 1:
                        issues.append('%s: %d <h1> tags' % (name, m['h1']))
                    if m['noAlt']:
                        issues.append('%s: %d images with no alt text'
                                      % (name, m['noAlt']))
                    if m['dead']:
                        issues.append('%s: %d links that go nowhere'
                                      % (name, m['dead']))
                pg.close()
            b.close()
    finally:
        httpd.shutdown()

    for name in pages:
        text = open(os.path.join(ROOT, name), encoding='utf-8').read()
        for pat in ('Lorem', 'lorem ipsum', 'TODO', 'PLACEHOLDER'):
            if pat in text:
                issues.append('%s: contains %r' % (name, pat))

    print('Checked %d pages at two widths.' % len(pages))
    if not issues:
        print('No issues found.')
        return 0
    print('\nSUSPECTS: %d (confirm each before changing anything)\n' % len(issues))
    for i in issues:
        print('  -', i)
    return 1


if __name__ == '__main__':
    sys.exit(main())
