#!/usr/bin/env python3
"""
KLIP — site build.

    python build/build.py

Reads the CMS content in data/*.json and writes a complete HTML file for
every page: headings, copy, links, image alt text, address and structured
data are all in the delivered HTML. Nothing a search engine needs waits for
JavaScript.

Editing stays where it was: /admin writes the JSON, this build turns it into
pages. Run it after any content change (Cloudflare Pages runs it on deploy).
"""
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import insights as INS  # noqa: E402
import render as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SITE = 'https://theklipstudio.com'

PARTS = ['brand', 'navigation', 'hero', 'sections', 'studio', 'photography',
         'photographers', 'podcasts', 'clients', 'location', 'visibility',
         'booking', 'consultation', 'faq', 'specials', 'seo', 'podcast-page',
         'insights', 'media-services']

LEGAL = [('privacy.html', 'privacy', '/privacy/'), ('terms.html', 'terms', '/terms/')]

PAGES = [
    ('index.html', 'home', '/'),
    ('media.html', 'media', '/media/'),
    ('studio.html', 'studio', '/studio/'),
    ('photography.html', 'photography', '/photography/'),
    ('podcasts.html', 'podcasts', '/podcasts/'),
    ('work.html', 'work', '/work/'),
    ('about.html', 'about', '/about/'),
]


def load():
    d = {}
    for p in PARTS:
        with open(os.path.join(DATA, p + '.json'), encoding='utf-8') as fh:
            d.update(json.load(fh))
    with open(os.path.join(DATA, 'pages.json'), encoding='utf-8') as fh:
        pages = json.load(fh)
    with open(os.path.join(DATA, 'legal.json'), encoding='utf-8') as fh:
        d.update(json.load(fh))
    try:
        with open(os.path.join(DATA, 'webp.json'), encoding='utf-8') as fh:
            R.WEBP = set(json.load(fh))
    except OSError:
        R.WEBP = set()
    try:
        with open(os.path.join(DATA, 'srcset.json'), encoding='utf-8') as fh:
            R.SRCSET = json.load(fh)
    except OSError:
        R.SRCSET = {}
    R.BOOKING_BASE = (d.get('booking') or {}).get('base', '')
    return d, pages


# ----------------------------------------------------------------- chrome
def header(D, here):
    def cur(h):
        return ' aria-current="page"' if str(h).split('/')[-1].lower() == here else ''

    # KLIPV2 §31: do not crowd the desktop nav. A link marked mobileOnly is
    # in the drawer and the footer but not the desktop bar, which is where
    # Insights lives until the top-level row has room for a seventh item.
    nav = ''.join('<a href="%s"%s>%s</a>' % (R.esc(l['href']), cur(l['href']), R.esc(l['label']))
                  for l in D['nav']['links'] if not l.get('mobileOnly'))
    drawer_nav = ''.join('<a href="%s"%s>%s</a>'
                         % (R.esc(l['href']), cur(l['href']), R.esc(l['label']))
                         for l in D['nav']['links'])
    a = R.act(D['nav']['cta'])
    cta_attr = ' data-consult="1"' if D['nav']['cta'].get('consult') else ''
    logo = D['logo'].get('mark') or D['logo'].get('light')
    return (
        '<a class="skip" href="#top">Skip to content</a>\n'
        '<div class="progress" id="progress" aria-hidden="true"></div>\n'
        '<div class="cursor" id="cursor" aria-hidden="true"></div>\n'
        '<div class="cursor-ring" id="cursor-ring" aria-hidden="true"><b>PLAY</b></div>\n'
        '<header class="site-header" id="header"><div class="wrap">'
        '<a class="brand" id="brand-link" href="index.html" aria-label="KLIP home">'
        '<img id="logo-light" src="%s" alt="%s" width="104" height="38"></a>'
        '<nav class="nav" id="nav" aria-label="Primary">%s</nav>'
        '<a class="btn btn--ghost header-cta" id="header-cta" href="%s"%s>%s %s</a>'
        '<button class="burger" id="burger" aria-label="Open menu" aria-expanded="false" '
        'aria-controls="drawer"><span></span></button>'
        '</div></header>\n'
        '<div class="drawer" id="drawer" role="dialog" aria-modal="true" aria-label="Menu">'
        '<div class="drawer-top"><img id="logo-light-2" src="%s" alt="%s" width="104" height="38">'
        '<button id="drawer-close" aria-label="Close menu" '
        'style="color:#fff;font-size:30px;line-height:1">&times;</button></div>'
        '<nav id="drawer-nav" aria-label="Mobile">%s</nav>'
        '<a class="btn btn--solid" id="drawer-cta" href="%s"%s>%s %s</a></div>'
        % (R.esc(logo), R.esc(D['logo'].get('alt', '')), nav,
           R.esc(a['href']), cta_attr, R.esc(D['nav']['cta']['label']), R.AR,
           R.esc(logo), R.esc(D['logo'].get('alt', '')), drawer_nav,
           R.esc(a['href']), cta_attr, R.esc(D['nav']['cta']['label']), R.AR))


