"""KLIP_FIX §7 — the acceptance test, every check, both pages, all 4 rooms."""
import asyncio
import sys
from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:8899/'
ROOMS = ['Klip Room', 'Kapture Room', 'Kreator Room', 'Kanvas Room']
fails = []


def chk(ok, label):
    print(('  PASS  ' if ok else '  FAIL  ') + label)
    if not ok:
        fails.append(label)


async def gallery_opens(pg, idx, where):
    """Click the idx-th VIEW PHOTOS and report what the gallery shows."""
    btns = pg.locator('.vp-btn[data-gallery]')
    if await btns.count() <= idx:
        return None
    await btns.nth(idx).click()
    await pg.wait_for_timeout(450)
    r = await pg.evaluate("""()=>{
      var g=document.getElementById('gallery');
      return {open:g.classList.contains('is-open'),
              name:document.getElementById('gal-name').textContent,
              count:document.getElementById('gal-count').textContent,
              n:document.querySelectorAll('.gal-track figure').length,
              closeVisible:!!document.getElementById('gal-close').offsetParent};}""")
    await pg.keyboard.press('Escape')
    await pg.wait_for_timeout(300)
    return r


async def page_checks(b, page, label, w=1440, touch=False):
    ctx = await b.new_context(viewport={'width': w, 'height': 900},
                              has_touch=touch, is_mobile=touch)
    pg = await ctx.new_page()
    await pg.goto(BASE + page, wait_until='load')
    await pg.wait_for_timeout(800)

    n = await pg.locator('.vp-btn[data-gallery]').count()
    chk(n == 4, f'{label}: 4 VIEW PHOTOS buttons present (found {n})')

    for i, room in enumerate(ROOMS):
        r = await gallery_opens(pg, i, label)
        if r is None:
            chk(False, f'{label}: {room} VIEW PHOTOS exists')
            continue
        chk(r['open'] and r['n'] >= 4 and room in r['name'],
            f'{label}: {room} opens {r["n"]} photos, counter {r["count"]}')
    await ctx.close()


async def main():
    async with async_playwright() as b_:
        b = await b_.chromium.launch()

        print('\n--- HOMEPAGE (desktop) ---')
        await page_checks(b, 'index.html', 'home')
        print('\n--- STUDIO PAGE (desktop) ---')
        await page_checks(b, 'studio.html', 'studio')

        # photo click opens the gallery, not booking
        ctx = await b.new_context(viewport={'width': 1440, 'height': 900})
        pg = await ctx.new_page()
        await pg.goto(BASE + 'index.html', wait_until='load')
        await pg.wait_for_timeout(700)
        print('\n--- ACTION SEPARATION ---')
        await pg.locator('.rooms .room-img--gal').first.click()
        await pg.wait_for_timeout(400)
        st = await pg.evaluate("""()=>({
          open:document.getElementById('gallery').classList.contains('is-open'),
          url:location.pathname})""")
        chk(st['open'] and st['url'].endswith('index.html'),
            'clicking the room photo opens the gallery, not booking')
        await pg.keyboard.press('Escape')
        await pg.wait_for_timeout(250)

        href = await pg.locator('.rooms a.vp-btn--ghost').first.get_attribute('href')
        chk(bool(href and 'studio.html#' in href),
            f'EXPLORE ROOM goes to the room detail ({href})')
        bk = await pg.locator('.rooms .room-book').first.get_attribute('data-booking')
        chk(bool(bk), f'BOOK ROOM opens embedded SimplyBook (key: {bk})')

        # keyboard
        print('\n--- KEYBOARD + TOUCH ---')
        await pg.locator('.vp-btn[data-gallery]').first.focus()
        await pg.keyboard.press('Enter')
        await pg.wait_for_timeout(400)
        kb = await pg.evaluate(
            "()=>document.getElementById('gallery').classList.contains('is-open')")
        await pg.keyboard.press('ArrowRight')
        await pg.wait_for_timeout(300)
        adv = await pg.evaluate("()=>document.getElementById('gal-count').textContent")
        chk(kb and adv.startswith('2'), f'keyboard opens and advances ({adv})')
        await pg.keyboard.press('Escape')
        await ctx.close()

        # swipe on a phone
        ctx = await b.new_context(viewport={'width': 390, 'height': 844},
                                  has_touch=True, is_mobile=True)
        pg = await ctx.new_page()
        await pg.goto(BASE + 'index.html', wait_until='load')
        await pg.wait_for_timeout(800)
        vis = await pg.evaluate("""()=>{
          var b=document.querySelector('.vp-btn[data-gallery]');
          return b?getComputedStyle(b).opacity:'0';}""")
        chk(vis == '1', 'VIEW PHOTOS always visible on touch (no hover needed)')
        await pg.locator('.vp-btn[data-gallery]').first.click()
        await pg.wait_for_timeout(450)
        await pg.evaluate("""()=>{var t=document.getElementById('gal-track');
          function ev(n,x){var e=new Touch({identifier:1,target:t,clientX:x,clientY:300});
            t.dispatchEvent(new TouchEvent(n,{touches:n==='touchend'?[]:[e],
              changedTouches:[e],bubbles:true}));}
          ev('touchstart',300); ev('touchend',110);}""")
        await pg.wait_for_timeout(350)
        sw = await pg.evaluate("()=>document.getElementById('gal-count').textContent")
        chk(sw.startswith('2'), f'swipe advances the gallery ({sw})')
        await ctx.close()

        # no horizontal overflow
        print('\n--- OVERFLOW ---')
        for w in (320, 375, 390, 430):
            ctx = await b.new_context(viewport={'width': w, 'height': 844})
            pg = await ctx.new_page()
            for page in ('index.html', 'studio.html'):
                await pg.goto(BASE + page, wait_until='load')
                await pg.wait_for_timeout(400)
                over = await pg.evaluate(
                    '()=>document.documentElement.scrollWidth-window.innerWidth')
                chk(over == 0, f'{page} at {w}px: no horizontal overflow ({over})')
            await ctx.close()

        # rooms bigger than work and podcast
        print('\n--- STUDIO OUTWEIGHS WORK AND PODCAST ---')
        ctx = await b.new_context(viewport={'width': 1440, 'height': 900})
        pg = await ctx.new_page()
        await pg.goto(BASE + 'index.html', wait_until='load')
        await pg.wait_for_timeout(800)
        sz = await pg.evaluate("""()=>{
          function h(sel){var e=document.querySelector(sel);
            return e?Math.round(e.getBoundingClientRect().height):0;}
          return {room:h('.rooms .room-img, .rooms .room-img--gal'),
                  work:h('.work-grid .w'), pod:h('#pod-grid .pod-thumb')};}""")
        chk(sz['room'] > sz['work'] and sz['room'] > sz['pod'],
            f'room image {sz["room"]}px > work {sz["work"]}px and podcast {sz["pod"]}px')
        await ctx.close()
        await b.close()

    print('\n' + '=' * 58)
    print('FAILURES: %d' % len(fails))
    for f in fails:
        print('  - ' + f)
    sys.exit(1 if fails else 0)

asyncio.run(main())
