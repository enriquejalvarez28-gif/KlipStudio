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
    if not o:
        return ''
    a = act(o)
    return ('<a class="btn %s" href="%s"%s>%s %s</a>'
            % (cls, esc(a['href']), a['attr'], esc(o.get('label', '')), AR))


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


def pic(src, alt='', attrs=''):
    """WebP only where one exists — a missing <source> breaks the image."""
    tag = '<img src="%s" alt="%s" %s>' % (esc(src), esc(alt or ''), attrs)
    if not re.search(r'\.jpe?g$', str(src or ''), re.I):
        return tag
    webp = re.sub(r'\.jpe?g$', '.webp', src, flags=re.I)
    if WEBP and os.path.basename(webp) not in WEBP:
        return tag
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


def split(b, D):
    fig = '<figure>%s</figure>' % pic(b.get('image', ''), b.get('imageAlt', ''),
                                      'loading="lazy" decoding="async" width="1200" height="800"')
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
    return ('<section class="sec sec--paper"%s><div class="wrap">%s'
            '<div class="%s rv" style="%s">%s</div></div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b),
               'ind-grid' if portrait else 'rooms', style, items))


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
        fig = '<figure>%s</figure>' % pic(
            r.get('image', ''), r.get('imageAlt') or name,
            'loading="lazy" decoding="async" width="1600" height="900"')
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
    items = ''
    for c in (b.get('items') or []):
        items += ('<a class="pod fade" href="%s"%s><div class="pod-thumb">%s</div>'
                  '<div class="pod-meta"><div><span class="label">%s</span><h3>%s</h3></div>%s</div></a>'
                  % (esc(c.get('video') or '#'),
                     ' data-video="%s"' % esc(c['video']) if c.get('video') else '',
                     pic(c.get('image', ''), c.get('title', ''),
                         'loading="lazy" decoding="async" width="1000" height="700"'),
                     esc(c.get('show', '')), esc(c.get('title', '')),
                     '<span class="pod-time">%s</span>' % esc(c['time']) if c.get('time') else ''))
    return ('<section class="sec sec--paper"%s><div class="wrap">%s'
            '<div class="pod-grid rv" id="pod-grid">%s</div></div></section>'
            % (' id="%s"' % esc(b['id']) if b.get('id') else '', head_block(b), items))


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
          'clips': clips, 'visibility': visibility, 'cta': cta}


def render_blocks(blocks, D):
    return ''.join(BLOCKS[b['type']](b, D) for b in (blocks or []) if b.get('type') in BLOCKS)