def footer(D, here):
    def cur(h):
        return ' aria-current="page"' if str(h).split('/')[-1].lower() == here else ''

    FO = D['footer']
    h = D['hero']
    a, b = R.act(h['primaryCta']), R.act(h['secondaryCta'])
    return (
        '<div class="mcta" id="mcta">'
        '<a class="btn btn--solid" href="%s"%s>%s</a>'
        '<a class="btn btn--ghost" href="%s"%s>%s</a></div>\n'
        '<div class="mdl" id="booking-modal" role="dialog" aria-modal="true" aria-labelledby="booking-title">'
        '<div class="mdl-box mdl-box--wide"><div class="mdl-top"><h2 id="booking-title">Book with KLIP</h2>'
        '<button class="mdl-close" data-mdl-close aria-label="Close booking">&times;</button></div>'
        '<div class="mdl-body" id="booking-body"></div>'
        '<div class="mdl-foot"><span id="booking-note"></span>'
        '<a id="booking-fallback" href="#" target="_blank" rel="noopener"></a></div></div></div>\n'
        '<div class="mdl" id="consult-modal" role="dialog" aria-modal="true" aria-labelledby="consult-title">'
        '<div class="mdl-box"><div class="mdl-top"><h2 id="consult-title">Book a marketing call</h2>'
        '<button class="mdl-close" data-mdl-close aria-label="Close scheduler">&times;</button></div>'
        '<div class="mdl-body" id="consult-body"></div></div></div>\n'
        '<div class="mdl" id="pg-modal" role="dialog" aria-modal="true" aria-labelledby="pg-title">'
        '<div class="mdl-box mdl-box--wide"><div class="mdl-top"><h2 id="pg-title">KLIP Photographers</h2>'
        '<button class="mdl-close" data-mdl-close aria-label="Close photographers">&times;</button></div>'
        '<div class="mdl-body" id="pg-body"></div></div></div>\n'
        '<div class="lb" id="lightbox" role="dialog" aria-modal="true" aria-label="Video player">'
        '<div class="lb-inner" id="lb-inner">'
        '<button class="lb-close" id="lb-close" aria-label="Close video">&times;</button></div></div>\n'
        # Room gallery. Empty until a VIEW PHOTOS button fills it, so none of
        # the gallery images are fetched on page load.
        '<div class="gal" id="gallery" role="dialog" aria-modal="true" aria-label="Room photos">'
        '<div class="gal-top"><span class="gal-name" id="gal-name"></span>'
        '<span class="gal-count" id="gal-count"></span>'
        '<button class="gal-close" id="gal-close" aria-label="Close photos">&times;</button></div>'
        '<button class="gal-arrow gal-prev" id="gal-prev" aria-label="Previous photo">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg></button>'
        '<div class="gal-track" id="gal-track"></div>'
        '<button class="gal-arrow gal-next" id="gal-next" aria-label="Next photo">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg></button>'
        # Thumbnail strip. On a phone the arrows used to be hidden and swipe
        # was the only way through, with nothing on screen to say so, so the
        # other photos were invisible. The strip shows every photo in the
        # room at once and is tappable, which is what "view all of them"
        # means. Filled by the gallery script; empty on page load.
        '<div class="gal-thumbs" id="gal-thumbs" aria-label="All photos in '
        'this room"></div></div>\n'
        # Specials. The shell is empty and the script fills it only when a
        # live offer exists, so a site with no promotion ships no promotion.
        '<div class="sp" id="special" role="dialog" aria-modal="true" '
        'aria-labelledby="sp-head" hidden><div class="sp-box" id="sp-box">'
        '<button class="sp-close" id="sp-close" aria-label="Close offer">&times;</button>'
        '</div></div>\n'
        '<footer class="site-footer" id="site-footer"><div class="wrap">'
        '<div class="foot-top"><a href="#top" aria-label="Home">'
        '<img class="logo" src="%s" alt="%s" width="150" height="56"></a>'
        '<nav class="foot-nav" aria-label="Footer">%s</nav>'
        '<div class="socials">%s</div></div>'
        '<div class="foot-bottom"><span>%s &nbsp;&middot;&nbsp; %s</span><span>%s</span></div>'
        '</div></footer>'
        % (R.esc(a['href']), a['attr'],
           R.esc(h['primaryCta'].get('mobileLabel') or h['primaryCta']['label']),
           R.esc(b['href']), b['attr'],
           R.esc(h['secondaryCta'].get('mobileLabel') or h['secondaryCta']['label']),
           R.esc(D['logo'].get('dark', '')), R.esc(D['logo'].get('alt', '')),
           ''.join('<a href="%s"%s>%s</a>' % (R.esc(l['href']), cur(l['href']), R.esc(l['label']))
                   for l in FO['links']),
           ''.join('<a href="%s" aria-label="%s"%s><svg viewBox="0 0 24 24" aria-hidden="true">%s</svg></a>'
                   % (R.esc(s['href']), R.esc(s['label']), R.ext(s['href']),
                      R.SOCIAL.get(s['icon'], '')) for s in FO['socials']),
           R.esc(FO['copyright']),
           ' &nbsp;&middot;&nbsp; '.join('<a href="%s">%s</a>' % (R.esc(l['href']), R.esc(l['label']))
                                         for l in FO['legal']),
           R.esc(FO['tagline'])))


