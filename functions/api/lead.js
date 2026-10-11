/**
 * KLIP lead capture — forwards a Visibility Check lead to Make / GoHighLevel.
 * Cloudflare Pages Function, served at POST /api/lead
 *
 * SETUP: in the Cloudflare Pages dashboard add an environment variable
 *   LEAD_WEBHOOK_URL = your Make.com (or GHL inbound) webhook URL
 * Nothing secret ever reaches the browser.
 */

const json = (d, s = 200) =>
  new Response(JSON.stringify(d), { status: s, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });

const clean = (v, max = 200) => String(v ?? '').replace(/[\u0000-\u001f]/g, ' ').trim().slice(0, max);

export async function onRequestPost({ request, env }) {
  let body;
  try { body = await request.json(); } catch { return json({ error: 'Bad request.' }, 400); }

  const name  = clean(body.name, 120);
  const email = clean(body.email, 160);
  const phone = clean(body.phone, 40);
  const company = clean(body.company, 160);
  const url   = clean(body.url, 400);

  if (!name || !email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))
    return json({ error: 'A name and a valid email are required.' }, 400);

  const lead = {
    source: 'KLIP Visibility Check',
    name, email, phone, company,
    scanned_url: url,
    scores: body.scores && typeof body.scores === 'object' ? body.scores : null,
    submitted_at: new Date().toISOString(),
    ip_country: request.headers.get('CF-IPCountry') || null
  };

  const hook = env.LEAD_WEBHOOK_URL;
  if (!hook) {
    console.error('LEAD_WEBHOOK_URL is not configured', lead);   // logged so nothing is lost
    return json({ error: 'Lead routing is not configured yet.' }, 503);
  }

  try {
    const r = await fetch(hook, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lead),
      signal: AbortSignal.timeout(8000)
    });
    if (!r.ok) throw new Error('webhook ' + r.status);
  } catch (err) {
    console.error('lead forward failed', err);
    return json({ error: 'We could not send that just now.' }, 502);
  }

  return json({ ok: true });
}

export const onRequestGet = () => json({ error: 'POST only.' }, 405);
