/**
 * KLIP Visibility Check — server-side scanner
 * Cloudflare Pages Function. Deploys automatically at POST /api/visibility
 * when this folder sits at the root of the project.
 *
 * It reads only what a public visitor's browser could read: the HTML of the
 * submitted page, robots.txt and the sitemap. It computes scores from those
 * signals. It never invents a number, a ranking or an AI citation.
 *
 * Request :  POST { "url": "https://example.com" }
 * Response:  { url, host, scores:{search,ai,health,content}, findings:[{ok,text}], checkedAt }
 */

const TIMEOUT_MS   = 8000;
const MAX_BYTES    = 600_000;          // stop reading after ~600KB of HTML
const CACHE_TTL    = 3600;             // 1 hour per domain
const RATE_LIMIT   = 8;                // scans per IP per minute
const UA = 'KlipVisibilityCheck/1.0 (+https://theklipstudio.com)';

/* ---------------- helpers ---------------- */

const json = (data, status = 200, extra = {}) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...extra }
  });

/** Block anything that is not a public website (SSRF protection). */
function validateTarget(raw) {
  let u;
  try { u = new URL(/^https?:\/\//i.test(raw) ? raw : 'https://' + raw); }
  catch { return { error: 'That does not look like a website address.' }; }

  if (u.protocol !== 'http:' && u.protocol !== 'https:')
    return { error: 'Only http and https addresses can be scanned.' };

  const host = u.hostname.toLowerCase();

  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') ||
      host.endsWith('.internal') || host === '[::1]' || !host.includes('.'))
    return { error: 'That address is not a public website.' };

  // literal IP addresses: refuse private, loopback, link-local and metadata ranges
  const v4 = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    const priv =
      a === 0 || a === 10 || a === 127 ||
      (a === 169 && b === 254) ||                   // link-local + cloud metadata
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 100 && b >= 64 && b <= 127) ||
      a >= 224;
    if (priv) return { error: 'That address is not a public website.' };
  }
  if (host.startsWith('[')) return { error: 'That address is not a public website.' };

  u.hash = '';
  return { url: u };
}

async function grab(url, { timeout = TIMEOUT_MS, max = MAX_BYTES } = {}) {
  const res = await fetch(url, {
    redirect: 'follow',
    signal: AbortSignal.timeout(timeout),
    headers: { 'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,text/plain,*/*' }
  });
  const reader = res.body?.getReader();
  let received = 0;
  const chunks = [];
  if (reader) {
    while (received < max) {
      const { done, value } = await reader.read();
      if (done) break;
      received += value.length;
      chunks.push(value);
    }
    try { await reader.cancel(); } catch {}
  }
  const buf = new Uint8Array(received);
  let off = 0;
  for (const c of chunks) { buf.set(c.subarray(0, Math.min(c.length, received - off)), off); off += c.length; }
  return { res, body: new TextDecoder('utf-8', { fatal: false }).decode(buf) };
}

const strip = (s) => (s || '').replace(/\s+/g, ' ').trim();
const firstMatch = (re, s) => { const m = s.match(re); return m ? strip(m[1]) : ''; };
const countAll = (re, s) => (s.match(re) || []).length;

/* ---------------- the scan ---------------- */

