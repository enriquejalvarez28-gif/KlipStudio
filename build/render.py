"""
KLIP — component renderer.

Every component the site draws lives here, in one place. The build script
turns data/*.json into complete HTML with these, so a crawler receives the
finished page and the browser does not have to assemble it.

This replaces the old client-side renderers. There is one renderer, not two.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AR = '<span class="ar" aria-hidden="true">&#8594;</span>'

with open(os.path.join(ROOT, 'build', 'icons.json'), encoding='utf-8') as fh:
    _MAPS = json.load(fh)
ICON = _MAPS['icons']
SOCIAL = _MAPS['socials']


# ---------------------------------------------------------------- helpers
def esc(s):
    return (str('' if s is None else s)
            .replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def ext(href):
    return ' target="_blank" rel="noopener"' if re.match(r'^https?:', str(href or ''), re.I) else ''


def act(o):
    """A CTA points at a url, the booking modal, Calendly or the photographer list."""
    if not o:
        return {'href': '#', 'attr': ''}
    if o.get('booking'):
        attr = ' data-booking="%s"' % esc(o['booking'])
        if o.get('provider'):
            attr += ' data-provider="%s"' % esc(o['provider'])
        return {'href': BOOKING_BASE or '#', 'attr': attr}
    if o.get('consult'):
        topic = o['consult'] if isinstance(o['consult'], str) else '1'
        return {'href': '#contact', 'attr': ' data-consult="%s"' % esc(topic)}
    if o.get('photographers'):
        return {'href': '#photography', 'attr': ' data-photographers="1"'}
    href = o.get('href') or '#'
    return {'href': href, 'attr': ext(href)}


BOOKING_BASE = ''


def btn(o, cls='btn--solid'):
    """A CTA. Where a mobileLabel exists the phone gets the short form and
    the desktop keeps the fuller supporting label — both are in the HTML and
    CSS swaps them, so no layout shift and both are crawlable."""
    if not o:
        return ''
    a = act(o)
    label = esc(o.get('label', ''))
    short = o.get('mobileLabel')
    text = ('<span class="lbl-full">%s</span><span class="lbl-short">%s</span>'
            % (label, esc(short))) if short else label
    return ('<a class="btn %s" href="%s"%s>%s %s</a>'
            % (cls, esc(a['href']), a['attr'], text, AR))


def icon(name):
    paths = ICON.get(name, '')
    if not paths:
        return ''
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.4" aria-hidden="true">%s</svg>' % paths)


def headline(lines_, punct=None):
    """The last line takes the red KLIP dot."""
    l = list(lines_ or [])
    last = esc(l.pop() if l else '')
    out = ''.join('<span class="ln"><span>%s</span></span>' % esc(x) for x in l)
    dot = ('<span class="dot dot--q">?</span>' if punct == '?'
           else '<span class="dot">.</span>')
    return out + '<span class="ln"><span>%s%s</span></span>' % (last, dot)


def lines(arr):
    return '<br>'.join(esc(x) for x in (arr or []))


WEBP = set()


SRCSET = {}


def pic(src, alt='', attrs='', sizes=None):
    """WebP only where one exists — a missing <source> breaks the image —
    plus the smaller widths from tools/make-sizes.py, so a phone downloads a
    480px file rather than a desktop one."""
    tag = '<img src="%s" alt="%s" %s>' % (esc(src), esc(alt or ''), attrs)
    if not re.search(r'\.jpe?g$', str(src or ''), re.I):
        return tag
    webp = re.sub(r'\.jpe?g$', '.webp', src, flags=re.I)
    if WEBP and os.path.basename(webp) not in WEBP:
        return tag
    entries = SRCSET.get(src)
    if entries:
        srcset = ', '.join('%s %dw' % (esc(u), w) for w, u in entries)
        return ('<picture><source srcset="%s" sizes="%s" type="image/webp">%s</picture>'
                % (srcset, esc(sizes or '(max-width:760px) 100vw, 50vw'), tag))
    return ('<picture><source srcset="%s" type="image/webp">%s</picture>'
            % (esc(webp), tag))


def ctas(list_, styles=None):
    styles = styles or ['btn--solid', 'btn--ghost']
    return ''.join(btn(c, styles[i] if i < len(styles) else styles[-1])
                   for i, c in enumerate(list_ or []))


# ------------------------------------------------------------ page blocks
def head_block(b, dark=False):
    if not b.get('headline') and not b.get('eyebrow'):
        return ''
    od = ' on-dark' if dark else ''
    out = '<div class="sec-head rv"><div class="titles">'
    if b.get('eyebrow'):
        out += '<p class="eyebrow%s fade">%s</p>' % (od, esc(b['eyebrow']))
    if b.get('headline'):
        out += '<h2>%s</h2>' % headline(b['headline'])
    out += '</div><div class="aside%s">' % (' right' if b.get('asideRight') else '')
    if b.get('body'):
        out += '<p class="lede%s fade">%s</p>' % (od, esc(b['body']))
    if b.get('cta'):
        out += btn(b['cta'], 'btn--ghost' if dark else 'btn--outline')
    return out + '</div></div>'


def pagehero(b, D):
    out = '<section class="pagehero" id="top">'
    if b.get('image'):
        out += ('<div class="bg">%s</div><div class="scrim" aria-hidden="true"></div>'
                % pic(b['image'], b.get('imageAlt', ''), 'fetchpriority="high" width="1600" height="900"'))
    out += '<div class="wrap rv">'
    if b.get('eyebrow'):
        out += '<p class="eyebrow on-dark fade">%s</p>' % esc(b['eyebrow'])
    out += '<h1>%s</h1>' % headline(b.get('headline') or [])
    if b.get('body'):
        out += '<p class="lede on-dark fade" style="margin-top:20px">%s</p>' % esc(b['body'])
    if b.get('ctas'):
        out += '<div class="hero-actions">%s</div>' % ctas(b['ctas'])
    return out + '</div></section>'


def editorial(b, D):
    items = ''
    for i in (b.get('items') or []):
        tag = 'a' if i.get('href') else 'div'
        href = ' href="%s"' % esc(i['href']) if i.get('href') else ''
        items += ('<%s class="svc fade"%s>%s<h3>%s</h3><p>%s</p></%s>'
                  % (tag, href, icon(i.get('icon', '')), esc(i.get('title', '')),
                     esc(i.get('text', '')), tag))
    return ('<section class="sec sec--paper"%s><div class="wrap">%s'
            '<div class="svc-grid rv">%s</div></div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b), items))


def room_gallery_button(anchor, D, label='View Studio Photos'):
    """A VIEW PHOTOS control for a room's gallery, usable from any page.

    Returns '' while that room has no extra views, so the Photography page
    never shows a button that opens a single picture.
    """
    for r in ((D.get('studio') or {}).get('rooms') or []):
        if r.get('anchor') != anchor:
            continue
        gal = [g for g in (r.get('gallery') or []) if g.get('image')]
        if not gal:
            return ''
        name = r.get('name') or ''
        shots = [[r.get('image', ''), r.get('imageAlt') or name]] + \
                [[g['image'], g.get('alt') or name] for g in gal]
        return ('<button type="button" class="view-photos view-photos--inline" '
                'data-gallery="%s" data-gallery-name="%s">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="1.5" aria-hidden="true"><rect x="3" y="5" width="18" '
                'height="14" rx="1.5"/><circle cx="8.5" cy="10" r="1.5"/>'
                '<path d="M21 16l-5-5-5 5-2-2-6 5"/></svg>%s '
                '<span class="vp-n">%d</span></button>'
                % (esc(json.dumps(shots)), esc(name), esc(label), len(shots)))
    return ''


def split(b, D):
    gal_btn = room_gallery_button(b['roomGallery'], D,
                                  b.get('roomGalleryLabel') or 'View Studio Photos') \
        if b.get('roomGallery') else ''
    fig = '<figure%s>%s%s</figure>' % (
        ' class="has-gallery"' if gal_btn else '',
        pic(b.get('image', ''), b.get('imageAlt', ''),
            'loading="lazy" decoding="async" width="1200" height="800"'),
        gal_btn.replace('view-photos--inline', '') if gal_btn else '')
    copy = '<div class="studio-copy">'
    if b.get('eyebrow'):
        copy += '<p class="eyebrow fade">%s</p>' % esc(b['eyebrow'])
    copy += '<h2>%s</h2>' % headline(b.get('headline') or [])
    if b.get('body'):
        copy += '<p class="lede fade">%s</p>' % esc(b['body'])
    if b.get('points'):
        copy += '<div class="why-points">' + ''.join(
            '<div class="why-point fade"><b>%s</b><span>%s</span></div>'
            % (esc(p.get('title', '')), esc(p.get('text', ''))) for p in b['points']) + '</div>'
    if b.get('ctas'):
        copy += '<div class="photo-actions">%s</div>' % ctas(b['ctas'], ['btn--dark', 'btn--outline'])
    copy += '</div>'
    return ('<section%s style="background:var(--paper)"><div class="studio-split rv">%s</div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '',
               (copy + fig) if b.get('reverse') else (fig + copy)))


def cards(b, D):
    portrait = b.get('ratio') == 'portrait'
    items = ''
    for i in (b.get('items') or []):
        a = act(i)
        if portrait:
            items += ('<a class="ind fade" href="%s"%s>%s<figcaption><b>%s</b>%s</figcaption></a>'
                      % (esc(a['href']), a['attr'],
                         pic(i.get('image', ''), i.get('title', ''),
                             'loading="lazy" decoding="async" width="720" height="900"'),
                         esc(i.get('title', '')),
                         '<span>%s</span>' % esc(i['sub']) if i.get('sub') else ''))
        else:
            items += ('<a class="room fade" href="%s"%s><div class="room-img">%s</div>'
                      '<h3>%s</h3>%s</a>'
                      % (esc(a['href']), a['attr'],
                         pic(i.get('image', ''), i.get('title', ''),
                             'loading="lazy" decoding="async" width="820" height="640"'),
                         esc(i.get('title', '')),
                         '<span>%s</span>' % esc(i['sub']) if i.get('sub') else ''))
    style = '' if portrait else 'grid-template-columns:repeat(%s,minmax(0,1fr))' % (b.get('cols') or 4)
    # The portrait grid is shared with Industries, which legitimately has six
    # tiles. Four items must not be stretched across a six-column grid, so the
    # count travels with the markup and the stylesheet picks the right shape.
    cls = 'ind-grid' if portrait else 'rooms'
    if portrait:
        cls += ' ind-grid--n%d' % min(len(b.get('items') or []), 6)
    return ('<section class="sec sec--paper"%s><div class="wrap">%s'
            '<div class="%s rv" style="%s">%s</div></div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b),
               cls, style, items))


def rooms(b, D):
    """Image-led room blocks, photo dominant, sides alternating."""
    lst = b.get('items')
    if lst is None and b.get('source') == 'studio.rooms':
        lst = (D.get('studio') or {}).get('rooms')
    out = ('<section class="sec sec--paper"%s><div class="wrap">%s</div>'
           % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b)))
    for i, r in enumerate(lst or []):
        a = act(r)
        rev = (i % 2 == 1)
        name = r.get('name') or r.get('title') or ''
        # Gallery: the cover plus whatever extra views the room has. The
        # VIEW PHOTOS control only appears once there is more than the cover,
        # so a room awaiting its shoot never shows a button that opens one
        # picture. Sources go in a data attribute, not <img> tags, so nothing
        # downloads until the gallery is opened.
        gal = [g for g in (r.get('gallery') or []) if g.get('image')]
        shots = ([{'image': r.get('image', ''),
                   'alt': r.get('imageAlt') or name}] + gal) if r.get('image') else gal
        gal_attr = view = ''
        if len(shots) > 1:
            gal_attr = (' data-gallery="%s" data-gallery-name="%s"'
                        % (esc(json.dumps([[g['image'], g.get('alt') or name]
                                           for g in shots])), esc(name)))
            view = ('<button type="button" class="view-photos"%s>'
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                    'stroke-width="1.5" aria-hidden="true"><rect x="3" y="5" width="18" '
                    'height="14" rx="1.5"/><circle cx="8.5" cy="10" r="1.5"/>'
                    '<path d="M21 16l-5-5-5 5-2-2-6 5"/></svg>'
                    'View Photos <span class="vp-n">%d</span></button>'
                    % (gal_attr, len(shots)))
        fig = '<figure%s>%s%s</figure>' % (
            ' class="has-gallery"' if view else '',
            pic(r.get('image', ''), r.get('imageAlt') or name,
                'loading="lazy" decoding="async" width="1600" height="900"'), view)
        copy = '<div class="studio-copy">'
        if r.get('role'):
            copy += '<p class="eyebrow fade">%s</p>' % esc(r['role'])
        copy += '<h2>%s</h2>' % headline([name])
        summary = r.get('summary') or r.get('sub')
        if summary:
            copy += '<p class="lede fade">%s</p>' % esc(summary)
        if r.get('capabilities'):
            copy += '<ul class="room-caps fade">%s</ul>' % ''.join(
                '<li>%s</li>' % esc(c) for c in r['capabilities'])
        copy += ('<div class="photo-actions"><a class="btn btn--dark" href="%s"%s>%s %s</a></div></div>'
                 % (esc(a['href']), a['attr'], esc(r.get('cta') or 'Book This Room'), AR))
        anchor = r.get('anchor')
        out += ('<div class="studio-split studio-split--room%s rv"%s>%s</div>'
                % (' is-rev' if rev else '',
                   ' id="%s"' % esc(anchor) if anchor else '',
                   (copy + fig) if rev else (fig + copy)))
    return out + '</section>'


def portfolio(b, D):
    """The full Work page: filters, with reels two-up and landscape full width."""
    filters = ''
    if b.get('filters'):
        filters = '<div class="work-filters" role="group" aria-label="Filter work">' + ''.join(
            '<button type="button" data-filter="%s" aria-pressed="%s">%s</button>'
            % (esc(f['key']), 'true' if i == 0 else 'false', esc(f['label']))
            for i, f in enumerate(b['filters'])) + '</div>'
    items = ''
    for i in (b.get('items') or []):
        a = act(i)
        fmt = i.get('format') or 'landscape'
        items += ('<a class="w fade w--%s" href="%s"%s data-category="%s">%s'
                  '<span class="w-cap"><em>%s</em><h3>%s</h3></span></a>'
                  % (esc(fmt), esc(a['href']), a['attr'], esc(i.get('category', '')),
                     pic(i.get('image', ''), i.get('title', ''),
                         'loading="lazy" decoding="async" width="1200" height="800"'),
                     esc(i.get('sub', '')), esc(i.get('title', ''))))
    return ('<section class="sec sec--paper"%s><div class="wrap">%s%s'
            '<div class="work-grid work-grid--all rv" id="work-grid">%s</div></div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b), filters, items))


def steps(b, D):
    items = ''.join(
        '<div class="step fade"><b>%02d</b><h3>%s</h3><p>%s</p></div>'
        % (n + 1, esc(i.get('title', '')), esc(i.get('text', '')))
        for n, i in enumerate(b.get('items') or []))
    return ('<section class="sec sec--dark"%s><div class="wrap">%s'
            '<div class="steps rv">%s</div></div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b, True), items))


def facts(b, D):
    items = ''.join(
        '<div class="why-point fade"><b>%s</b><span>%s</span></div>'
        % (esc(i.get('title', '')), i.get('html') or esc(i.get('text', '')))
        for i in (b.get('items') or []))
    return ('<section class="sec sec--paper"%s><div class="wrap">%s'
            '<div class="why-points rv" style="max-width:860px">%s</div></div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b), items))


def clips(b, D):
    """FULL EPISODES and SHORT CLIPS as two labelled sections.

    Episodes are 16:9 and ride the auto-advance rail; clips are 9:16, two to
    a row on a phone, and are never auto-scrolled. A list with no `kind` on
    its items is treated as episodes, so older data keeps working.
    """
    items = b.get('items') or []
    eps = [c for c in items if (c.get('kind') or 'episode') == 'episode']
    cl = [c for c in items if (c.get('kind') or 'episode') == 'clip']

    def card(c, kind):
        prev = ''
        if c.get('preview') or c.get('previewMp4'):
            prev = (' data-preview="%s" data-preview-mp4="%s"'
                    % (esc(c.get('preview', '')), esc(c.get('previewMp4', ''))))
        return ('<a class="pod pod--%s fade" href="%s"%s%s><div class="pod-thumb">%s</div>'
                '<div class="pod-meta"><div><span class="label">%s</span><h3>%s</h3></div>%s</div></a>'
                % (kind, esc(c.get('video') or '#'),
                   ' data-video="%s"' % esc(c['video']) if c.get('video') else '', prev,
                   pic(c.get('image', ''), c.get('title', ''),
                       'loading="lazy" decoding="async" width="1000" height="700"'),
                   esc(c.get('show', '')), esc(c.get('title', '')),
                   '<span class="pod-time">%s</span>' % esc(c['time']) if c.get('time') else ''))

    # The column count follows the item count. Two episodes in a four-column
    # grid leave half the row empty, which is the desktop dead space the
    # master doc calls out; two of four columns is a gap, two of two is a
    # layout.
    body = head_block(b)
    if eps:
        body += ('<p class="rail-label" id="full-episodes">%s</p>'
                 '<div class="pod-grid pod-grid--eps pod-n%d rv" id="episode-rail">%s</div>'
                 % (esc(b.get('episodesLabel', 'Full Episodes')), min(len(eps), 4),
                    ''.join(card(c, 'episode') for c in eps)))
    if cl:
        body += ('<p class="rail-label" id="short-clips">%s</p>'
                 '<div class="pod-clips pod-n%d rv">%s</div>'
                 % (esc(b.get('clipsLabel', 'Short Clips')), min(len(cl), 4),
                    ''.join(card(c, 'clip') for c in cl)))
    return ('<section class="sec sec--paper"%s><div class="wrap">%s</div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', body))


def faq(b, D):
    """Questions and answers as real HTML — <details> so it is keyboard
    accessible and open-able without JavaScript, and so a crawler reads
    every answer whether or not it is expanded. No layout jump: the
    accordion grows in place."""
    src = (D.get('faq') or {}) if b.get('source') == 'faq' else b
    items = src.get('items') or b.get('items') or []
    if not items:
        return ''
    b = dict(b, eyebrow=b.get('eyebrow') or src.get('eyebrow'),
             headline=b.get('headline') or src.get('headline'))
    rows = ''.join(
        '<details class="faq-item fade"%s><summary><span>%s</span>'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
        'aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></summary>'
        '<div class="faq-a"><p>%s</p></div></details>'
        % (' open' if i == 0 else '', esc(q.get('q', '')), esc(q.get('a', '')))
        for i, q in enumerate(items))
    return ('<section class="sec sec--paper"%s><div class="wrap">%s'
            '<div class="faq rv">%s</div></div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b), rows))


def duo(b, D):
    """Two equal primary paths side by side — Book a Photographer and Rent
    the Photo Studio. Both are revenue paths, so neither panel is styled as
    secondary: same size, same weight, same button prominence. 50/50 on
    desktop and iPad landscape, stacked full width on a phone."""
    panels = ''
    for p in (b.get('panels') or []):
        a = act(p.get('cta'))
        media = ''
        if p.get('image'):
            media = '<div class="duo-img">%s</div>' % pic(
                p['image'], p.get('imageAlt') or p.get('title', ''),
                'loading="lazy" decoding="async" width="1200" height="900"')
        panels += ('<div class="duo-panel fade">%s<div class="duo-copy">'
                   '<p class="eyebrow">%s</p><h3>%s</h3><p class="duo-text">%s</p>'
                   '<a class="btn btn--dark" href="%s"%s>%s %s</a></div></div>'
                   % (media, esc(p.get('eyebrow', '')), esc(p.get('title', '')),
                      esc(p.get('text', '')), esc(a['href']), a['attr'],
                      esc((p.get('cta') or {}).get('label', '')), AR))
    return ('<section class="sec sec--paper"%s><div class="wrap">%s'
            '<div class="duo rv">%s</div></div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b), panels))


def photographers(b, D):
    """Real photographer cards. A profile is public only when it is active,
    not marked temp, and actually has a headshot and a provider id — the
    three together are what "approved" means. Everything else stays private,
    so placeholder names can live in the CMS without ever reaching a
    visitor. First Available stays a small separate option beside them."""
    P = (D.get('photographers') or {})
    people = [p for p in (P.get('items') or [])
              if p.get('active') and not p.get('temp')
              and p.get('headshot') and p.get('providerId')]

    cards = ''
    for p in people:
        a = act({'booking': p.get('booking'), 'provider': p.get('providerId')})
        shots = [g for g in (p.get('portfolio') or []) if g]
        work = ''
        if shots:
            work = ('<button type="button" class="pg-work" data-gallery="%s" '
                    'data-gallery-name="%s">View Work <span class="vp-n">%d</span>'
                    '</button>'
                    % (esc(json.dumps([[u, '%s — work' % p.get('name', '')]
                                       for u in shots])),
                       esc(p.get('name', '')), len(shots)))
        cards += ('<article class="pg-card fade"><div class="pg-shot">%s</div>'
                  '<div class="pg-body"><h3>%s</h3><p class="pg-spec">%s</p>'
                  '<p class="pg-bio">%s</p><div class="pg-acts">'
                  '<a class="btn btn--dark" href="%s"%s>%s %s</a>%s</div></div></article>'
                  % (pic(p.get('headshot', ''), p.get('name', ''),
                         'loading="lazy" decoding="async" width="800" height="1000"'),
                     esc(p.get('name', '')), esc(p.get('specialties', '')),
                     esc(p.get('bio', '')), esc(a['href']), a['attr'],
                     esc('Book With %s' % p.get('name', '').split()[0]
                         if p.get('name') else 'Book'), AR, work))

    fa = P.get('firstAvailable') or {}
    aside = ''
    if fa:
        fa_act = act({'booking': fa.get('booking')})
        aside = ('<div class="pg-first fade"><div><p class="eyebrow">%s</p>'
                 '<p>%s</p></div><a class="btn btn--outline" href="%s"%s>%s %s</a></div>'
                 % (esc(fa.get('title', 'First Available')), esc(fa.get('text', '')),
                    esc(fa_act['href']), fa_act['attr'],
                    esc(fa.get('cta', 'Find A Time')), AR))

    note = ('<p class="pg-note fade">%s</p>' % esc(P['intro'])) if P.get('intro') else ''
    body = head_block(b)
    if cards:
        body += '<div class="pg-grid rv">%s</div>%s%s' % (cards, note, aside)
    else:
        # No approved profiles yet: show the one honest path rather than an
        # empty grid or placeholder people.
        body += '%s%s' % (note, aside)
    return ('<section class="sec sec--paper"%s><div class="wrap">%s</div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', body))


def visibility(b, D):
    V = D['visibility']
    return ('<section class="sec sec--paper" id="visibility"><div class="wrap"><div class="vis-panel rv">'
            '<div class="vis-head"><div><h2 style="color:#fff">%s</h2>'
            '<p class="lede on-dark fade" style="margin-top:16px">%s</p></div>'
            '<p class="vis-micro fade">%s</p></div>'
            '<form class="vis-form fade" id="vis-form" novalidate>'
            '<label class="skip" for="vis-url">Your website address</label>'
            '<input id="vis-url" name="url" type="text" inputmode="url" autocomplete="url" placeholder="%s">'
            '<button type="submit" id="vis-go">%s %s</button></form>'
            '<p class="vis-note fade">%s</p>'
            '<div class="vis-out" id="vis-out" aria-live="polite"></div></div></div></section>'
            % (headline(V['headline'], '?'), esc(V.get('sub', '')), esc(V.get('microLabel', '')),
               esc(V.get('placeholder', '')), esc(V.get('button', '')), AR,
               esc(V.get('disclaimer', ''))))


def cta(b, D):
    C = D['finalCta']
    return ('<section class="final" id="contact"><div class="bg">%s</div>'
            '<div class="scrim" aria-hidden="true"></div>'
            '<div class="wrap rv"><p class="eyebrow on-dark fade">%s</p><h2>%s</h2>'
            '<div class="final-actions">%s</div></div></section>'
            % (pic(b.get('image') or C['image'], C.get('imageAlt', ''),
                   'loading="lazy" decoding="async" width="1800" height="1000"'),
               esc(b.get('eyebrow') or C.get('eyebrow', '')),
               headline([b.get('headline') or C.get('headline', '')]),
               ctas(b.get('ctas') or [C.get('primaryCta'), C.get('secondaryCta')])))


BLOCKS = {'pagehero': pagehero, 'editorial': editorial, 'split': split, 'cards': cards,
          'rooms': rooms, 'portfolio': portfolio, 'steps': steps, 'facts': facts,
          'clips': clips, 'visibility': visibility, 'cta': cta,
          'faq': faq, 'duo': duo, 'photographers': photographers}


def render_blocks(blocks, D):
    return ''.join(BLOCKS[b['type']](b, D) for b in (blocks or []) if b.get('type') in BLOCKS)
