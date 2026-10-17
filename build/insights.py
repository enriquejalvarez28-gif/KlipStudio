"""
KLIP — Insights hub and article pages.

Articles live one-per-file in data/insights/*.json so the CMS can treat them
as a folder collection: add, edit, delete and schedule without touching code.

Two rules this module enforces, from KLIPV2 §31:

  * A draft is never built. Not built as noindex, not built and hidden —
    simply not written to disk and not listed in the sitemap. The only way
    to publish is to set published: true.
  * Every article carries BlogPosting data built from what the file actually
    says. A missing author or date is left out of the schema rather than
    filled with a placeholder, because structured data that disagrees with
    the page is worse than none.
"""
import json
import os
import re

import render as R

try:
    import markdown as _md
except ImportError:                                  # pragma: no cover
    _md = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'data', 'insights')


def slugify(v):
    v = re.sub(r'[^a-z0-9]+', '-', (v or '').lower()).strip('-')
    return v or 'article'


def body_html(a):
    """Article body. Markdown when the library is present, otherwise
    paragraphs — never raw, unescaped HTML from the CMS."""
    raw = a.get('body') or ''
    if not raw.strip():
        return ''
    if _md:
        return _md.markdown(raw, extensions=['extra', 'sane_lists'])
    return ''.join('<p>%s</p>' % R.esc(p.strip())
                   for p in re.split(r'\n\s*\n', raw) if p.strip())


def load_articles():
    """Published articles, newest first. Drafts never leave this function."""
    out = []
    if not os.path.isdir(DIR):
        return out
    for name in sorted(os.listdir(DIR)):
        if not name.endswith('.json'):
            continue
        with open(os.path.join(DIR, name), encoding='utf-8') as fh:
            a = json.load(fh)
        a = a.get('article', a)
        if not a.get('published'):
            continue
        if not a.get('title'):
            continue
        a['slug'] = a.get('slug') or slugify(a['title'])
        a['_file'] = 'insights-%s.html' % a['slug']
        a['_url'] = '/insights/%s/' % a['slug']
        out.append(a)
    out.sort(key=lambda x: (x.get('datePublished') or '', x['slug']), reverse=True)
    return out


def card(a):
    img = ''
    if a.get('image'):
        img = '<div class="ins-img">%s</div>' % R.pic(
            a['image'], a.get('imageAlt') or a['title'],
            'loading="lazy" decoding="async" width="1200" height="800"')
    meta = []
    if a.get('category'):
        meta.append('<span class="ins-cat">%s</span>' % R.esc(a['category']))
    if a.get('datePublished'):
        meta.append('<time datetime="%s">%s</time>'
                    % (R.esc(a['datePublished']), R.esc(pretty(a['datePublished']))))
    return ('<a class="ins-card fade" href="%s" data-cat="%s">%s'
            '<div class="ins-body"><div class="ins-meta">%s</div>'
            '<h3>%s</h3>%s</div></a>'
            % (R.esc(a['_file']), R.esc(a.get('category', '')), img,
               ''.join(meta), R.esc(a['title']),
               '<p>%s</p>' % R.esc(a['excerpt']) if a.get('excerpt') else ''))


def pretty(iso):
    try:
        y, m, d = iso.split('-')[:3]
        months = ('January February March April May June July August '
                  'September October November December').split()
        return '%s %d, %s' % (months[int(m) - 1], int(d), y)
    except Exception:
        return iso