# --------------------------------------------------------------- homepage
def home_main(D):
    esc, btn, pic, icon, headline, act = R.esc, R.btn, R.pic, R.icon, R.headline, R.act
    H = D['hero']
    poster = H.get('videoPoster') or H.get('image')
    poster_m = H.get('videoPosterMobile') or poster

    # No <source> children in the HTML on purpose. A phone must never start
    # the desktop file, and the `media` attribute on <source> inside <video>
    # is not honoured by Chrome — tested: at 390px it fetched BOTH files and
    # played the desktop one. So the element ships empty and this inline
    # script, which runs before the next element is parsed, attaches exactly
    # one pair. Nothing is requested until it does.
    # The poster is the LCP element, so it is preloaded in <head> with a media
    # query (honoured on <link>, unlike on <source>) and only assigned here —
    # a poster="" attribute could not be made viewport-specific.
    video = (
        '<video id="hero-video" autoplay muted loop playsinline preload="metadata" '
        'width="1920" height="1080"></video>')
    swap = (
        '<script>(function(){var v=document.getElementById("hero-video");if(!v)return;'
        'var sm=matchMedia("(max-width:760px)").matches,p=sm?"%s":"%s";'
        'if(matchMedia("(prefers-reduced-motion: reduce)").matches){'
        'v.parentNode.innerHTML=\'<img src="\'+p+\'" alt="%s" fetchpriority="high" '
        'width="1920" height="1080">\';return;}'
        'v.poster=p;'
        'var w=sm?"%s":"%s",m=sm?"%s":"%s";'
        'function add(src,type){if(!src)return;var s=document.createElement("source");'
        's.src=src;s.type=type;v.appendChild(s);}'
        'add(w,"video/webm");add(m,"video/mp4");v.load();})();</script>'
        % (esc(poster_m), esc(poster), esc(H.get('imageAlt', '')),
           esc(H.get('videoMobileWebm', '')), esc(H.get('videoWebm', '')),
           esc(H.get('videoMobile', '')), esc(H.get('videoMp4', ''))))
    out = [
        '<section class="hero" id="top">'
        '<div class="hero-media">%s</div>%s'
        '<div class="hero-scrim" aria-hidden="true"></div>'
        '<div class="wrap"><div class="hero-copy">'
        '<p class="eyebrow on-dark fade">%s</p><h1>%s</h1>'
        '<p class="lede fade">%s</p>'
        '<div class="hero-actions">%s%s</div></div>'
        '<div class="hero-proof">%s</div></div>'
        '<div class="hero-aside" aria-hidden="true">%s</div></section>'
        % (video, swap,
           esc(H.get('eyebrow', '')), headline(H['headline']), esc(H.get('body', '')),
           btn(H['primaryCta'], 'btn--solid'), btn(H['secondaryCta'], 'btn--ghost'),
           ''.join('<span class="fade">%s</span>' % esc(p) for p in H.get('proof', [])),
           R.lines(H.get('sideNote', [])))]

    S = D['services']
    out.append(
        '<section class="sec sec--paper" id="services"><div class="wrap">'
        '<div class="sec-head rv"><div class="titles"><p class="eyebrow fade">%s</p><h2>%s</h2></div>'
        '<div class="aside"><p class="lede fade">%s</p>%s</div></div>'
        '<div class="svc-grid rv">%s</div></div></section>'
        % (esc(S['eyebrow']), headline(S['headline']), esc(S['body']),
           btn(S.get('cta'), 'btn--outline'),
           ''.join('<a class="svc fade" href="%s">%s<h3>%s</h3><p>%s</p></a>'
                   % (esc(i['href']), icon(i['icon']), esc(i['title']), esc(i['text']))
                   for i in S['items'])))

    W = D['why']
    out.append(
        '<section class="sec sec--paper" id="why" style="padding-top:0"><div class="wrap">'
        '<div class="why-split rv"><div><h2>%s</h2>'
        '<p class="lede fade" style="margin-top:20px">%s</p></div>'
        '<div class="why-points">%s</div></div></div></section>'
        % (headline(W['headline']), esc(W['body']),
           ''.join('<div class="why-point fade"><b>%s</b><span>%s</span></div>'
                   % (esc(p['title']), esc(p['text'])) for p in W['points'])))

    out.append(R.visibility({}, D).replace('<section class="sec sec--paper" id="visibility">',
                                           '<section class="sec sec--paper" id="visibility" style="padding-top:0">'))

    K = D['work']
    # A set of exactly two reels and two landscape projects tiles perfectly on
    # desktop as reel|landscape over reel|landscape, with both aspect ratios
    # intact. Any other mix falls back to the uniform band, so changing the
    # featured items in /admin cannot leave holes in the grid.
    fmts = [(w.get('format') or 'landscape') for w in K['items']]
    mix = ' work-grid--mix22' if (len(fmts) == 4 and fmts.count('reel') == 2
                                  and fmts.count('landscape') == 2) else ''
    tiles = ''
    for w in K['items']:
        # format drives the mobile shape: reels pair up 2-across, landscape
        # projects run full width. Nothing is a full-width 9:16 stack.
        cls = 'w fade' + {'wide': ' w-wide', 'tall': ' w-tall', 'span2': ' w-span2'}.get(w.get('size'), '')
        cls += ' w--' + (w.get('format') or 'landscape')
        prev = ''
        if w.get('preview') or w.get('previewMp4'):
            prev = (' data-preview="%s" data-preview-mp4="%s"'
                    % (esc(w.get('preview', '')), esc(w.get('previewMp4', ''))))
        tiles += ('<a class="%s" href="%s"%s>%s<span class="w-cap"><em>%s</em><h3>%s</h3>'
                  '<span class="go">View Project %s</span></span></a>'
                  % (cls, esc(w['href']), prev,
                     pic(w['image'], w['title'], 'loading="lazy" decoding="async" width="1500" height="940"'),
                     esc(w['category']), esc(w['title']), R.AR))
    out.append(
        '<section class="sec sec--dark" id="work"><div class="wrap">'
        '<div class="sec-head rv"><div class="titles"><p class="eyebrow on-dark fade">%s</p><h2>%s</h2></div>'
        '<div class="aside right">%s</div></div><div class="work-grid work-grid--home%s rv">%s</div></div></section>'
        % (esc(K['eyebrow']), headline(K['headline']), btn(K.get('cta'), 'btn--ghost'),
           mix, tiles))

    P = D['podcasts']
    eps = [c for c in P['items'] if (c.get('kind') or 'episode') == 'episode']
    clips = [c for c in P['items'] if (c.get('kind') or 'episode') == 'clip']
    # Episodes are the rail that auto-advances on a phone; clips sit two to a
    # row underneath and never auto-scroll. Same split as the Podcasts page.
    out.append(
        '<section class="sec sec--paper" id="podcasts"><div class="wrap">'
        '<div class="sec-head rv"><div class="titles"><p class="eyebrow fade">%s</p><h2>%s</h2></div>'
        '<div class="aside right"><div style="display:flex;align-items:center;gap:26px" class="fade">'
        '<a class="link" href="%s">%s %s</a><div class="carousel-ctl">'
        '<button class="circ" data-dir="-1" aria-label="Previous episode"><svg width="14" height="14" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'
        '<path d="M15 5l-7 7 7 7"/></svg></button>'
        '<button class="circ" data-dir="1" aria-label="Next episode"><svg width="14" height="14" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'
        '<path d="M9 5l7 7-7 7"/></svg></button></div></div></div></div>'
        '<div class="pod-grid pod-grid--eps pod-grid--home pod-n%d rv" id="pod-grid">%s</div>'
        '%s</div></section>'
        % (esc(P['eyebrow']), headline(P['headline']), esc(P['cta']['href']),
           esc(P['cta']['label']), R.AR,
           min(len(eps), 4), ''.join(pod_card(c) for c in eps),
           ('<p class="rail-label">%s</p><div class="pod-clips pod-clips--home pod-n%d rv">%s</div>'
            % (esc(P.get('clipsLabel', 'Short Clips')), min(len(clips), 4),
               ''.join(pod_card(c) for c in clips))) if clips else ''))

    T = D['studio']
    room_tiles = ''
    for _n, r in enumerate([x for x in T['rooms'] if x.get('active', True)], 1):
        # Three visible actions under every room, identical on both pages:
        # VIEW PHOTOS | EXPLORE ROOM ........ BOOK ROOM.
        # The photo itself opens the gallery, never booking.
        href = 'studio.html#%s' % r.get('anchor', 'rooms')
        caps = (r.get('capabilities') or [])[:3]
        focal = (' style="object-position:%s"' % esc(r['focal'])) if r.get('focal') else ''
        name = r['name']
        media = R.room_media(
            r, href, 'loading="lazy" decoding="async" width="820" height="640"' + focal)
        vp = R.view_photos_btn(r)
        book = act({'booking': r.get('booking')}) if r.get('booking') else None
        room_tiles += ('<article class="room fade">%s<div class="room-text">'
                       '<a class="room-name" href="%s" data-track="explore_room" '
                       'data-track-room="%s"><span class="k-num">%02d</span>'
                       '<h3>%s</h3></a>'
                       '<span>%s%s</span>%s'
                       '<div class="room-actions">%s'
                       '<a class="vp-btn vp-btn--ghost" href="%s" '
                       'data-track="explore_room" data-track-room="%s">'
                       '<span>Explore Room</span></a>%s</div>'
                       '</div></article>'
                       % (media, esc(href), esc(name), _n, esc(name),
                          esc(r.get('role') or r.get('card') or ''),
                          '<br>' + esc(r['price']) if r.get('price') else '',
                          ('<ul class="room-caps room-caps--mini">%s</ul>'
                           % ''.join('<li>%s</li>' % esc(c) for c in caps)) if caps else '',
                          vp, esc(href), esc(name),
                          ('<a class="btn btn--dark room-book" href="%s"%s '
                           'data-track="book_room" data-track-room="%s">Book Room %s</a>'
                           % (esc(book['href']), book['attr'], esc(name), R.AR))
                          if book else ''))
    out.append(
        '<section id="studio" style="background:var(--paper);padding-bottom:clamp(44px,5vw,78px)">'
        '<div class="studio-split rv"><figure>%s</figure>'
        '<div class="studio-copy"><p class="eyebrow fade">%s</p><h2>%s</h2>'
        '<p class="lede fade">%s</p><div class="photo-actions">%s%s</div></div></div>'
        '<div class="wrap"><div class="rooms rv">%s</div>'
        '<div class="room-panel rv"><ul>%s</ul>%s</div></div></section>'
        % (pic(T['image'], T.get('imageAlt', ''),
               'loading="lazy" decoding="async" width="1700" height="1130"'),
           esc(T['eyebrow']), headline(T['headline']), esc(T['body']),
           btn(T.get('cta'), 'btn--dark'), btn(T.get('tourCta'), 'btn--outline'), room_tiles,
           ''.join('<li>%s %s</li>' % (icon(f['icon']), esc(f['label'])) for f in T['features']),
           btn(T.get('featuresCta'), 'btn--ghost')))

    F = D['photography']
    out.append(
        '<section class="sec" id="photography" style="background:var(--paper);'
        'padding-top:clamp(30px,3vw,46px)"><div class="wrap"><div class="photo-split rv">'
        '<div><p class="eyebrow fade">%s</p><h2>%s</h2>'
        '<p class="lede fade" style="margin-top:18px">%s</p>'
        '<div class="photo-actions">%s%s</div>'
        '<p class="fade" style="margin:20px 0 0"><a class="link" href="#photography" '
        'data-photographers="1">%s %s</a></p></div><div class="photo-grid">%s</div></div></div></section>'
        % (esc(F['eyebrow']), headline(F['headline']), esc(F['body']),
           btn(F['primaryCta'], 'btn--dark'), btn(F['secondaryCta'], 'btn--outline'),
           esc(F['smallLink']['label']), R.AR,
           ''.join('<figure class="ph fade">%s<figcaption>%s</figcaption></figure>'
                   % (pic(p['image'], p.get('alt', ''),
                          'loading="lazy" decoding="async" width="780" height="1030"'),
                      esc(p['label'])) for p in F['items'])))

    L = D['location']
    out.append(
        '<section class="location" id="on-location"><div class="bg">%s</div>'
        '<div class="scrim" aria-hidden="true"></div><div class="wrap">'
        '<div class="loc-copy rv"><h2>%s</h2>'
        '<p class="lede on-dark fade" style="margin-top:20px">%s</p>%s</div>'
        '<div class="loc-panel rv">%s</div></div></section>'
        % (pic(L['image'], L.get('imageAlt', ''),
               'loading="lazy" decoding="async" width="2000" height="1150"'),
           headline(L['headline']), esc(L['body']), btn(L.get('cta'), 'btn--ghost'),
           ''.join('<div class="fade">%s</div>' % esc(c) for c in L['categories'])))

    I = D['industries']
    out.append(
        '<section class="sec sec--paper" id="industries"><div class="wrap">'
        '<div class="sec-head rv"><div class="titles"><h2>%s</h2></div>'
        '<div class="aside"><p class="lede fade">%s</p></div></div>'
        '<div class="ind-grid rv">%s</div></div></section>'
        % (headline(I['headline']), esc(I['body']),
           ''.join('<a class="ind fade" href="%s">%s<figcaption><b>%s</b><span>%s</span>'
                   '</figcaption></a>'
                   % (esc(t['href']),
                      pic(t['image'], t['title'],
                          'loading="lazy" decoding="async" width="720" height="900"'),
                      esc(t['title']), esc(t['examples'])) for t in I['items'])))

    A = D['about']
    out.append(
        '<section class="sec sec--paper" id="about-klip" style="padding-top:0"><div class="wrap">'
        '<div class="about-split rv"><figure>%s</figure><div><h2>%s</h2>'
        '<p class="lede fade" style="margin-top:20px">%s</p>'
        '<div style="margin-top:28px">%s</div></div></div></div></section>'
        % (pic(A['image'], A.get('imageAlt', ''),
               'loading="lazy" decoding="async" width="1400" height="933"'),
           headline(A['headline']), esc(A['body']), btn(A.get('cta'), 'btn--dark')))

    out.append(R.cta({}, D))
    return '\n'.join(out)