async function scan(target) {
  const origin = target.origin;
  const findings = [];
  const add = (ok, text, weight = 1, bucket = []) => { findings.push({ ok, text, weight, bucket }); return ok ? weight : 0; };

  let page;
  try { page = await grab(target.href); }
  catch {
    return { error: 'We could not reach that site. Check the address, or try again in a moment.' };
  }

  const html = page.body;
  const status = page.res.status;
  const finalUrl = new URL(page.res.url || target.href);
  const https = finalUrl.protocol === 'https:';

  if (status >= 400) return { error: `That page returned a ${status} response, so there was nothing to scan.` };

  // ---- signals ----
  const title   = firstMatch(/<title[^>]*>([\s\S]*?)<\/title>/i, html);
  const desc    = firstMatch(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']*)["']/i, html) ||
                  firstMatch(/<meta[^>]+content=["']([^"']*)["'][^>]+name=["']description["']/i, html);
  const h1s     = (html.match(/<h1[\s>][\s\S]*?<\/h1>/gi) || []).map(h => strip(h.replace(/<[^>]+>/g, '')));
  const canon   = /<link[^>]+rel=["']canonical["']/i.test(html);
  const viewport= /<meta[^>]+name=["']viewport["']/i.test(html);
  const robotsMeta = firstMatch(/<meta[^>]+name=["']robots["'][^>]+content=["']([^"']*)["']/i, html).toLowerCase();
  const noindex = /noindex/.test(robotsMeta);
  const langSet = /<html[^>]+lang=["'][a-z]/i.test(html);
  const ogTitle = /<meta[^>]+property=["']og:(title|image)["']/i.test(html);

  const ldBlocks = html.match(/<script[^>]+application\/ld\+json[^>]*>([\s\S]*?)<\/script>/gi) || [];
  const ldText = ldBlocks.join(' ');
  const hasSchema = ldBlocks.length > 0 || /itemtype=["']https?:\/\/schema\.org/i.test(html);
  const hasOrgSchema = /"@type"\s*:\s*"?(Organization|LocalBusiness|ProfessionalService|Corporation)/i.test(ldText);
  const hasAddress  = /"(streetAddress|addressLocality)"/i.test(ldText) || /<address[\s>]/i.test(html);
  const hasPhone    = /"telephone"/i.test(ldText) || /href=["']tel:/i.test(html);

  const imgs = html.match(/<img\b[^>]*>/gi) || [];
  const imgsWithAlt = imgs.filter(t => /\balt\s*=\s*["'][^"']/i.test(t)).length;
  const altCoverage = imgs.length ? imgsWithAlt / imgs.length : 1;

  const links = html.match(/<a\b[^>]+href=["'][^"']+["']/gi) || [];
  const internal = links.filter(a => {
    const h = (a.match(/href=["']([^"']+)["']/i) || [])[1] || '';
    return h.startsWith('/') || h.includes(finalUrl.hostname);
  }).length;

  const text = strip(html.replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<style[\s\S]*?<\/style>/gi, ' ').replace(/<[^>]+>/g, ' '));
  const words = text ? text.split(' ').length : 0;

  // robots.txt + sitemap + AI crawler rules
  let robotsTxt = '', robotsOk = false, sitemapOk = false, aiBlocked = false;
  try {
    const r = await grab(origin + '/robots.txt', { timeout: 5000, max: 60_000 });
    if (r.res.ok) { robotsOk = true; robotsTxt = r.body.toLowerCase(); }
  } catch {}
  if (robotsTxt) {
    sitemapOk = /sitemap:\s*http/i.test(robotsTxt);
    // a disallow-all directly under a named AI crawler
    aiBlocked = /user-agent:\s*(gptbot|claudebot|perplexitybot|google-extended|ccbot|anthropic-ai)[\s\S]{0,200}?disallow:\s*\//.test(robotsTxt);
  }
  if (!sitemapOk) {
    try { const s = await grab(origin + '/sitemap.xml', { timeout: 5000, max: 20_000 }); sitemapOk = s.res.ok && /<(urlset|sitemapindex)/i.test(s.body); } catch {}
  }

  // ---- scoring: every point traces back to a signal above ----
  const searchPts = [
    [title.length >= 15 && title.length <= 70, 'Title tag is present and a usable length.', 'Your title tag is missing, too short or too long — it is the first thing Google and AI assistants read.'],
    [desc.length >= 50,       'Meta description is present.',        'No usable meta description, so search engines write their own.'],
    [h1s.length === 1,        'One clear H1 heading.',               h1s.length === 0 ? 'No H1 heading on the page, so the main topic is unclear.' : 'Multiple H1 headings compete for the main topic.'],
    [canon,                   'Canonical tag is set.',               'No canonical tag, which risks duplicate-content confusion.'],
    [sitemapOk,               'An XML sitemap is discoverable.',     'No XML sitemap found at the usual locations.'],
    [internal >= 8,           'Internal linking is in place.',       'Very few internal links were found on this page.']
  ];
  const healthPts = [
    [https,                   'HTTPS is active.',                    'The site is not served over HTTPS.'],
    [viewport,                'Mobile viewport is configured.',      'No mobile viewport tag, so phones will render the desktop layout.'],
    [!noindex,                'The page is indexable.',              'This page carries a noindex tag, so search engines are told to skip it.'],
    [robotsOk,                'robots.txt is reachable.',            'No robots.txt found at the root.'],
    [altCoverage >= 0.8,      'Most images carry alt text.',         `Only ${Math.round(altCoverage * 100)}% of images have alt text.`],
    [langSet,                 'Page language is declared.',          'No lang attribute on the html element.']
  ];
  const aiPts = [
    [hasSchema,               'Structured data is present.',         'No structured data found — AI answer engines rely on it to understand who you are.'],
    [hasOrgSchema,            'Organisation / LocalBusiness schema is present.', 'No Organization or LocalBusiness schema, so your business identity is not machine-readable.'],
    [hasAddress,              'A business address is published.',    'No address found on the page or in schema.'],
    [hasPhone,                'A phone number is published.',        'No clickable phone number or telephone in schema.'],
    [!aiBlocked,              'AI crawlers are not blocked in robots.txt.', 'robots.txt blocks one or more AI crawlers, which keeps you out of AI answers.'],
    [ogTitle,                 'Social/share metadata is present.',   'No Open Graph title or image, so shared links render bare.']
  ];
  const contentPts = [
    [words >= 300,            'The page has enough copy to describe the business.', 'Very little readable text on the page for search or AI to work with.'],
    [/\b(service|services|what we do|solutions|packages)\b/i.test(text), 'Services are described in the copy.', 'No clear services section in the page copy.'],
    [/\b(contact|call|book|get in touch|request)\b/i.test(text), 'A clear next step appears in the copy.', 'No obvious call to action in the page copy.'],
    [title && desc && h1s.length ? strip(h1s[0]).length > 8 : false, 'The main heading states what the business does.', 'The main heading does not clearly state what the business does.'],
    [/\b(fort lauderdale|miami|broward|florida|near me|[A-Z][a-z]+,\s?[A-Z]{2})\b/i.test(text), 'A service location is mentioned.', 'No city or service area mentioned, which hurts local and AI-driven discovery.']
  ];

  const tally = (pts) => Math.round((pts.filter(p => p[0]).length / pts.length) * 100);
  const collect = (pts) => pts.map(p => ({ ok: !!p[0], text: p[0] ? p[1] : p[2] }));

  const scores = {
    search:  tally(searchPts),
    ai:      tally(aiPts),
    health:  tally(healthPts),
    content: tally(contentPts)
  };

  // prioritise: failures first, biggest category gaps first, max 6
  const all = [
    ...collect(searchPts).map(f => ({ ...f, w: scores.search })),
    ...collect(aiPts).map(f => ({ ...f, w: scores.ai })),
    ...collect(healthPts).map(f => ({ ...f, w: scores.health })),
    ...collect(contentPts).map(f => ({ ...f, w: scores.content }))
  ];
  const fails = all.filter(f => !f.ok).sort((a, b) => a.w - b.w);
  const wins  = all.filter(f => f.ok);
  const out   = fails.slice(0, 6);
  if (out.length < 3) out.push(...wins.slice(0, 3 - out.length));

  return {
    url: finalUrl.href,
    host: finalUrl.hostname,
    scores,
    findings: out.map(f => ({ ok: f.ok, text: f.text })),
    checkedAt: new Date().toISOString()
  };
}

/* ---------------- handler ---------------- */

export async function onRequestPost(context) {
  const { request } = context;

  // crude per-IP rate limit using the edge cache
  const ip = request.headers.get('CF-Connecting-IP') || 'anon';
  const cache = caches.default;
  const rlKey = new Request(`https://rl.klip.local/${encodeURIComponent(ip)}`);
  try {
    const hit = await cache.match(rlKey);
    const n = hit ? Number(await hit.text()) : 0;
    if (n >= RATE_LIMIT) return json({ error: 'That is a lot of scans in one minute. Give it a moment and try again.' }, 429);
    await cache.put(rlKey, new Response(String(n + 1), { headers: { 'Cache-Control': 'max-age=60' } }));
  } catch {}

  let payload;
  try { payload = await request.json(); } catch { return json({ error: 'Bad request.' }, 400); }

  const check = validateTarget(String(payload?.url || ''));
  if (check.error) return json({ error: check.error }, 400);

  // cached result per normalised origin
  const cacheKey = new Request(`https://cache.klip.local/v1/${encodeURIComponent(check.url.origin + check.url.pathname)}`);
  try {
    const cached = await cache.match(cacheKey);
    if (cached) return json(await cached.json(), 200, { 'X-Klip-Cache': 'hit' });
  } catch {}

  let result;
  try { result = await scan(check.url); }
  catch (err) {
    console.error('visibility scan failed', err);        // logged, not shown
    return json({ error: 'The scan did not finish. Try again in a moment.' }, 502);
  }
  if (result.error) return json({ error: result.error }, 422);

  try { await cache.put(cacheKey, new Response(JSON.stringify(result), { headers: { 'Content-Type': 'application/json', 'Cache-Control': `max-age=${CACHE_TTL}` } })); } catch {}

  return json(result);
}

export const onRequestGet = () => json({ error: 'POST a url to this endpoint.' }, 405);
