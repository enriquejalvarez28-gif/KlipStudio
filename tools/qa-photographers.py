#!/usr/bin/env python3
"""
KLIP — acceptance test for the photographer profiles and booking panel.

Why this exists
---------------
Every photographer profile is currently unapproved, so the page and the
booking panel render their empty state and none of the profile code runs.
That hid two real faults until a profile was approved by hand:

  * the specialties span used class "sp", which is also the specials
    pop-up — position:fixed, inset:0, z-index:118. The span became a
    full-screen shield over the booking modal (z-index 110) and nothing
    inside it could be clicked.
  * /admin writes a portfolio as [{"image": "..."}], but the gallery was
    handed those objects instead of paths, so View Work opened nothing.

Neither would have appeared in any check that only loads the site as it
ships today. This test injects an approved profile into the page config at
request time — the data files on disk are never touched — so the approved
path is exercised on every run, and it also checks that the empty state
still says something honest.

    python3 tools/qa-photographers.py
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import functools
import http.server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8911
PAGE = 'photography.html'

# A stand-in profile. It never reaches disk and never reaches a build; it
# exists only inside one browser tab for the length of this test.
FAKE = {
    'name': 'QA Test Profile',
    'specialties': 'Headshots · Branding',
    'bio': 'Placeholder biography used only by the acceptance test.',
    'headshot': 'img/klip-white-wall-studio-wide.jpg',
    'providerId': 'QA-0',
    'booking': 'photographySessions',
    'portfolio': ['img/klip-podcast-room-wide-angle.jpg',
                  'img/klip-black-room-desk-main.jpg'],
}

fails = []
checks = [0]


def check(ok, label):
    checks[0] += 1
    if not ok:
        fails.append(label)
    print('  %s %s' % ('ok  ' if ok else 'FAIL', label))


def serve():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


async def run():
    from playwright.async_api import async_playwright

    url = 'http://127.0.0.1:%d/%s' % (PORT, PAGE)
    async with async_playwright() as p:
        b = await p.chromium.launch()

        # ---------- 1. the state the site is actually in today ----------
        print('\nEmpty state (no approved profile):')
        ctx = await b.new_context(viewport={'width': 390, 'height': 900},
                                  is_mobile=True, has_touch=True)
        pg = await ctx.new_page()
        await pg.goto(url, wait_until='load')
        await pg.wait_for_timeout(700)

        state = await pg.evaluate("""() => {
            const s = document.getElementById('photographers');
            return {
              pending: !!(s && s.querySelector('.pg-pending')),
              words: s ? (s.querySelector('.pg-pending') || {}).innerText || '' : '',
              first: !!(s && s.querySelector('.pg-first')),
            };
        }""")
        check(state['pending'], 'page shows a pending note, not a bare heading')
        check(len(state['words'].split()) >= 8,
              'pending note actually says something')
        check(state['first'], 'First Available still offered on the page')

        await pg.click('[data-photographers]')
        await pg.wait_for_timeout(400)
        mstate = await pg.evaluate("""() => {
            const m = document.getElementById('pg-body');
            return {pending: !!m.querySelector('.pg-pending'),
                    emptyList: !!m.querySelector('.pg-list') &&
                               m.querySelector('.pg-list').children.length === 0};
        }""")
        check(mstate['pending'], 'booking panel explains why no one is listed')
        check(not mstate['emptyList'], 'booking panel has no empty list element')
        await ctx.close()

        # ---------- 2. the approved path, injected at request time ----------
        print('\nApproved profile (injected, nothing written to disk):')
        ctx = await b.new_context(viewport={'width': 390, 'height': 900},
                                  is_mobile=True, has_touch=True)

        async def patch(route):
            r = await route.fetch()
            body = await r.text()
            m = re.search(r'(<script[^>]*id="klip-config"[^>]*>)(.*?)(</script>)',
                          body, re.S)
            if m:
                cfg = json.loads(m.group(2))
                cfg.setdefault('photographers', {})['items'] = [FAKE]
                body = body[:m.start()] + m.group(1) + json.dumps(cfg) \
                    + m.group(3) + body[m.end():]
            await route.fulfill(response=r, body=body)

        await ctx.route('**/' + PAGE, patch)
        pg = await ctx.new_page()
        broken = []
        pg.on('response', lambda r: broken.append(r.url.split('/')[-1])
              if r.status >= 400 else None)
        await pg.goto(url, wait_until='load')
        await pg.wait_for_timeout(700)

        await pg.click('[data-photographers]')
        await pg.wait_for_timeout(400)

        card = await pg.evaluate("""() => {
            const x = document.querySelector('#pg-body .pg');
            if (!x) return null;
            return {face: !!x.querySelector('.pg-face img'),
                    name: (x.querySelector('b') || {}).textContent || '',
                    bio: (x.querySelector('p') || {}).textContent || '',
                    work: !!x.querySelector('.pg-work'),
                    book: !!x.querySelector('a[data-booking]'),
                    provider: (x.querySelector('a[data-booking]') || {})
                                .getAttribute('data-provider')};
        }""")
        check(card is not None, 'an approved profile renders in the panel')
        if card:
            check(card['face'], 'profile shows the headshot')
            check(len(card['bio']) > 10, 'profile shows the bio')
            check(card['work'], 'profile offers View Work')
            check(card['provider'] == FAKE['providerId'],
                  'Book carries the SimplyBook provider id')

        # the collision that made the panel unclickable
        shield = await pg.evaluate("""() => {
            const bad = [];
            document.querySelectorAll('#pg-body *').forEach(e => {
              const c = getComputedStyle(e);
              if (c.position === 'fixed' && parseInt(c.zIndex || 0) >= 110)
                bad.push(e.className || e.tagName);
            });
            return bad;
        }""")
        check(not shield,
              'nothing inside the panel is a fixed overlay above the modal '
              '(got: %s)' % (shield or 'none'))

        # View Work must open the gallery, above the modal, with real paths
        payload = await pg.evaluate(
            "() => document.querySelector('#pg-body .pg-work')"
            "        .getAttribute('data-gallery')")
        shots = json.loads(payload) if payload else []
        check(bool(shots) and all(isinstance(s[0], str) and '/' in s[0]
                                  for s in shots),
              'View Work payload is image paths, not CMS objects')

        await pg.click('#pg-body .pg-work')
        await pg.wait_for_timeout(600)
        gal = await pg.evaluate("""() => {
            const g = document.getElementById('gallery');
            return {open: g.classList.contains('is-open'),
                    z: parseInt(getComputedStyle(g).zIndex || 0),
                    thumbs: document.querySelectorAll('.gal-thumb').length};
        }""")
        check(gal['open'], 'View Work opens the gallery from inside the panel')
        check(gal['z'] > 110, 'gallery layers above the booking modal')
        check(gal['thumbs'] == len(FAKE['portfolio']),
              'every portfolio image has a thumbnail')

        check(not broken, 'no failed requests (%s)' % (broken[:3] or 'none'))
        await ctx.close()
        await b.close()


def main():
    if not os.path.exists(os.path.join(ROOT, PAGE)):
        print('Build the site first: python3 build/build.py')
        return 1
    srv = serve()
    try:
        asyncio.run(run())
    finally:
        srv.shutdown()
    print('\n' + '=' * 58)
    print('%d checks, %d failures' % (checks[0], len(fails)))
    for f in fails:
        print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