# ------------------------------------------------------------------ pages
def pod_card(c):
    """A podcast card. Episodes are 16:9, clips 9:16; a clip may carry a
    silent preview that the page attaches only when it is on screen."""
    kind = c.get('kind') or 'episode'
    prev = ''
    if c.get('preview') or c.get('previewMp4'):
        prev = (' data-preview="%s" data-preview-mp4="%s"'
                % (R.esc(c.get('preview', '')), R.esc(c.get('previewMp4', ''))))
    return ('<a class="pod pod--%s fade" href="%s"%s%s><div class="pod-thumb">%s</div>'
            '<div class="pod-meta"><div><span class="label">%s</span><h3>%s</h3></div>%s</div></a>'
            % (R.esc(kind), R.esc(c.get('video') or 'podcasts.html'),
               ' data-video="%s"' % R.esc(c['video']) if c.get('video') else '', prev,
               R.pic(c['image'], '%s: %s' % (c.get('show', ''), c.get('title', '')),
                     'loading="lazy" decoding="async" width="1000" height="700"'),
               R.esc(c.get('show', '')), R.esc(c.get('title', '')),
               '<span class="pod-time">%s</span>' % R.esc(c['time']) if c.get('time') else ''))



def live_special(D):
    """The offer, but only if it is genuinely live.

    Active, inside its date window, and carrying at least a headline. A
    promotional price with no SimplyBook service behind it is not published:
    an offer a visitor cannot actually book is worse than no offer.
    """
    S = (D.get('specials') or {})
    if not S.get('active') or not S.get('headline'):
        return None
    today = date.today().isoformat()
    if S.get('startDate') and today < S['startDate']:
        return None
    if S.get('endDate') and today > S['endDate']:
        return None
    if S.get('promoPrice') and not (S.get('booking') or S.get('simplybookServiceId')):
        return None
    return S