def hub_main(D, arts):
    I = D.get('insights') or {}
    head = ('<section class="page-hero page-hero--text"><div class="wrap">'
            '<p class="eyebrow fade">%s</p><h1>%s</h1><p class="lede fade">%s</p>'
            '</div></section>'
            % (R.esc(I.get('eyebrow', 'Insights')),
               R.headline(I.get('headline') or ['Insights']),
               R.esc(I.get('body', ''))))

    if not arts:
        return (head + '<section class="sec sec--paper"><div class="wrap">'
                '<p class="lede">%s</p></div></section>'
                % R.esc(I.get('emptyNote', '')))

    used = [c for c in (I.get('categories') or [])
            if any(a.get('category') == c for a in arts)]
    filters = ''
    if len(used) > 1:
        filters = ('<div class="work-filters ins-filters rv">'
                   '<button type="button" data-cat="all" aria-pressed="true">All</button>%s'
                   '</div>'
                   % ''.join('<button type="button" data-cat="%s" aria-pressed="false">%s'
                             '</button>' % (R.esc(c), R.esc(c)) for c in used))

    feat = [a for a in arts if a.get('featured')]
    rest = [a for a in arts if not a.get('featured')]
    body = ''
    if feat:
        body += '<div class="ins-grid ins-grid--lead rv">%s</div>' % ''.join(
            card(a) for a in feat[:1])
        rest = feat[1:] + rest
    body += '<div class="ins-grid rv" id="ins-grid">%s</div>' % ''.join(
        card(a) for a in rest)

    cta = ''
    if I.get('cta'):
        cta = ('<section class="sec sec--ink"><div class="wrap ta-c">%s</div></section>'
               % R.btn(I['cta'], 'btn--solid'))
    return (head + '<section class="sec sec--paper"><div class="wrap">%s%s</div>'
            '</section>' % (filters, body) + cta)


def article_main(D, a, arts):
    I = D.get('insights') or {}
    meta = []
    if a.get('category'):
        meta.append('<span class="ins-cat">%s</span>' % R.esc(a['category']))
    if a.get('datePublished'):
        meta.append('<time datetime="%s">%s</time>'
                    % (R.esc(a['datePublished']), R.esc(pretty(a['datePublished']))))
    if a.get('author'):
        meta.append('<span>By %s</span>' % R.esc(a['author']))

    hero_img = ''
    if a.get('image'):
        hero_img = ('<figure class="art-hero">%s</figure>' % R.pic(
            a['image'], a.get('imageAlt') or a['title'],
            'fetchpriority="high" decoding="async" width="1600" height="900"'))

    review = ''
    if a.get('reviewer'):
        review = ('<p class="art-review">Reviewed by %s</p>' % R.esc(a['reviewer']))
    if a.get('dateModified') and a['dateModified'] != a.get('datePublished'):
        review += ('<p class="art-review">Updated %s</p>'
                   % R.esc(pretty(a['dateModified'])))

    # one CTA, not five
    cta = ''
    if a.get('cta'):
        cta = ('<div class="art-cta">%s</div>' % R.btn(a['cta'], 'btn--dark'))

    related = ''
    same = [x for x in arts
            if x['slug'] != a['slug'] and x.get('category') == a.get('category')][:3]
    if same:
        related = ('<section class="sec sec--paper"><div class="wrap">'
                   '<p class="eyebrow">Keep Reading</p>'
                   '<div class="ins-grid rv">%s</div></div></section>'
                   % ''.join(card(x) for x in same))

    return ('<article class="art"><div class="wrap art-head">'
            '<p class="art-meta">%s</p><h1>%s</h1>%s</div>%s'
            '<div class="wrap art-body">%s%s%s</div></article>%s'
            % (''.join(meta), R.esc(a['title']),
               '<p class="lede">%s</p>' % R.esc(a['excerpt']) if a.get('excerpt') else '',
               hero_img, body_html(a), review, cta, related))


def article_schema(a, site):
    """BlogPosting built from what the file says. Absent fields stay absent."""
    s = {"@type": "BlogPosting",
         "headline": a['title'],
         "url": site + a['_url'],
         "mainEntityOfPage": {"@type": "WebPage", "@id": site + a['_url']},
         "publisher": {"@id": site + "/#klip"}}
    if a.get('excerpt'):
        s['description'] = a['excerpt']
    if a.get('image'):
        s['image'] = site + '/' + a['image'].lstrip('/')
    if a.get('datePublished'):
        s['datePublished'] = a['datePublished']
    if a.get('dateModified') or a.get('datePublished'):
        s['dateModified'] = a.get('dateModified') or a['datePublished']
    if a.get('author'):
        s['author'] = {"@type": "Person", "name": a['author']}
    if a.get('category'):
        s['articleSection'] = a['category']
    return s
