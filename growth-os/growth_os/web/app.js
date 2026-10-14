"use strict";
const CSRF = document.querySelector('meta[name="csrf"]').content;
const $ = (s) => document.querySelector(s);
const LABEL = { youtube: "YouTube", instagram: "Instagram", spotify: "Spotify", apple_podcasts: "Apple Podcasts" };
const GLYPH = { youtube: "YT", instagram: "IG", spotify: "SP", apple_podcasts: "AP" };
const OK = new Set(["ACTIVE"]);
const WAIT = new Set(["AUTHORIZED_UNASSIGNED", "OWNER_VERIFIED", "ASSIGNED", "SYNCING", "CONNECTING", "IMPORT_ONLY"]);
const BAD = new Set(["NEEDS_REAUTH", "SYNC_FAILED", "PERMISSION_LIMITED", "REVOKED"]);
let brand = new URLSearchParams(location.search).get("brand");

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) n.append(k.nodeType ? k : String(k));
  return n;
}

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-CSRF": CSRF }, body: JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.message || data.error || `HTTP ${r.status}`);
  return data;
}

function flash(msg, bad = false) {
  const f = $("#flash");
  f.textContent = msg; f.hidden = !msg; f.classList.toggle("bad", bad);
}

function ago(iso) {
  if (!iso) return "never";
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function ask(title, bodyNodes, okLabel = "Confirm") {
  const d = $("#dlg");
  $("#dlg-title").textContent = title;
  $("#dlg-body").replaceChildren(...bodyNodes);
  $("#dlg-ok").textContent = okLabel;
  d.showModal();
  return new Promise((res) => d.addEventListener("close", () => res(d.returnValue === "ok"), { once: true }));
}

async function act(row, action, body = {}) {
  try {
    const r = await api(`/api/brands/${brand}/accounts/${row}/${action}`, body);
    if (action === "test") {
      const lines = [`First sync OK: ${r.channel_title} (${r.channel_id})`,
        `Videos sampled: ${(r.videos || []).length} · daily rows: ${r.daily_rows} · data through ${r.available_through || "n/a"}`];
      if (r.retention) lines.push(`Retention buckets for ${r.retention.video_id}: ${r.retention.buckets}`);
      if (r.unavailable && r.unavailable.length) lines.push("Unavailable: " + r.unavailable.join("; "));
      flash(lines.join("\n"));
    } else flash("");
  } catch (e) { flash(e.message, true); }
  load();
}

function accountBlock(a, primary) {
  const actions = [];
  const st = a.state;
  if (st === "AUTHORIZED_UNASSIGNED") {
    actions.push(el("button", { class: "gold", onclick: async () => {
      const input = el("input", { autocomplete: "off", spellcheck: "false", "aria-label": "Platform ID" });
      const ok = await ask(`Is this ${$("#brand-name").textContent}'s account?`, [
        el("p", {}, `${LABEL[a.platform]}: `, el("b", {}, a.account_name || "(no name)"), a.handle ? ` ${a.handle}` : ""),
        el("p", {}, "Immutable ID: ", el("code", {}, a.platform_account_id)),
        el("p", {}, "Authorized by: ", a.connected_identity || "unknown"),
        el("p", {}, "Type the ID above to confirm. Nothing is imported until you also assign it."),
        input,
      ], "Verify identity");
      if (ok) act(a.id, "verify", { confirm_id: input.value });
    } }, "Verify identity"));
    actions.push(el("button", { class: "ghost danger", onclick: () => act(a.id, "reject") }, "Not this account"));
  }
  if (st === "OWNER_VERIFIED") actions.push(el("button", { class: "gold", onclick: () => act(a.id, "assign") }, "Assign to brand"));
  if (["ASSIGNED", "ACTIVE", "SYNC_FAILED", "PERMISSION_LIMITED"].includes(st) && a.platform === "youtube")
    actions.push(el("button", { class: st === "ASSIGNED" ? "gold" : "", onclick: () => act(a.id, "test") }, "Test connection"));
  if (st === "ASSIGNED" && ["spotify", "apple_podcasts"].includes(a.platform))
    actions.push(el("button", { class: "gold", onclick: () => act(a.id, "enable_import") }, "Enable import"));
  if (st === "IMPORT_ONLY")
    actions.push(el("button", { disabled: true, title: "CLI for now: growth-os import" }, "Import report (CLI)"));
  if (!["DISCONNECTED", "REVOKED", "REJECTED", "AUTHORIZED_UNASSIGNED"].includes(st))
    actions.push(el("button", { class: "ghost", onclick: async () => {
      if (await ask("Disconnect?", [el("p", {}, "Stops sync and deletes stored tokens. History stays attributed to this brand.")], "Disconnect"))
        act(a.id, "disconnect");
    } }, "Disconnect"));
  if (a.platform === "youtube" && !["REVOKED", "REJECTED", "DISCONNECTED"].includes(st))
    actions.push(el("button", { class: "ghost danger", onclick: async () => {
      if (await ask("Revoke Google access?", [el("p", {}, "Revokes this token at Google and pauses all jobs for this channel.")], "Revoke"))
        act(a.id, "revoke");
    } }, "Revoke"));

  return el("div", { class: primary ? "ablk" : "ablk cand" },
    el("div", { class: "acct" },
      a.avatar_url ? el("img", { src: a.avatar_url, alt: "", referrerpolicy: "no-referrer" }) : null,
      el("div", { style: "min-width:0" }, el("div", { class: "nm" }, a.account_name || "(unnamed)"),
        el("div", { class: "hd" }, a.handle || ""))),
    el("dl", {},
      el("dt", {}, "ID"), el("dd", {}, el("code", {}, a.platform_account_id)),
      el("dt", {}, "Verified"), el("dd", {}, a.verified_by ? `${a.verified_by} · ${ago(a.verified_at)}` : "not yet"),
      el("dt", {}, "Access"), el("dd", {}, a.access_level),
      el("dt", {}, "Last sync"), el("dd", {}, ago(a.last_successful_sync)),
      el("dt", {}, "Data as of"), el("dd", {}, a.data_as_of || "—")),
    a.last_error ? el("div", { class: "err" }, a.last_error) : null,
    el("div", { class: "next" }, "Next: " + a.next_action),
    el("div", { class: "row" }, actions));
}

async function connect(t) {
  try {
    if (t.platform === "youtube") {
      const r = await api(`/api/brands/${brand}/connect/youtube`, {});
      location.href = r.auth_url;
      return;
    }
    if (t.platform === "instagram") throw new Error(t.note);
    const input = el("input", { placeholder: t.platform === "spotify" ? "https://open.spotify.com/show/…" : "Apple Podcasts show ID (numbers)" });
    if (!(await ask(`Find ${LABEL[t.platform]} show`, [
      el("p", {}, "A public match only identifies the show. It is not proof you own it or can see its analytics."), input,
    ], "Find show"))) return;
    await api(`/api/brands/${brand}/connect/${t.platform}`, { show: input.value });
    flash("");
  } catch (e) { flash(e.message, true); }
  load();
}

function tile(t) {
  const cls = OK.has(t.state) ? "ok" : BAD.has(t.state) ? "bad" : WAIT.has(t.state) ? "wait" : "";
  const kids = [
    el("div", { class: "tile-h" }, el("div", { class: "icon" }, GLYPH[t.platform]), el("h3", {}, LABEL[t.platform]),
      el("span", { class: `state ${cls}` }, t.state.replaceAll("_", " "))),
  ];
  if (t.primary) kids.push(accountBlock(t.primary, true));
  for (const c of t.candidates) kids.push(accountBlock(c, !t.primary && t.candidates.length === 1));
  if (!t.primary && !t.candidates.length) kids.push(el("div", { class: "empty" }, "No account connected."));
  if (!t.primary) {
    const label = t.candidates.length ? "Connect another" : "Connect";
    kids.push(el("div", { class: "row" }, el("button", { class: t.candidates.length ? "ghost" : "gold", onclick: () => connect(t) }, label)));
  }
  kids.push(el("div", { class: "note" }, t.note +
    (t.platform === "youtube" && t.client_configured === false ? " OAuth client not configured yet." : "")));
  return el("article", { class: "tile" }, kids);
}

async function load() {
  const list = await api("/api/brands");
  const sel = $("#brand");
  if (!list.length) { $("#brand-name").textContent = "No brands yet"; $("#tiles").replaceChildren(); return; }
  if (!brand || !list.some((b) => b.tenant_id === brand)) brand = list[0].tenant_id;
  sel.replaceChildren(...list.map((b) => el("option", { value: b.tenant_id, selected: b.tenant_id === brand }, b.display_name)));
  $("#brand-name").textContent = list.find((b) => b.tenant_id === brand).display_name;
  const [tiles, diag, audit] = await Promise.all([
    api(`/api/brands/${brand}/tiles`), api(`/api/brands/${brand}/diagnostics`), api(`/api/brands/${brand}/audit`),
  ]);
  $("#tiles").replaceChildren(...tiles.map(tile));
  $("#diag tbody").replaceChildren(...(diag.rows.length ? diag.rows.map((r) => el("tr", {},
    el("td", {}, r.kind), el("td", {}, r.name), el("td", {}, r.n), el("td", {}, r.hits), el("td", {}, r.quota), el("td", {}, r.errors)))
    : [el("tr", {}, el("td", { colspan: 6 }, "No API or model calls today."))]));
  $("#audit").replaceChildren(...audit.map((a) => {
    const d = JSON.parse(a.detail_json || "{}");
    const what = d.to ? ` ${d.platform} ${d.platform_account_id}: ${d.from} → ${d.to}` : d.platform_account_id ? ` ${d.platform || ""} ${d.platform_account_id}` : "";
    return el("li", {}, el("b", {}, a.event), what, ` · ${a.actor} · ${ago(a.at)}`);
  }));
  history.replaceState(null, "", `/?brand=${brand}`);
}

$("#brand").addEventListener("change", (e) => { brand = e.target.value; flash(""); load(); });
$("#new-brand").addEventListener("click", async () => {
  const name = el("input", { placeholder: "Brand name" });
  if (!(await ask("Create brand", [el("p", {}, "Each brand is fully isolated: its own accounts, tokens, data and share links."), name], "Create"))) return;
  try { brand = (await api("/api/brands", { display_name: name.value })).tenant_id; flash(""); }
  catch (e) { flash(e.message, true); }
  load();
});
const disc = new URLSearchParams(location.search).get("discovered");
if (disc) flash(`Google returned ${disc} channel(s). Verify the correct one below; nothing has been imported.`);
load().catch((e) => flash(e.message, true));