def runtime_config(D):
    """The settings the behaviour needs, inlined so nothing is fetched at runtime.
    Content is already in the HTML; this is booking ids, schedulers and copy for
    the interactive pieces only. No secrets — those are Cloudflare env vars."""
    return {
        'booking': D.get('booking', {}),
        'consultation': D.get('consultation', {}),
        # Only approved profiles are inlined. A profile is approved when it is
        # active, not marked temp, and actually has a headshot and a provider
        # id. Filtering here and not in the browser matters: the config is
        # shipped in the HTML, so an unapproved name left in it is published
        # whether or not anything renders it.
        'photographers': dict(
            D.get('photographers', {}),
            # Portfolios are normalised to plain paths here, the same way the
            # page renderer does it, so the booking panel and the page card
            # open the identical gallery instead of one of them shipping the
            # raw {"image": ...} objects /admin writes.
            items=[dict(p, portfolio=R.portfolio_urls(p))
                   for p in (D.get('photographers', {}).get('items') or [])
                   if p.get('active') and not p.get('temp')
                   and p.get('headshot') and p.get('providerId')]),
        'visibility': D.get('visibility', {}),
        'hero': {k: D['hero'].get(k) for k in
                 ('image', 'videoPoster', 'videoPosterMobile', 'videoMp4',
                  'videoWebm', 'videoMobile', 'videoMobileWebm')},
        'webp': sorted(R.WEBP),
        # Only a genuinely live offer is inlined, and only the fields the
        # pop-up needs. An inactive or expired offer is simply absent, so
        # there is nothing in the page for anyone to read or trigger.
        'special': (lambda S: S and {
            'name': S.get('name', ''), 'badge': S.get('badge', ''),
            'headline': S.get('headline', ''), 'copy': S.get('copy', ''),
            'regularPrice': S.get('regularPrice', ''),
            'promoPrice': S.get('promoPrice', ''),
            'ctaLabel': S.get('ctaLabel') or 'Book The Special',
            'booking': S.get('booking', ''),
            'image': S.get('image', ''), 'imageMobile': S.get('imageMobile', ''),
            'imageAlt': S.get('imageAlt', ''),
            'popup': bool(S.get('showAsPopup')),
            'days': int(S.get('frequencyDays') or 7),
            'delay': int(S.get('delaySeconds') or 10),
            'scroll': int(S.get('scrollPercent') or 40),
            'email': bool(S.get('emailCapture')),
            'emailLabel': S.get('emailLabel', ''),
            'emailNote': S.get('emailNote', ''),
            'id': (S.get('name') or S.get('headline') or '')[:40],
        })(live_special(D)) or None,
    }



def seo_for(D, key):
    """Per-page title, description, share image and index flag, as set in
    /admin -> SEO & Integrations. Anything left blank there falls back to the
    page's own content, so an empty field never blanks a tag."""
    S = (D.get('seo') or {})
    row = next((r for r in (S.get('pages') or []) if r.get('key') == key), {})
    share = row.get('shareImage') or S.get('shareImage') or 'img/hero.jpg'
    if not share.startswith('http'):
        share = SITE + '/' + share.lstrip('/')
    return (row.get('title') or '', row.get('description') or '',
            share, bool(row.get('noindex')))


def site_head(D):
    """Verification tags and measurement snippets, from public IDs only.

    Nothing is emitted for a blank field, so a site with no analytics ships
    no analytics. Secrets never belong here — this file is public; API keys
    and webhook secrets stay in the Cloudflare environment.
    """
    I = (D.get('integrations') or {})
    out = []
    if I.get('searchConsole'):
        out.append('<meta name="google-site-verification" content="%s">'
                   % R.esc(I['searchConsole']))
    if I.get('bing'):
        out.append('<meta name="msvalidate.01" content="%s">' % R.esc(I['bing']))
    if I.get('gtm'):
        g = R.esc(I['gtm'])
        out.append("<script>(function(w,d,s,l,i){w[l]=w[l]||[];"
                   "w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});"
                   "var f=d.getElementsByTagName(s)[0],j=d.createElement(s),"
                   "dl=l!='dataLayer'?'&l='+l:'';j.async=true;"
                   "j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;"
                   "f.parentNode.insertBefore(j,f);})"
                   "(window,document,'script','dataLayer','%s');</script>" % g)
    elif I.get('ga4'):
        g = R.esc(I['ga4'])
        out.append('<script async src="https://www.googletagmanager.com/gtag/js?id=%s">'
                   '</script><script>window.dataLayer=window.dataLayer||[];'
                   'function gtag(){dataLayer.push(arguments);}'
                   "gtag('js',new Date());gtag('config','%s');</script>" % (g, g))
    return ('\n' + '\n'.join(out)) if out else ''


def shell(title, desc, canonical, body, schema, page_key, extra_head='',
          config='{}', share='', noindex=False, site_head=''):
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%s</title>
<meta name="description" content="%s">
<link rel="canonical" href="%s">%s
<meta name="theme-color" content="#1d1d1c">
<link rel="icon" type="image/png" href="img/favicon.png?v=2">
<link rel="apple-touch-icon" href="img/favicon.png?v=2">

<meta property="og:type" content="website">
<meta property="og:site_name" content="KLIP">
<meta property="og:title" content="%s">
<meta property="og:description" content="%s">
<meta property="og:url" content="%s">
<meta property="og:image" content="%s">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="%s">
<meta name="twitter:description" content="%s">
<meta name="twitter:image" content="%s">
%s

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="css/klip.css">
%s
<script type="application/ld+json">
%s
</script>
</head>
<body class="js-motion" data-page="%s">
%s
<script type="application/json" id="klip-config">%s</script>
<script src="js/klip-site.js" defer></script>
</body>
</html>
""" % (R.esc(title), R.esc(desc), canonical,
       '\n<meta name="robots" content="noindex,nofollow">' if noindex else '',
       R.esc(title), R.esc(desc), canonical, R.esc(share),
       R.esc(title), R.esc(desc), R.esc(share), site_head,
       extra_head, schema, page_key, body, config)


def org_schema(D):
    site = D.get('site', {})
    return {
        "@type": "Organization",
        "@id": SITE + "/#klip",
        "name": D['brand']['parent'],
        "alternateName": ["Klip", D['brand']['media'], D['brand']['studio']],
        "description": site.get('metaDescription', ''),
        "url": SITE + "/",
        "telephone": "+1-954-541-3708",
        "email": "info@theklipstudio.com",
        "logo": SITE + "/img/logo-dark.png",
        "address": {"@type": "PostalAddress", "streetAddress": "2145 Davie Blvd, Suite 204",
                    "addressLocality": "Fort Lauderdale", "addressRegion": "FL",
                    "postalCode": "33312", "addressCountry": "US"},
        "sameAs": [s['href'] for s in D['footer']['socials']],
        "subOrganization": [
            {"@type": "Organization", "@id": SITE + "/#klipmedia", "name": D['brand']['media'],
             "url": SITE + "/media", "parentOrganization": {"@id": SITE + "/#klip"}},
            {"@type": "LocalBusiness", "@id": SITE + "/#klipstudio", "name": D['brand']['studio'],
             "url": SITE + "/studio", "telephone": "+1-954-541-3708",
             "email": "info@theklipstudio.com", "image": SITE + "/img/studio-main.jpg",
             "address": {"@type": "PostalAddress", "streetAddress": "2145 Davie Blvd, Suite 204",
                         "addressLocality": "Fort Lauderdale", "addressRegion": "FL",
                         "postalCode": "33312", "addressCountry": "US"},
             "areaServed": ["Fort Lauderdale", "Broward County", "Miami-Dade County", "South Florida"],
             "parentOrganization": {"@id": SITE + "/#klip"}}]}


def breadcrumbs(name, url):
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
        {"@type": "ListItem", "position": 2, "name": name, "item": SITE + url}]}


SERVICE_PAGES = {
    'media': ("Digital Marketing", "Google Ads, Meta Ads, SEO, GEO and AI search, social media, branding, websites and AI automation."),
    'studio': ("Studio Rental & Production", "Podcast, video, photography, live streaming and course production in Fort Lauderdale."),
    'photography': ("Photography", "Headshots, lifestyle, personal branding and product photography."),
    'podcasts': ("Podcast Production", "Multicam podcast recording, editing and short-form clips."),
}


def video_schema(D):
    """VideoObject for the podcast clips that have a real link."""
    out = []
    for c in D['podcasts']['items']:
        if not c.get('video'):
            continue
        out.append({"@type": "VideoObject", "name": c['title'],
                    "description": "%s — %s, produced at Klip Studio." % (c['show'], c['title']),
                    "thumbnailUrl": SITE + "/" + c['image'], "contentUrl": c['video'],
                    "uploadDate": c.get('uploadDate') or date.today().isoformat(),
                    "publisher": {"@id": SITE + "/#klip"}})
    return out


def build():
    D, pages = load()
    cfg = runtime_config(D)
    head_tags = site_head(D)
    written = []
    for filename, key, url in PAGES:
        here = filename.lower()
        graph = [org_schema(D)]
        if key == 'home':
            title = D['site']['title']
            desc = D['site']['metaDescription']
            main = home_main(D)
            graph += video_schema(D)
            hp = D['hero']
            head = (
                '<link rel="preload" as="image" href="%s" media="(max-width:760px)" '
                'fetchpriority="high">\n'
                '<link rel="preload" as="image" href="%s" media="(min-width:761px)" '
                'fetchpriority="high">'
                % (R.esc(hp.get('videoPosterMobile') or hp.get('videoPoster', '')),
                   R.esc(hp.get('videoPoster', ''))))
        else:
            head = ''
            page = pages[key]
            title = page['title']
            desc = page['description']
            main = R.render_blocks(page.get('blocks'), D)
            graph.append(breadcrumbs(page['title'].split('—')[0].strip(), url))
            if key in SERVICE_PAGES:
                nm, sd = SERVICE_PAGES[key]
                graph.append({"@type": "Service", "name": nm, "description": sd,
                              "serviceType": nm, "provider": {"@id": SITE + "/#klip"},
                              "areaServed": {"@type": "Place", "name": "South Florida"},
                              "url": SITE + url})
            if key == 'podcasts':
                graph += video_schema(D)

        # the global rhythm rule is applied to the finished page, so it
        # holds whatever order the sections end up in (KLIP_GLOBAL §2)
        body = (header(D, here) + '\n<main>\n' + R.assign_modes(main)
                + '\n</main>\n' + footer(D, here))
        schema = json.dumps({"@context": "https://schema.org", "@graph": graph},
                            indent=2, ensure_ascii=False)
        t2, d2, share, noindex = seo_for(D, key)
        html = shell(t2 or title, d2 or desc, SITE + url, body, schema, key,
                     extra_head=head, share=share, noindex=noindex,
                     site_head=head_tags,
                     config=json.dumps(cfg, ensure_ascii=False, separators=(',', ':')))
        with open(os.path.join(ROOT, filename), 'w', encoding='utf-8') as fh:
            fh.write(html)
        written.append((filename, len(html)))

    # Privacy and Terms — plain readable pages, same chrome, same build
    for filename, key, url in LEGAL:
        L = D['legal'][key]
        secs = ''.join(
            '<section class="sec sec--paper"><div class="wrap legal-body">'
            '<h2>%s</h2>%s</div></section>'
            % (R.esc(sec['title']),
               ''.join('<p>%s</p>' % R.esc(par) for par in sec['body']))
            for sec in L['sections'])
        main = (
            '<section class="pagehero pagehero--legal" id="top"><div class="wrap">'
            '<p class="eyebrow on-dark">Effective %s</p><h1>%s</h1>'
            '<p class="lede on-dark" style="margin-top:20px">%s</p></div></section>'
            % (R.esc(D['legal']['effective']), R.headline(L['heading']), R.esc(L['intro']))
            + secs)
        graph = [org_schema(D), breadcrumbs(L['heading'][0], url)]
        body = (header(D, filename.lower()) + '\n<main>\n' + main + '\n</main>\n'
                + footer(D, filename.lower()))
        t2, d2, share, noindex = seo_for(D, key)
        html = shell(t2 or L['title'], d2 or L['description'], SITE + url, body,
                     json.dumps({"@context": "https://schema.org", "@graph": graph},
                                indent=2, ensure_ascii=False),
                     key, share=share, noindex=noindex, site_head=head_tags,
                     config=json.dumps(cfg, ensure_ascii=False, separators=(',', ':')))
        with open(os.path.join(ROOT, filename), 'w', encoding='utf-8') as fh:
            fh.write(html)
        written.append((filename, len(html)))

    # ---------------------------------------------------------- Insights
    # Drafts are not built at all, so an unpublished article has no page and
    # no sitemap entry — there is nothing to find and nothing to leak.
    arts = INS.load_articles()
    ins_urls = []

    hub_schema = [org_schema(D), breadcrumbs('Insights', '/insights/')]
    t2, d2, share, noindex = seo_for(D, 'insights')
    I = D.get('insights') or {}
    html = shell(t2 or I.get('title', 'Insights | KLIP'),
                 d2 or I.get('description', ''), SITE + '/insights/',
                 header(D, 'insights.html') + '\n<main>\n'
                 + INS.hub_main(D, arts) + '\n</main>\n' + footer(D, 'insights.html'),
                 json.dumps({"@context": "https://schema.org", "@graph": hub_schema},
                            indent=2, ensure_ascii=False),
                 'insights', share=share, noindex=noindex, site_head=head_tags,
                 config=json.dumps(cfg, ensure_ascii=False, separators=(',', ':')))
    with open(os.path.join(ROOT, 'insights.html'), 'w', encoding='utf-8') as fh:
        fh.write(html)
    written.append(('insights.html', len(html)))
    ins_urls.append('/insights/')

    for a in arts:
        graph = [org_schema(D), INS.article_schema(a, SITE),
                 breadcrumbs(a['title'][:60], a['_url'])]
        body = (header(D, 'insights.html') + '\n<main>\n'
                + INS.article_main(D, a, arts) + '\n</main>\n'
                + footer(D, 'insights.html'))
        share_a = a.get('socialImage') or a.get('image') or ''
        if share_a and not share_a.startswith('http'):
            share_a = SITE + '/' + share_a.lstrip('/')
        html = shell(a.get('seoTitle') or (a['title'] + ' | KLIP'),
                     a.get('metaDescription') or a.get('excerpt', ''),
                     a.get('canonical') or (SITE + a['_url']), body,
                     json.dumps({"@context": "https://schema.org", "@graph": graph},
                                indent=2, ensure_ascii=False),
                     'insights', share=share_a or share, site_head=head_tags,
                     config=json.dumps(cfg, ensure_ascii=False, separators=(',', ':')))
        with open(os.path.join(ROOT, a['_file']), 'w', encoding='utf-8') as fh:
            fh.write(html)
        written.append((a['_file'], len(html)))
        ins_urls.append(a['_url'])

    # sitemap from the same lists, so it can never drift from the pages
    today = date.today().isoformat()
    urls = ''.join(
        '  <url><loc>%s%s</loc><lastmod>%s</lastmod><changefreq>%s</changefreq>'
        '<priority>%s</priority></url>\n'
        % (SITE, u, today, 'weekly' if u == '/' else 'monthly', '1.0' if u == '/' else '0.8')
        for _, _, u in PAGES + LEGAL)
    urls += ''.join(
        '  <url><loc>%s%s</loc><lastmod>%s</lastmod><changefreq>monthly</changefreq>'
        '<priority>0.7</priority></url>\n' % (SITE, u, today) for u in ins_urls)
    with open(os.path.join(ROOT, 'sitemap.xml'), 'w', encoding='utf-8') as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n' % urls)

    print('Built %d pages:' % len(written))
    for f, n in written:
        print('  %-20s %6d bytes' % (f, n))
    print('  sitemap.xml          %d urls' % (len(PAGES) + len(LEGAL) + len(ins_urls)))
    return written


if __name__ == '__main__':
    build()
