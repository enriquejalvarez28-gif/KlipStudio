"use strict";
/* Klip Growth OS — owner app (vanilla JS, no build step). */
const CSRF = document.querySelector('meta[name="csrf"]').content;
const $ = (s, r = document) => r.querySelector(s);
const C = window.Charts;
const S = { brand: null, brands: [], app: null, cache: {} };

/* ── utilities ─────────────────────────────────────────────────────── */
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(3)) if (k !== null && k !== undefined && k !== false) n.append(k.nodeType ? k : String(k));
  return n;
}
async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF": CSRF }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json().catch(() => ({})) : await r.text();
  if (!r.ok) throw new Error((data && (data.message || data.error)) || `HTTP ${r.status}`);
  return data;
}
const T = (p) => `/api/t/${S.brand}/${p}`;
function toast(msg, bad = false) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false; t.classList.toggle("bad", bad);
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), bad ? 7000 : 3500);
}
function ask(title, nodes, ok = "Confirm") {
  const d = $("#dlg"); $("#dlg-title").textContent = title; $("#dlg-body").replaceChildren(...nodes); $("#dlg-ok").textContent = ok;
  d.showModal();
  return new Promise((res) => d.addEventListener("close", () => res(d.returnValue === "ok"), { once: true }));
}
const nf = C.nf;
const pct = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
const chg = (v) => (v == null ? null : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}%`);
function ago(iso) {
  if (!iso) return "never";
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 0) { const f = -s; return f < 5400 ? `in ${Math.round(f / 60)} min` : f < 172800 ? `in ${Math.round(f / 3600)} h` : `in ${Math.round(f / 86400)} d`; }
  if (s < 90) return "just now"; if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`; return `${Math.round(s / 86400)} d ago`;
}
const dur = (s) => (s == null ? "" : s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`);
const fmtName = (f) => ({ long_form: "Long-form", short_heuristic: "Short" }[f] || f);
const basisTag = (b) => el("span", { class: `tag ${b}`, title: { measured: "Straight from the platform", derived: "Calculated from measured data", ai: "AI draft — review before use", synthetic: "Generated test data" }[b] || "" }, b);
function freshBadge(asOf, label = "Data as of") {
  if (!asOf) return el("span", { class: "fresh none" }, "No data yet");
  const days = (Date.now() - Date.parse(asOf)) / 864e5;
  return el("span", { class: `fresh ${days > 4 ? "stale" : ""}`, title: "YouTube Analytics lags 2–3 days" }, `${label} ${asOf.slice(0, 10)}`);
}
function ph(eyebrow, title, desc, ...actions) {
  return el("div", { class: "ph" }, el("div", {}, el("div", { class: "eyebrow" }, eyebrow), el("h1", {}, title), desc ? el("p", {}, desc) : null),
    actions.length ? el("div", { class: "actions" }, actions) : null);
}
function card(title, right, ...body) {
  return el("section", { class: "card" }, title ? el("div", { class: "card-h" }, el("h2", {}, title), right ? el("div", { class: "r" }, right) : null) : null, body);
}
function seg(options, current, onPick) {
  const wrap = el("div", { class: "seg", role: "group" });
  for (const [v, label] of options) wrap.append(el("button", { class: v == current ? "on" : "", "aria-pressed": v == current ? "true" : "false", onclick: () => onPick(v) }, label));
  return wrap;
}
function emptyState(what, action) {
  return el("div", { class: "callout" }, el("b", {}, what.title), el("div", {}, what.body), action ? el("div", { style: "margin-top:10px" }, action) : null);
}
const NO_DATA = {
  title: "No platform data for this brand yet.",
  body: "Connect and verify accounts in Manage Accounts. Nothing is estimated or filled in: charts appear after the first real sync.",
};
const goAccounts = () => el("a", { class: "btn gold sm", href: "#/accounts" }, "Manage accounts");
const brand = () => S.brands.find((b) => b.tenant_id === S.brand) || {};
function thumbImg(v) { return el("img", { src: v.thumb, alt: "", loading: "lazy", onerror: (e) => e.target.remove() }); }
function vcard(v, extra) {
  return el("a", { class: "vcard", href: `#/episode/${v.asset_id}` },
    el("div", { class: "thumb" }, thumbImg(v), v.duration_s ? el("span", { class: "dur" }, dur(v.duration_s)) : null,
      extra && extra.flag ? el("span", { class: "flag tag ai", style: "background:var(--panel)" }, extra.flag) : null),
    el("div", { class: "vbody" }, el("div", { class: "vtitle" }, v.title),
      el("div", { class: "vstats" },
        el("span", {}, el("b", {}, nf(v.views)), " views"),
        v.ctr != null ? el("span", {}, el("b", {}, pct(v.ctr)), " CTR") : null,
        v.avg_pct_viewed != null ? el("span", {}, el("b", {}, pct(v.avg_pct_viewed)), " viewed") : null),
      el("div", { class: "vstats" }, el("span", {}, fmtName(v.format)), el("span", {}, v.age_days != null ? `${v.age_days} d old` : ""),
        extra && extra.right ? el("span", { style: "margin-left:auto" }, extra.right) : null)));
}
function mini(v, right) {
  return el("a", { class: "mini", href: `#/episode/${v.asset_id}` }, thumbImg(v),
    el("div", { style: "min-width:0;flex:1" }, el("div", { class: "t" }, v.title), el("div", { class: "faint", style: "font-size:12px" }, right)));
}
function kpiTile(k, series, label) {
  const t = el("div", { class: "card kpi" }, el("span", { class: "lab" }, label || k.label),
    el("span", { class: "val" }, k.unit === "pct" ? pct(k.value) : nf(k.value)),
    el("span", { class: `chg ${k.change == null ? "flat" : (k.metric === "subscribersLost" ? -k.change : k.change) > 0.005 ? "up" : (k.metric === "subscribersLost" ? -k.change : k.change) < -0.005 ? "down" : "flat"}` },
      k.note ? k.note : k.change == null ? "no comparable prior period" : `${chg(k.change)} vs prior ${k.days} d`));
  if (series) { const sp = el("div", { class: "sp" }); t.append(sp); requestAnimationFrame(() => C.spark(sp, series)); }
  if (k.quality === "synthetic") t.append(el("span", { class: "tag synthetic", style: "align-self:flex-start;margin-top:6px" }, "synthetic"));
  return t;
}
function checkRow(c) {
  const st = { ok: "ok", warn: "warn", na: "na", info: "na" }[c.status] || "na";
  const val = Array.isArray(c.value) ? (c.value.join(", ") || "none") : c.value === true ? "yes" : c.value === false ? "no" : c.value ?? "—";
  return el("div", { class: "check" }, el("span", { class: `dotst ${st}`, "aria-label": c.status }), el("span", {}, c.label, " ", el("span", { class: "faint" }, `(${val})`)), el("span", { class: "n" }, c.note || ""));
}

/* ── navigation ────────────────────────────────────────────────────── */
const NAV = [
  ["Overview", [["home", "Home", "⌂"], ["brief", "Growth brief", "✦"], ["analytics", "Analytics overview", "◔"]]],
  ["Content", [["episodes", "Episode intelligence", "▦"], ["youtube", "YouTube", "▶"], ["instagram", "Instagram", "◎"], ["podcasts", "Podcasts", "♪"]]],
  ["Labs", [["thumbnails", "Thumbnail lab", "▣"], ["titles", "Title lab", "T"], ["seo", "SEO & discoverability", "⌕"]]],
  ["Growth", [["insights", "Insights", "◆"], ["autopilot", "Autopilot", "⟲"], ["monetization", "Monetization", "$"], ["discovery", "Discovery", "⌖"], ["trends", "Trend radar", "↗"], ["recommendations", "Recommendations", "✦"], ["calendar", "Content calendar", "▤"]]],
  ["Operate", [["reports", "Reports", "⎙"], ["jobs", "Jobs & integrations", "⟳"], ["accounts", "Manage accounts", "⚿"], ["settings", "Settings", "⚙"]]],
];
function renderNav(active) {
  const nav = $("#nav"); nav.replaceChildren();
  for (const [grp, items] of NAV) {
    nav.append(el("div", { class: "grp" }, grp));
    for (const [id, label, ic] of items) {
      const badge = id === "jobs" && S.app && S.app.alerts_open ? el("span", { class: "st bad badge" }, S.app.alerts_open) : null;
      nav.append(el("a", { href: `#/${id}`, class: active === id || (active === "episode" && id === "episodes") ? "on" : "", "aria-current": active === id ? "page" : null, onclick: closeMenu },
        el("span", { class: "ic", "aria-hidden": "true" }, ic), label, badge));
    }
  }
}
function closeMenu() { $("#side").classList.remove("open"); $("#scrim").hidden = true; $("#menu").setAttribute("aria-expanded", "false"); }
$("#menu").addEventListener("click", () => { $("#side").classList.add("open"); $("#scrim").hidden = false; $("#menu").setAttribute("aria-expanded", "true"); });
$("#scrim").addEventListener("click", closeMenu);

function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("kgos.theme", t); } catch (e) { /* storage unavailable */ }
  applyAccent();
}
function applyAccent() {
  const b = brand(); const dark = document.documentElement.dataset.theme !== "light";
  const acc = b.theme && b.theme.accent;
  document.documentElement.style.setProperty("--accent", dark ? (acc || "#CFB53B") : "");
  if (!dark) document.documentElement.style.removeProperty("--accent");
}
$("#theme").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light"));
try { const t = localStorage.getItem("kgos.theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* ignore */ }

$("#brand").addEventListener("change", (e) => {
  S.brand = e.target.value;
  try { localStorage.setItem("kgos.brand", S.brand); } catch (err) { /* ignore */ }
  route();
});

async function loadApp() {
  S.app = await api("/api/app");
  S.brands = S.app.brands;
  const qs = new URLSearchParams(location.search).get("brand");
  let saved = null; try { saved = localStorage.getItem("kgos.brand"); } catch (e) { /* ignore */ }
  S.brand = [qs, S.brand, saved, "ryj-media"].find((x) => x && S.brands.some((b) => b.tenant_id === x)) || (S.brands[0] || {}).tenant_id;
  $("#brand").replaceChildren(...S.brands.map((b) => el("option", { value: b.tenant_id, selected: b.tenant_id === S.brand }, b.display_name + (b.is_demo ? "  (synthetic demo)" : ""))));
  $("#side-foot").replaceChildren(el("div", {}, "Local app · data stays on this computer"), el("div", {}, S.app.ai.cli_found ? "AI drafts: Claude Code CLI" : "AI drafts: off (CLI not found)"));
}
function updateChrome() {
  const b = brand();
  $("#demo-banner").hidden = !b.is_demo;
  applyAccent();
  const pill = $("#runpill");
  const run = S.app && S.app.running && S.app.running[0];
  pill.hidden = !run;
  if (run) pill.textContent = `${run.kind.replaceAll("_", " ")} ${run.progress}% ${run.message || ""}`;
}
setInterval(async () => {
  try { const a = await api("/api/app"); const was = (S.app.running || []).length; S.app = a; updateChrome();
    if (was && !a.running.length && ["jobs", "home"].includes(curPage())) route(true); } catch (e) { /* offline */ }
}, 4000);

/* ── router ────────────────────────────────────────────────────────── */
const curPage = () => (location.hash.replace(/^#\//, "").split("/")[0] || "home");
let routeSeq = 0;
async function route(soft) {
  const [page, arg] = location.hash.replace(/^#\//, "").split("/");
  const p = page || "home";
  renderNav(p); updateChrome();
  const main = $("#main"); const seq = ++routeSeq;
  if (!soft) { main.replaceChildren(el("div", { class: "skel" })); window.scrollTo(0, 0); }
  try {
    const fn = PAGES[p] || PAGES.home;
    const node = await fn(arg);
    if (seq !== routeSeq) return;
    main.replaceChildren(node);
    if (!soft) main.focus({ preventScroll: true });
    document.title = `${(NAV.flatMap((g) => g[1]).find((x) => x[0] === p) || [, "Episode"])[1]} · ${brand().display_name || ""} · Klip Growth OS`;
    requestAnimationFrame(() => main.querySelectorAll("[data-draw]").forEach((n) => n._draw && n._draw()));
  } catch (e) {
    if (seq !== routeSeq) return;
    main.replaceChildren(el("div", { class: "callout" }, el("b", {}, "Couldn't load this page. "), e.message));
  }
}
function drawLater(node, fn) { node.dataset.draw = "1"; node._draw = fn; return node; }
window.addEventListener("hashchange", () => route());
let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => document.querySelectorAll("[data-draw]").forEach((n) => n._draw && n._draw()), 200); });

/* ── pages ─────────────────────────────────────────────────────────── */
const PAGES = {};

PAGES.home = async () => {
  const d = await api(T("home"));
  const b = d.brand; const k28 = d.kpis["28"] || [];
  const byM = Object.fromEntries(k28.map((k) => [k.metric, k]));
  const yt = d.accounts.youtube;
  const wrap = el("div", {});
  wrap.append(ph(b.is_demo ? "Synthetic demo" : "Owner dashboard", b.display_name,
    `Last 28 days on connected platforms. Platforms are shown separately; views, plays and listeners are never added together.`,
    freshBadge(yt.data_as_of), el("button", { class: "btn gold", onclick: () => { sessionSet("brief.run", "1"); location.hash = "#/brief"; } }, "✦ Analyze everything"), el("button", { class: "btn", onclick: async () => { await api("/api/jobs/analytics_sync/run", { tenant_id: S.brand }); toast("Refresh queued"); } }, "↻ Refresh")));
  if (d.alerts.length) wrap.append(el("div", { class: "callout", style: "border-color:var(--bad);margin-bottom:14px" },
    el("b", {}, `${d.alerts.length} job alert(s). `), d.alerts[0].source, ": ", d.alerts[0].message, " ", el("a", { href: "#/jobs" }, "Open job health")));

  if (!k28.length) {
    wrap.append(el("div", { class: "grid g2" },
      card("Get started", null, emptyState(NO_DATA, goAccounts())),
      card("Accounts", null, accountStrip(d.accounts))));
  } else {
    const tiles = el("div", { class: "grid g5" });
    for (const [m, label] of [["views", "YouTube views"], ["estimatedMinutesWatched", "Watch hours"], ["subscribersGained", "Subscribers gained"], ["ctr", "Impressions CTR"], ["averageViewPercentage", "Avg % viewed"]])
      tiles.append(byM[m] ? kpiTile(byM[m], (d.spark[m] || []).slice(-28), label)
        : el("div", { class: "card kpi" }, el("span", { class: "lab" }, label), el("span", { class: "val faint" }, "—"), el("span", { class: "chg flat" }, m === "ctr" ? "not yet available (reach reports pending)" : "not yet available")));
    for (const [p, k] of Object.entries(d.podcasts)) tiles.append(kpiTile(k, k.series.slice(-28), `${p === "spotify" ? "Spotify plays" : "Apple listeners"} (imported)`));
    wrap.append(tiles);
    const chartBox = el("div", {});
    wrap.append(el("div", { class: "grid g3 sec" },
      el("section", { class: "card span2" }, el("div", { class: "card-h" }, el("h2", {}, "Daily YouTube views · 90 days"), el("div", { class: "r" }, basisTag(byM.views && byM.views.quality === "synthetic" ? "synthetic" : "measured"))),
        drawLater(chartBox, () => C.line(chartBox, [{ name: "Views", points: d.spark.views }], { area: true, height: 230, tipX: (x) => x }))),
      card("Accounts", el("a", { class: "btn sm ghost", href: "#/accounts" }, "Manage"), accountStrip(d.accounts))));
  }
  const best = card("Strongest content", el("span", { class: "faint", style: "font-size:12px" }, "views/day since publish"),
    d.best.length ? el("div", { class: "list" }, d.best.map((v) => mini(v, `${nf(v.views_per_day)} views/day · ${fmtName(v.format)}`))) : el("p", { class: "empty" }, "Appears after videos have 7+ days of data."));
  const worst = card("Needs attention", null,
    d.worst.length ? el("div", { class: "list" }, d.worst.map((v) => mini(v, `${nf(v.views_per_day)} views/day · ${fmtName(v.format)}`))) : el("p", { class: "empty" }, "Appears once there are enough videos to compare."));
  const recs = card("Top recommendations", el("a", { class: "btn sm ghost", href: "#/recommendations" }, "All"),
    d.recommendations.length ? el("div", { class: "list" }, d.recommendations.slice(0, 4).map((r) => recItem(r, true))) : el("p", { class: "empty" }, "No open recommendations. The daily review and packaging check add them when the data supports one."));
  const trs = card("Opportunity radar", el("a", { class: "btn sm ghost", href: "#/trends" }, "Open radar"),
    d.trends.length ? el("div", { class: "list" }, d.trends.map((t) => el("div", { class: "li" }, el("div", { class: "score", style: "font-size:18px;min-width:34px" }, Math.round(t.score)),
      el("div", { class: "body" }, el("a", { class: "t", href: t.url, target: "_blank", rel: "noopener noreferrer" }, t.title), el("div", { class: "d" }, `${t.source} · ${ago(t.published_at)} · uncertainty ${t.uncertainty.split(" ")[0]}`)))))
      : el("p", { class: "empty" }, "No trends yet. Trend research runs daily at 06:30, or run it now from Jobs."));
  const jobs = card("Automation", el("a", { class: "btn sm ghost", href: "#/jobs" }, "Jobs"),
    el("div", { class: "list" }, d.schedules.map((s) => el("div", { class: "li" }, el("span", { class: `dotst ${s.last_status === "failed" ? "bad" : s.last_status ? "ok" : "na"}` }),
      el("div", { class: "body" }, el("div", { class: "t", style: "font-weight:500" }, s.name.replaceAll("_", " ")), el("div", { class: "d" }, `next ${ago(s.next_run_at)} · last ok ${ago(s.last_success_at)}`))))));
  wrap.append(el("div", { class: "grid g2 sec" }, best, worst), el("div", { class: "grid g3 sec" }, recs, trs, jobs));
  return wrap;
};

function accountStrip(acc) {
  const L = { youtube: "YouTube", instagram: "Instagram", spotify: "Spotify", apple_podcasts: "Apple Podcasts" };
  return el("div", { class: "list" }, Object.entries(acc).map(([p, a]) => el("div", { class: "li", style: "align-items:center" },
    el("div", { class: "body" }, el("div", { class: "t", style: "font-weight:550" }, L[p]), el("div", { class: "d" }, a.name || "Not connected")),
    stPill(a.state))));
}
function stPill(state) {
  const cls = state === "ACTIVE" ? "ok" : ["NEEDS_REAUTH", "SYNC_FAILED", "PERMISSION_LIMITED", "REVOKED"].includes(state) ? "bad" : state === "NOT_CONNECTED" ? "" : "wait";
  return el("span", { class: `st ${cls}` }, state.replaceAll("_", " "));
}
function recItem(r, compact) {
  const ev = Array.isArray(r.evidence) ? r.evidence : JSON.parse(r.evidence_json || "[]");
  return el("div", { class: "li" }, el("div", { class: "body" },
    el("div", { class: "row" }, el("span", { class: "t" }, r.title)),
    compact ? null : el("div", { class: "d" }, r.detail),
    el("div", { class: "ev" }, basisTag(r.basis), (ev.some((e) => e.peer_median != null) ? ev.filter((e) => e.peer_median != null || /drop/i.test(e.metric)) : ev).slice(-2).map((e) => { const f = /CTR|%/.test(e.metric) ? pct : (x) => nf(x, 2);
      return el("span", {}, `${e.metric}: ${typeof e.value === "number" ? f(e.value) : e.value}${e.peer_median != null ? ` · peers ${f(e.peer_median)}` : ""}${e.percentile != null ? ` · percentile ${e.percentile}` : ""}`); }),
      r.asset_id ? el("a", { class: "btn sm ghost", href: `#/episode/${r.asset_id}` }, "Open") : null)));
}

PAGES.analytics = async () => {
  const days = Number(sessionGet("an.days", 90));
  const [o, p, acc] = await Promise.all([api(T(`overview?days=${days}`)), api(T("podcasts")), api(T("accounts"))]);
  const wrap = el("div", {}, ph("Analytics overview", "Performance across platforms", "Each platform is measured differently, so each keeps its own scale and units.",
    seg([[28, "28 d"], [90, "90 d"], [365, "1 yr"]], days, (v) => { sessionSet("an.days", v); route(true); })));
  if (!o.kpis.length && !Object.values(p).some((x) => Object.keys(x.series).length)) {
    wrap.append(emptyState(NO_DATA, goAccounts())); return wrap;
  }
  const g = el("div", { class: "grid g4" }); o.kpis.forEach((k) => g.append(kpiTile(k, null)));
  wrap.append(el("h2", { style: "margin:4px 0 10px" }, "YouTube"), g);
  const c1 = el("div", {}), c2 = el("div", {}), c3 = el("div", {});
  wrap.append(el("div", { class: "grid g2 sec" },
    el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, "Views per day")), drawLater(c1, () => C.line(c1, [{ name: "Views", points: o.series.views }], { area: true }))),
    el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, "Net subscribers per day")), drawLater(c2, () => C.line(c2, [{ name: "Net subscribers", points: o.net_subscribers, color: "--s2" }], {})))),
    el("div", { class: "grid g2 sec" },
      el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, "Watch time per day (minutes)")), drawLater(c3, () => C.line(c3, [{ name: "Minutes", points: o.series.estimatedMinutesWatched, color: "--s2" }], { area: true }))),
      formatCard(o)));
  const pods = el("div", { class: "grid g2 sec" });
  for (const [pl, x] of Object.entries(p)) {
    const metrics = Object.keys(x.series);
    const box = el("div", {});
    pods.append(el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, pl === "spotify" ? "Spotify" : "Apple Podcasts"), el("div", { class: "r" }, stPill(x.account.state))),
      metrics.length ? drawLater(box, () => C.line(box, metrics.slice(0, 2).map((m, i) => ({ name: m, points: x.series[m], color: ["--s1", "--s2"][i] })), {})) : el("p", { class: "empty" }, x.note),
      metrics.length > 1 ? el("div", { class: "legend" }, metrics.slice(0, 2).map((m, i) => el("span", {}, el("i", { style: `background:var(${["--s1", "--s2"][i]})` }), m))) : null,
      el("div", { class: "foot" }, "Imported reports. Plays and listeners are platform-defined and not comparable to YouTube views.")));
  }
  pods.append(el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, "Instagram"), el("div", { class: "r" }, stPill(acc.instagram.state))),
    el("p", { class: "empty" }, "Instagram insights need a Meta app and an Instagram professional account. See the Instagram page.")));
  wrap.append(el("h2", { style: "margin:26px 0 10px" }, "Podcasts & Instagram"), pods);
  return wrap;
};
function sessionGet(k, d) { try { return sessionStorage.getItem(k) ?? d; } catch (e) { return d; } }
function sessionSet(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* ignore */ } }
function formatCard(o) {
  return card("Shorts vs long-form", el("span", { class: "faint", style: "font-size:12px" }, "medians, videos ≥7 days old"),
    o.formats.length ? el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Format", "Videos", "Views/day", "CTR", "% viewed"].map((h, i) => el("th", { class: i ? "r" : "" }, h)))),
      el("tbody", {}, o.formats.map((f) => el("tr", {}, el("td", {}, fmtName(f.format)), el("td", { class: "r" }, f.count), el("td", { class: "r" }, nf(f.median_views_per_day)), el("td", { class: "r" }, pct(f.median_ctr)), el("td", { class: "r" }, pct(f.median_avg_pct_viewed)))))))
      : el("p", { class: "empty" }, "No videos yet."),
    el("div", { class: "foot" }, "Shorts are identified by length (≤3 min); the API has no Shorts flag."));
}

PAGES.episodes = async () => {
  const vids = await api(T("videos"));
  const st = { q: sessionGet("ep.q", ""), fmt: sessionGet("ep.fmt", "all"), sort: sessionGet("ep.sort", "recent") };
  const wrap = el("div", {}, ph("Episode intelligence", "Episodes", "Every published video with its packaging and performance against comparable videos."));
  if (!vids.length) { wrap.append(emptyState(NO_DATA, goAccounts())); return wrap; }
  const grid = el("div", { class: "vgrid" });
  const count = el("span", { class: "faint", style: "font-size:13px" });
  const draw = () => {
    let xs = vids.filter((v) => (st.fmt === "all" || v.format === st.fmt) && (!st.q || v.title.toLowerCase().includes(st.q.toLowerCase())));
    const key = { recent: (v) => v.published_at, views: (v) => v.views || 0, vpd: (v) => v.views_per_day || 0, ctr: (v) => v.ctr || 0, ret: (v) => v.avg_pct_viewed || 0 }[st.sort];
    xs = xs.slice().sort((a, b) => (key(b) > key(a) ? 1 : -1));
    count.textContent = `${xs.length} of ${vids.length}`;
    grid.replaceChildren(...xs.map((v) => vcard(v, { right: v.vpd_pctile != null ? `p${v.vpd_pctile} vs peers` : "" })));
  };
  const q = el("input", { class: "input", type: "search", placeholder: "Search titles", value: st.q, "aria-label": "Search titles", oninput: (e) => { st.q = e.target.value; sessionSet("ep.q", st.q); draw(); } });
  const f = el("select", { class: "input", "aria-label": "Format", onchange: (e) => { st.fmt = e.target.value; sessionSet("ep.fmt", st.fmt); draw(); } },
    [["all", "All formats"], ["long_form", "Long-form"], ["short_heuristic", "Shorts"]].map(([v, l]) => el("option", { value: v, selected: v === st.fmt }, l)));
  const so = el("select", { class: "input", "aria-label": "Sort", onchange: (e) => { st.sort = e.target.value; sessionSet("ep.sort", st.sort); draw(); } },
    [["recent", "Newest"], ["views", "Most views"], ["vpd", "Views per day"], ["ctr", "Highest CTR"], ["ret", "Highest % viewed"]].map(([v, l]) => el("option", { value: v, selected: v === st.sort }, l)));
  wrap.append(el("div", { class: "filters" }, q, f, so, count, el("a", { class: "btn sm ghost", href: T("export/videos.csv"), style: "margin-left:auto" }, "Export CSV")), grid);
  draw();
  return wrap;
};

PAGES.episode = async (id) => {
  const d = await api(T(`video/${id}`));
  const v = d.video; const m = d.metrics; const pm = d.peers.metrics;
  const wrap = el("div", {});
  wrap.append(el("a", { href: "#/episodes", class: "btn sm ghost", style: "margin-bottom:12px" }, "← Episodes"));
  const kk = (label, val, p) => el("div", { class: "k" }, el("div", { class: "l" }, label), el("div", { class: "v" }, val), p ? el("div", { class: "p" }, p) : null);
  const peerTxt = (x, f = nf) => (x ? `peers ${f(x.peer_median)} · p${x.percentile}` : "no peer comparison");
  wrap.append(el("div", { class: "detail-hero" },
    el("div", { class: "thumb" }, thumbImg(v), v.duration_s ? el("span", { class: "dur" }, dur(v.duration_s)) : null),
    el("div", {}, el("div", { class: "eyebrow", style: "color:var(--accent);font-size:11px;letter-spacing:.16em;text-transform:uppercase;font-weight:700" }, `${fmtName(v.format)} · published ${(v.published_at || "").slice(0, 10)} · ${v.age_days} d ago`),
      el("h1", { style: "font-size:24px;margin:4px 0 6px" }, v.title),
      el("div", { class: "row" }, basisTag(v.quality === "synthetic" ? "synthetic" : "measured"), freshBadge(m._through),
        d.youtube_url ? el("a", { class: "btn sm ghost", href: d.youtube_url, target: "_blank", rel: "noopener noreferrer" }, "Open on YouTube ↗") : null),
      el("div", { class: "kstrip" },
        kk("Views", nf(v.views), pm.views_per_day ? `${nf(v.views_per_day)}/day · peers ${nf(pm.views_per_day.peer_median)} · p${pm.views_per_day.percentile}` : null),
        kk("Impressions", nf(v.impressions), pm.impressions ? `p${pm.impressions.percentile} vs peers` : null),
        kk("Impressions CTR", pct(v.ctr), peerTxt(pm.ctr, pct)),
        kk("Avg % viewed", pct(v.avg_pct_viewed), peerTxt(pm.avg_pct_viewed, pct)),
        kk("Watch time", v.watch_minutes != null ? `${nf(v.watch_hours)} h` : "—", v.watch_minutes != null ? `${nf(v.watch_minutes)} min` : null),
        kk("Avg view duration", v.avg_view_s != null ? dur(Math.round(v.avg_view_s)) : "—", v.duration_s && v.avg_view_s != null ? `of ${dur(v.duration_s)}` : null)),
      el("p", { class: "faint", style: "font-size:12px;margin:8px 0 0" }, `Peer set: ${d.peers.basis} (n=${d.peers.n}).`))));

  const ret = el("div", {});
  wrap.append(el("div", { class: "grid g3 sec" },
    el("section", { class: "card span2" }, el("div", { class: "card-h" }, el("h2", {}, "Audience retention"), el("div", { class: "r" }, basisTag(v.quality === "synthetic" ? "synthetic" : "measured"))),
      drawLater(ret, () => C.line(ret, [{ name: "This video", points: d.retention }].concat(d.benchmark.length ? [{ name: `Typical ${fmtName(v.format)} (median of ${d.benchmark_n})`, points: alignBench(d.retention, d.benchmark), color: "--s3" }] : []), {
        xKey: "x", yfmt: (x) => `${Math.round(x * 100)}%`, xfmt: (x) => (v.duration_s ? dur(Math.round(x * v.duration_s)) : `${Math.round(x * 100)}%`),
        tipX: (x) => (v.duration_s ? `at ${dur(Math.round(x * v.duration_s))}` : `${Math.round(x * 100)}%`), area: !d.benchmark.length, height: 260,
        markers: d.retention_events.map((e) => ({ x: e.x, kind: e.kind, label: e.label })),
        onClick: (x) => { if (d.youtube_url && v.duration_s) window.open(`${d.youtube_url}&t=${Math.round(x * v.duration_s)}s`, "_blank", "noopener"); },
        empty: "No retention curve yet (needs enough views, or still processing). Curves fill in about 15 videos per sync." })),
      retentionEvents(d, v),
      el("div", { class: "foot" }, d.retention_note, " ", d.transcript_note || `Transcript linked (${d.transcript.file}); markers show what was said there.`), rewatchBox(d.rewatch, v)),
    card("Traffic sources", basisTag(v.quality === "synthetic" ? "synthetic" : "measured"), (() => { const b = el("div", {}); return drawLater(b, () => C.bars(b, Object.entries(d.traffic_sources).map(([k, x]) => ({ label: k.replaceAll("_", " ").toLowerCase(), v: x })), { empty: "Fetched for the most-changed videos each sync." })); })())));

  wrap.append(el("div", { class: "grid g3 sec" },
    card("Title check", null, el("div", { class: "checks" }, d.title_checks.map(checkRow)),
      d.search_terms.length ? el("div", { class: "foot" }, "Top YouTube search terms: ", d.search_terms.slice(0, 6).map((s) => s.term).join(" · ")) : null),
    card("Thumbnail (measured)", null, thumbFeatures(d.thumbnail)),
    card("SEO & discoverability", null, el("div", { class: "checks" }, d.seo.map(checkRow)))));

  wrap.append(thumbStudio(v));
  if (v.format === "long_form") wrap.append(conceptsCard(v));
  wrap.append(el("div", { class: "grid g2 sec" }, aiTitlesCard(v, d.ai_titles), aiThumbCard(v, d.ai_thumbnail)));

  const hist = d.history;
  wrap.append(el("div", { class: "grid g2 sec" },
    card("Title & thumbnail history", null, hist.length ? el("div", { class: "list" }, hist.map((h) => el("div", { class: "li" },
      el("span", { class: "tag" }, h.field), el("div", { class: "body" }, el("div", {}, h.field === "thumbnail" ? `image ${h.value}` : h.value), el("div", { class: "d" }, `first seen ${h.observed_at.slice(0, 16).replace("T", " ")} · ${h.source}`)))))
      : el("p", { class: "empty" }, "No changes recorded yet."),
      el("div", { class: "foot" }, "Changes are logged with timestamps. Later performance is shown alongside, but a change isn't treated as the cause without a proper experiment.")),
    card("Recommendations for this video", null, d.recommendations.length ? el("div", { class: "list" }, d.recommendations.slice(0, 4).map((r) => recItem(r, true))) : el("p", { class: "empty" }, "None open."))));
  return wrap;
};
function thumbFeatures(t) {
  if (!t.features) return el("p", { class: "empty" }, "Thumbnail not analysed yet.");
  const f = t.features;
  const row = (l, v, hint) => el("div", { class: "pct" }, el("span", { class: "muted", style: "width:110px" }, l), el("span", { class: "meter" }, el("i", { style: `width:${Math.round(Math.min(1, v) * 100)}%` })), el("span", { class: "num", title: hint }, v.toFixed(2)));
  return el("div", { class: "checks" },
    row("Brightness", f.luminance), row("Contrast", f.contrast * 3, "scaled ×3 for display"), row("Colorfulness", f.colorfulness * 2, "scaled ×2"),
    row("Saturation", f.saturation), row("Detail / edges", f.edge_density * 4, "scaled ×4"), row("Focal contrast", f.focal_contrast * 4, "center vs whole, scaled ×4"),
    el("div", { class: "row", style: "margin-top:4px" }, el("span", { class: "muted", style: "font-size:12.5px" }, "Dominant colors"), el("span", { class: "swatches" }, f.dominant_colors.map((c) => el("i", { style: `background:${c.hex}`, title: `${c.hex} · ${Math.round(c.share * 100)}%` })))),
    el("div", { class: "foot" }, "Not measured: ", f.unavailable.join("; "), "."));
}
function aiBox(kind, v, cached, render) {
  const body = el("div", {});
  const meta = el("div", { class: "foot" });
  const show = (res) => {
    body.replaceChildren(render(res.output));
    meta.replaceChildren(basisTag("ai"), ` ${res.meta ? res.meta.model : ""} · ${res.meta && res.meta.cached ? "cached" : "generated"} ${ago(res.meta ? res.meta.created_at : null)} · drafts for your review, not predictions.`);
  };
  const run = async (refresh) => {
    btn.disabled = true; body.replaceChildren(el("div", { class: "skel", style: "height:80px" }));
    try { show(await api(T(`ai/${kind}/${v.asset_id}`), { refresh })); } catch (e) { body.replaceChildren(el("p", { class: "empty" }, e.message)); }
    btn.disabled = false; btn.textContent = "Regenerate";
  };
  const btn = el("button", { class: "btn sm", onclick: () => run(!!cached || btn.textContent === "Regenerate") }, cached ? "Regenerate" : "Generate");
  if (cached) show({ output: cached.output, meta: { model: cached.model, cached: true, created_at: cached.created_at } });
  else body.append(el("p", { class: "empty" }, "Uses the evidence above (CTR vs peers, search terms, measured image features). Runs on your Claude Code subscription and is cached."));
  return { body, meta, btn };
}
function aiTitlesCard(v, cached) {
  const x = aiBox("titles", v, cached, (o) => el("div", {},
    (o.titles || []).map((t) => el("div", { class: "alt" }, el("div", { class: "s" }, (t.strategy || "").replaceAll("_", " ")), el("div", { class: "tt2" }, t.title, el("span", { class: "faint", style: "font-weight:400;font-size:12px" }, `  ${t.title.length} chars`)), el("div", { class: "muted", style: "font-size:13px" }, t.why))),
    o.keep_reason ? el("p", { class: "muted", style: "font-size:13px" }, el("b", {}, o.keep_current ? "Keep current? Yes. " : "Keep current? Consider a change. "), o.keep_reason) : null));
  return card("Alternative titles", x.btn, x.body, x.meta);
}
function conceptsCard(v) {
  const box = el("div", {}, el("p", { class: "faint" }, "Loading…"));
  const show = (d) => {
    box.replaceChildren();
    if (!d) { box.append(el("p", { class: "empty" }, "No concepts yet for this episode.")); return; }
    if (d.transcript_note) box.append(el("div", { class: "note", style: "font-size:12.5px" }, d.transcript_note));
    box.append(el("div", { class: "grid g3", style: "gap:10px" }, d.concepts.map((c) => {
      const pick = d.picks.includes(c.file);
      const m = c.moment_detail;
      return el("div", { class: "card", style: "padding:8px" },
        el("a", { href: c.url, target: "_blank", rel: "noopener" }, el("img", { src: c.url, alt: c.label, style: "width:100%;border-radius:6px" })),
        el("div", { class: "row", style: "gap:6px;margin-top:6px;flex-wrap:wrap" }, el("span", { class: "tag" }, c.label), pick ? el("span", { class: "st ok" }, "Test & Compare pick") : null),
        el("div", { style: "font-size:13px;margin-top:4px" }, c.angle || ""),
        m ? el("div", { class: "faint", style: "font-size:12px;margin-top:4px" }, `${dur(m.t)} · ${m.type}${m.quote ? ` · “${m.quote}”` : ""}`) : null);
    })), el("p", { class: "faint", style: "font-size:12px" }, d.note));
  };
  api(T(`concepts/${v.asset_id}`)).then((r) => show(r.latest)).catch(() => show(null));
  const btn = el("button", { class: "btn sm", onclick: async (e) => { e.target.disabled = true; e.target.textContent = "Reading the episode…"; try { show((await api(T(`concepts/${v.asset_id}`), {})).latest); } catch (x) { toast(x.message, true); } e.target.disabled = false; e.target.textContent = "Generate 5 concepts"; } }, "Generate 5 concepts");
  return card("Thumbnail concepts (5 distinct, 3 picks for Test & Compare)", btn, box);
}
function thumbStudio(v) {
  const box = el("section", { class: "card sec" }, el("div", { class: "card-h" }, el("h2", {}, "Thumbnail studio"), el("div", { class: "r faint", style: "font-size:12px" }, "RYJ style · local previews only")), el("p", { class: "empty" }, "Loading…"));
  (async () => {
    let d; try { d = await api(T(`thumbs/${v.asset_id}`)); } catch (e) { box.lastChild.textContent = e.message; return; }
    const fmtSel = el("select", { class: "input", "aria-label": "Thumbnail format" }, Object.entries(d.formats).map(([k, l]) =>
      el("option", { value: k, selected: k === d.recommended, disabled: k !== "guest" && !d.hosts_available.length }, k !== "guest" && !d.hosts_available.length ? `${l} (add host photos)` : l)));
    const hA = el("input", { class: "input", value: d.default_headlines[0], "aria-label": "Headline A", style: "flex:1;min-width:220px" });
    const hB = el("input", { class: "input", value: d.default_headlines[1], "aria-label": "Headline B", style: "flex:1;min-width:220px" });
    const cred = el("input", { class: "input", placeholder: "Optional credential pill, e.g. EX-NATIONAL TEAM GYMNAST", "aria-label": "Credential", style: "flex:1;min-width:220px" });
    const out = el("div", {});
    const show = (r) => out.replaceChildren(
      el("img", { src: r.sheet || r.sheet_url, alt: "Current thumbnail next to variants A and B, full and phone size", style: "width:100%;border-radius:10px;border:1px solid var(--line);margin-top:10px" }),
      el("div", { class: "row", style: "gap:8px;margin-top:8px;flex-wrap:wrap" }, (r.variants || []).map((x) => el("a", { class: "btn sm ghost", href: x.url, target: "_blank", rel: "noopener", download: x.file }, `Open ${x.file.split("-").pop().replace(".jpg", "")} (1280×720)`)),
        el("button", { class: "btn sm", onclick: async () => { await api(T("experiments"), { asset_id: v.asset_id, method: "native", status: "planned", variants: (r.variants || []).map((x) => ({ format: x.format, label: x.headline, file: x.file })) }); toast("Experiment recorded as planned"); } }, "Record as planned A/B test")),
      el("p", { class: "faint", style: "font-size:12px;margin:6px 0 0" }, r.source || "", " ", r.approval || ""));
    const go = el("button", { class: "btn gold", onclick: async () => {
      go.disabled = true; go.textContent = "Rendering…";
      try { show(await api(T(`thumbs/${v.asset_id}/previews`), { headlines: [hA.value, hB.value], format: fmtSel.value, credential: cred.value })); }
      catch (e) { toast(e.message, true); } finally { go.disabled = false; go.textContent = "Render previews"; }
    } }, "Render previews");
    box.replaceChildren(box.firstChild,
      el("div", { class: "kv", style: "margin:0 0 10px" }, el("dt", {}, "Recommended format"), el("dd", {}, el("b", {}, d.label), ` — ${d.why}`),
        el("dt", {}, "Evidence"), el("dd", {}, d.evidence), d.test_format ? el("dt", {}, "Worth testing") : null, d.test_format ? el("dd", {}, d.formats[d.test_format]) : null,
        el("dt", {}, "Current (your tag)"), el("dd", {}, d.current_format ? d.formats[d.current_format] : "not tagged yet — tag it in the Thumbnail lab")),
      el("div", { class: "row", style: "gap:8px;flex-wrap:wrap" }, hA, hB),
      el("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-top:8px" }, cred, fmtSel, go),
      el("p", { class: "faint", style: "font-size:12px;margin:6px 0 0" }, "Use / to break lines and *word* for the gold emphasis (default: last line gold). Keep the words faithful to what was said."),
      out,
      el("ul", { class: "faint", style: "font-size:12px;margin:10px 0 0;padding-left:18px" }, d.rules.map((x) => el("li", {}, x))));
    if (d.previews.length) show(d.previews[0]);
  })();
  return box;
}
function aiThumbCard(v, cached) {
  const x = aiBox("thumbnail", v, cached, (o) => el("div", {},
    (o.concepts || []).map((c) => el("div", { class: "alt" }, el("div", { class: "tt2" }, c.name, c.headline ? el("span", { class: "tag", style: "margin-left:8px" }, `“${c.headline}”`) : null),
      el("div", { class: "muted", style: "font-size:13px" }, c.composition), el("div", { class: "faint", style: "font-size:12.5px" }, `Colors: ${c.colors} · Addresses: ${c.addresses}`))),
    (o.experiments || []).length ? el("div", { class: "alt" }, el("div", { class: "s" }, "Experiments to run"), o.experiments.map((e) => el("div", { style: "font-size:13px;margin-top:4px" }, el("b", {}, e.what), ` — ${e.how} Measure: ${e.measure}`))) : null));
  return card("Thumbnail concepts to test", x.btn, x.body, x.meta,
    el("div", { class: "foot" }, "Concepts only. Published thumbnails are never replaced without your approval; compare variants with YouTube Studio's Test & Compare where available."));
}

const COUNTRY = (() => { try { const dn = new Intl.DisplayNames(["en"], { type: "region" }); return (c) => { try { return dn.of(c) || c; } catch (e) { return c; } }; } catch (e) { return (c) => c; } })();
const prettyDim = (x) => ({ SUBSCRIBED: "Subscribers", UNSUBSCRIBED: "Not subscribed", MOBILE: "Phone", DESKTOP: "Computer", TV: "TV", TABLET: "Tablet", GAME_CONSOLE: "Game console", UNKNOWN_PLATFORM: "Unknown" }[x] || x.replaceAll("_", " ").toLowerCase());
function growthSection(o) {
  const fc = o.formats_compare || { types: [] }, sc = o.subscriber_contribution || { items: [] }, tt = o.traffic_over_time || { series: [] };
  const fmtRows = fc.types.map((t) => el("tr", {}, el("td", {}, t.label), el("td", { class: "r" }, nf(t.views)), el("td", { class: "r" }, nf(t.watch_hours)),
    el("td", { class: "r" }, nf(t.videos)), el("td", { class: "r" }, pct(t.median_pct_viewed)), el("td", { class: "r" }, t.median_avg_view_s != null ? dur(t.median_avg_view_s) : "—"), el("td", { class: "r" }, nf(t.subs_gained_lifetime))));
  const sb = el("div", {}), tr = el("div", {}), ct = el("div", {}), ch = el("div", {});
  const pal = ["--s1", "--s2", "--s3", "--s4", "--s5"];
  const tdat = o.ctype_trend || [];
  return el("div", {},
    o.freshness_strip ? el("div", { class: "fresh sec" }, o.freshness_strip.map((f) => el("span", { title: f.note || "" }, el("b", {}, f.source), " ", f.as_of ? f.as_of.slice(0, 16).replace("T", " ") : "—"))) : null,
    el("div", { class: "grid g2 sec" },
      card("Daily views: Shorts vs long-form", null, drawLater(ct, () => C.line(ct, [{ name: "Shorts", points: tdat.map((x) => ({ d: x.d, v: x.shorts_views })), color: "--s3" }, { name: "Long-form", points: tdat.map((x) => ({ d: x.d, v: x.long_views })), color: "--s1" }], { height: 220, tipX: (x) => x, empty: "Fills in after the next sync." }))),
      card("Daily watch hours: Shorts vs long-form", null, drawLater(ch, () => C.line(ch, [{ name: "Shorts", points: tdat.map((x) => ({ d: x.d, v: x.shorts_hours })), color: "--s3" }, { name: "Long-form", points: tdat.map((x) => ({ d: x.d, v: x.long_hours })), color: "--s1" }], { height: 220, tipX: (x) => x, empty: "Fills in after the next sync." })))),
    el("section", { class: "card sec" }, el("div", { class: "card-h" }, el("h2", {}, "Shorts vs long-form"), el("div", { class: "r faint", style: "font-size:12px" }, fc.as_of ? `views & watch hours: last ${fc.days} days to ${fc.as_of}` : "split arrives with the next sync")),
      el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["", `Views (${fc.days} d)`, `Watch hrs (${fc.days} d)`, "Videos", "Median % viewed", "Median avg view", "Subs gained (lifetime)"].map((h, i) => el("th", { class: i ? "r" : "" }, h)))), el("tbody", {}, fmtRows))),
      el("div", { class: "foot" }, "Long-form watch hours count toward monetization; Shorts watch hours don't. See the Monetization page.")),
    el("div", { class: "grid g2 sec" },
      card("Subscribers gained by video", el("span", { class: "faint", style: "font-size:12px" }, `${nf(sc.total)} total`),
        drawLater(sb, () => C.bars(sb, sc.items.map((x) => ({ label: x.title.length > 46 ? x.title.slice(0, 44) + "…" : x.title, v: x.subs, note: `${fmtName(x.format)} · ${x.per_1k_views ?? "—"} subs per 1,000 views` })), { color: "--s2", empty: "No per-video subscriber data yet." }))),
      card("Traffic sources over time (weekly views)", null, drawLater(tr, () => C.line(tr, tt.series.map((s, i) => ({ name: s.source.replaceAll("_", " ").toLowerCase(), points: s.points, color: pal[i % pal.length] })), { height: 230, tipX: (x) => `week of ${x}`, empty: "Fills in after the next sync." })))));
}
function audienceSection(a) {
  const head = el("div", { class: "card-h" }, el("h2", {}, "Audience · last 90 days"), el("div", { class: "r" }, basisTag("measured")));
  if (!a || !a.available) return el("section", { class: "card sec" }, head, el("p", { class: "empty" }, "Fills in after the next YouTube sync."));
  const pc = (v) => `${v.toFixed(1)}%`;
  const ag = el("div", {}), gd = el("div", {}), dv = el("div", {});
  const subRows = a.subscribed.map((r) => el("tr", {}, el("td", {}, prettyDim(r.label)), el("td", { class: "r" }, pc(r.share_pct)), el("td", { class: "r" }, nf(r.watch_hours)), el("td", { class: "r" }, r.avg_view_s != null ? dur(Math.round(r.avg_view_s)) : "—")));
  const ctRows = a.country.map((r) => el("tr", {}, el("td", {}, COUNTRY(r.label)), el("td", { class: "r" }, nf(r.views)), el("td", { class: "r" }, pc(r.share_pct)), el("td", { class: "r" }, nf(r.watch_hours))));
  return el("div", {},
    el("div", { class: "grid g3 sec" },
      card("Age (signed-in viewers)", null, drawLater(ag, () => C.bars(ag, a.age.map((r) => ({ label: r.label, v: r.pct })), { fmt: pc, empty: "YouTube hasn't released age data yet (too few signed-in viewers)." }))),
      card("Gender (signed-in viewers)", null, drawLater(gd, () => C.bars(gd, a.gender.map((r) => ({ label: r.label, v: r.pct })), { fmt: pc, color: "--s2", empty: "Not released yet." }))),
      card("Device", null, drawLater(dv, () => C.bars(dv, a.device.map((r) => ({ label: prettyDim(r.label), v: r.share_pct, note: `${nf(r.watch_hours)} h watched · avg ${r.avg_view_s != null ? dur(Math.round(r.avg_view_s)) : "—"}` })), { fmt: pc })))),
    el("div", { class: "grid g2 sec" },
      card("Subscribers vs not", null, el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["", "Share of views", "Watch hrs", "Avg view"].map((h, i) => el("th", { class: i ? "r" : "" }, h)))), el("tbody", {}, subRows))),
        el("div", { class: "foot" }, "How much of the viewing comes from people already subscribed. A low subscriber share means the algorithm is bringing in new people.")),
      card("Top countries", null, el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Country", "Views", "Share", "Watch hrs"].map((h, i) => el("th", { class: i ? "r" : "" }, h)))), el("tbody", {}, ctRows))))),
    el("p", { class: "faint", style: "font-size:12px;margin:6px 0 0" }, a.note));
}

PAGES.youtube = async () => {
  const [o, vids, acc, aud, coh] = await Promise.all([api(T("overview?days=90")), api(T("videos")), api(T("accounts")), api(T("audience")), api(T("cohorts"))]);
  const a = acc.youtube;
  const wrap = el("div", {}, ph("YouTube intelligence", a.name || "YouTube", a.id ? `Channel ${a.id}` : "No channel connected yet.", stPill(a.state), freshBadge(a.data_as_of)));
  if (!vids.length && !o.kpis.length) { wrap.append(emptyState(NO_DATA, goAccounts())); return wrap; }
  const g = el("div", { class: "grid g4" }); o.kpis.forEach((k) => g.append(kpiTile(k, (o.series[k.metric] || []).slice(-28))));
  wrap.append(g);
  const t1 = el("div", {}), ts = el("div", {}), sc = el("div", {});
  const scat = vids.filter((v) => v.ctr != null && v.avg_pct_viewed != null && v.format === "long_form").map((v) => ({ x: v.ctr, y: v.avg_pct_viewed, label: v.title, id: v.asset_id }));
  wrap.append(el("div", { class: "grid g2 sec" },
    el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, "Traffic sources"), el("div", { class: "r faint", style: "font-size:12px" }, "views")),
      drawLater(ts, () => C.bars(ts, Object.entries(o.traffic_sources).map(([k, v]) => ({ label: k.replaceAll("_", " ").toLowerCase(), v })), { color: "--s2" })), el("div", { class: "foot" }, o.traffic_note)),
    el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, "Click vs hold (long-form)")),
      drawLater(sc, () => C.scatter(sc, scat, { xLabel: "Impressions CTR %", yLabel: "Avg % viewed", xfmt: (x) => `${x.toFixed(1)}%`, yfmt: (y) => `${Math.round(y)}%`, onClick: (p) => (location.hash = `#/episode/${p.id}`) })),
      el("div", { class: "foot" }, "Each dot is a video. Bottom-left videos lose people both before and after the click."))),
    el("div", { class: "grid g2 sec" }, el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, "Average view duration (s)")), drawLater(t1, () => C.line(t1, [{ name: "Seconds", points: o.series.averageViewDuration, color: "--s2" }], {}))), formatCard(o)));
  wrap.append(growthSection(o));
  wrap.append(cohortSection(coh));
  wrap.append(audienceSection(aud));
  const rows = vids.slice().sort((x, y) => (y.views_per_day || 0) - (x.views_per_day || 0));
  wrap.append(el("section", { class: "card sec" }, el("div", { class: "card-h" }, el("h2", {}, "All videos"), el("div", { class: "r" }, el("a", { class: "btn sm ghost", href: T("export/videos.csv") }, "CSV"))),
    el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Video", "Format", "Age", "Views/day", "Watch hrs", "Avg view", "% viewed", "Rewatch peak", "Impr.", "CTR"].map((h, i) => el("th", { class: i > 1 ? "r" : "" }, h)))),
      el("tbody", {}, rows.map((v) => el("tr", { class: "click", onclick: () => (location.hash = `#/episode/${v.asset_id}`) },
        el("td", { style: "max-width:360px" }, v.title), el("td", {}, fmtName(v.format)), el("td", { class: "r" }, `${v.age_days} d`), el("td", { class: "r" }, nf(v.views_per_day)),
        el("td", { class: "r" }, nf(v.watch_hours)), el("td", { class: "r" }, v.avg_view_s != null ? dur(Math.round(v.avg_view_s)) : "—"),
        el("td", { class: "r" }, pct(v.avg_pct_viewed)), el("td", { class: "r", title: "Highest audienceWatchRatio on the retention curve. Above 1.00x = that moment was replayed or scrubbed back to." }, v.rewatch_peak != null ? `${v.rewatch_peak.toFixed(2)}x` : "—"),
        el("td", { class: "r" }, nf(v.impressions)), el("td", { class: "r" }, pct(v.ctr))))))),
    el("div", { class: "foot" }, "Watch hours and average view duration are lifetime, from YouTube Analytics. Rewatch peak above 1.00x means part of the video was replayed or scrubbed back to; retention curves fill in a few videos per sync.")));
  return wrap;
};

function cohortSection(c) {
  const cell = (x) => (x ? el("td", { class: "r" }, nf(x.views), el("div", { class: "faint", style: "font-size:11px" }, `${nf(x.watch_hours)} h`)) : el("td", { class: "r faint" }, "—"));
  return el("section", { class: "card sec" }, el("div", { class: "card-h" }, el("h2", {}, "Launch cohorts: views at day 1 / 3 / 7 / 28")),
    c.items.length ? el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" },
      el("thead", {}, el("tr", {}, ["Video", "Published", ...c.points.map((n) => `Day ${n}`)].map((h, i) => el("th", { class: i > 1 ? "r" : "" }, h)))),
      el("tbody", {}, c.items.map((it) => el("tr", {}, el("td", {}, el("a", { href: `#/episode/${it.asset_id}` }, it.title), el("div", { class: "faint", style: "font-size:11px" }, fmtName(it.format))),
        el("td", {}, it.published_at), ...c.points.map((n) => cell(it.points[String(n)]))))))) : el("p", { class: "empty" }, "Per-video launch data is collected a few videos per sync; it fills in over the next syncs."),
    el("div", { class: "foot" }, c.note));
}
function alignBench(curve, bench) {
  // Benchmark points matched to this video's x positions (nearest bucket) so tooltips line up.
  if (!bench.length) return [];
  return curve.map((p) => { let b = bench[0]; for (const q of bench) if (Math.abs(q.x - p.x) < Math.abs(b.x - p.x)) b = q; return { x: p.x, v: b.v }; });
}
function retentionEvents(d, v) {
  const evs = d.retention_events || [];
  if (!evs.length) return null;
  const at = (e) => (e.t != null ? dur(e.t) : `${Math.round(e.x * 100)}%`);
  return el("div", { class: "evlist" }, evs.map((e) => el("div", { class: "ev" },
    el("span", { class: `k ${e.kind}` }, e.kind),
    d.youtube_url && e.t != null ? el("a", { class: "t", href: `${d.youtube_url}&t=${e.t}s`, target: "_blank", rel: "noopener", title: "Open the video at this moment" }, at(e)) : el("span", { class: "t" }, at(e)),
    el("span", {}, e.label, e.baseline != null ? el("span", { class: "faint" }, ` · typical here ${Math.round(e.baseline * 100)}%, this video ${Math.round(e.value * 100)}%`) : null),
    el("span", { class: "faint", style: "font-size:11.5px" }, `${e.confidence} confidence`),
    e.transcript ? el("div", { class: "tx" }, el("span", { class: "faint" }, `${dur(e.transcript.from)}–${dur(e.transcript.to)}: `), `“${e.transcript.text}”`) : null)));
}
function rewatchBox(r, v) {
  if (!r) return null;
  const items = [];
  if (r.loops_pct != null) items.push(["Loop rate (Shorts)", r.loops_pct > 0 ? `+${r.loops_pct.toFixed(1)}% beyond one full watch` : "no looping"]);
  if (r.has_curve) {
    items.push(["Rewatch peak", `${r.peak_ratio.toFixed(2)}x at ${r.peak_at_pct}%${v.duration_s ? ` (${dur(Math.round(r.peak_at_pct / 100 * v.duration_s))})` : ""}`]);
    items.push(["Share of the video replayed (>1x)", `${r.rewatched_share_pct}%`]);
    if (r.still_watching_at_10pct != null) items.push(["Still watching at 10% / 50%", `${r.still_watching_at_10pct}% / ${r.still_watching_at_50pct ?? "—"}%`]);
    if (r.biggest_drop_at_pct != null) items.push(["Biggest drop", `${r.biggest_drop_pts} pts at ${r.biggest_drop_at_pct}%${v.duration_s ? ` (${dur(Math.round(r.biggest_drop_at_pct / 100 * v.duration_s))})` : ""}`]);
  }
  if (!items.length) return el("div", { class: "foot" }, "Rewatch data appears once this video's retention curve is fetched.");
  return el("div", { class: "kv", style: "margin-top:10px" }, items.flatMap(([a, b]) => [el("dt", {}, a), el("dd", {}, b)]));
}
function meterRow(label, pctv, value, goal, note) {
  return el("div", { style: "margin:10px 0" },
    el("div", { style: "display:flex;justify-content:space-between;gap:8px;font-size:13px" }, el("span", {}, label), el("b", {}, `${value} / ${goal}`)),
    el("div", { class: "meter", style: "margin-top:4px" }, el("i", { style: `width:${Math.max(1, pctv)}%` })),
    note ? el("div", { class: "faint", style: "font-size:12px;margin-top:3px" }, note) : null);
}

PAGES.monetization = async () => {
  const m = await api(T("monetization"));
  const wrap = el("div", {}, ph("YouTube Partner Program", "Monetization", "Where the channel stands against YouTube's two monetization tiers, from your own analytics. YouTube Studio → Earn is the official count."));
  if (!m.available) { wrap.append(emptyState({ title: "No Shorts vs long-form data yet.", body: "It fills in after the next YouTube sync." }, el("a", { class: "btn sm", href: "#/jobs" }, "Jobs"))); return wrap; }
  const g = el("div", { class: "grid g4" });
  [["Subscribers", nf(m.subscribers), `as of ${m.subscribers_as_of}`], ["Long-form watch hours (365 d)", nf(m.long_form_watch_hours_365d), `+${m.pace.long_form_hours_per_day} h/day lately`],
   ["Shorts views (90 d)", nf(m.shorts_views_90d), `+${nf(m.pace.shorts_views_per_day)}/day lately`], ["Public uploads (90 d)", nf(m.uploads_90d), `data as of ${m.as_of}`]]
    .forEach(([l, v, p]) => g.append(el("div", { class: "card kpi" }, el("div", { class: "l faint", style: "font-size:12px" }, l), el("div", { style: "font-size:26px;font-weight:700;margin:4px 0" }, v), el("div", { class: "faint", style: "font-size:12px" }, p))));
  wrap.append(g);
  const eta = (d) => (d == null ? "" : `about ${nf(d)} days at the current pace`);
  const tiers = el("div", { class: "grid g2 sec" }, m.tiers.map((t) => el("section", { class: "card" },
    el("div", { class: "card-h" }, el("h2", {}, t.name), el("div", { class: "r" }, el("span", { class: `st ${t.eligible_by_numbers ? "ok" : "warn"}` }, t.eligible_by_numbers ? "numbers met" : "not yet"))),
    el("p", { class: "muted", style: "font-size:13px;margin:0 0 6px" }, `Unlocks: ${t.unlocks}`),
    meterRow("Subscribers", t.subs_pct, nf(m.subscribers), nf(t.subs), t.subs_gap ? `${nf(t.subs_gap)} to go` : "met"),
    t.uploads_90d ? meterRow("Public uploads, last 90 days", Math.min(100, 100 * m.uploads_90d / t.uploads_90d), nf(m.uploads_90d), t.uploads_90d, m.uploads_90d >= t.uploads_90d ? "met" : "") : null,
    el("div", { class: "faint", style: "font-size:12px;margin-top:8px;text-transform:uppercase;letter-spacing:.08em" }, "Then either path" + (t.closest_path === "watch_hours" ? " (closest: watch hours)" : " (closest: Shorts views)")),
    meterRow("Long-form watch hours, last 365 days", t.watch_hours_pct, nf(m.long_form_watch_hours_365d), nf(t.watch_hours_365d), t.watch_hours_gap ? `${nf(t.watch_hours_gap)} h to go · ${eta(t.days_to_watch_hours_at_pace)}` : "met"),
    meterRow("Shorts views, last 90 days", t.shorts_views_pct, nf(m.shorts_views_90d), nf(t.shorts_views_90d), t.shorts_views_gap ? `${nf(t.shorts_views_gap)} to go · ${eta(t.days_to_shorts_views_at_pace)}` : "met"))));
  wrap.append(tiers);
  wrap.append(el("section", { class: "card sec" }, el("div", { class: "card-h" }, el("h2", {}, "Read before you apply")),
    el("ul", { style: "margin:0;padding-left:18px;line-height:1.7;font-size:13.5px" }, m.notes.map((n) => el("li", {}, n)),
      el("li", {}, `Shorts watch time in the last 90 days: ${nf(m.shorts_watch_hours_90d)} h (doesn't count toward the watch-hour goal).`)),
    el("div", { class: "foot" }, "Sources: ", m.sources.map((u, i) => el("a", { href: u, target: "_blank", rel: "noopener", style: "margin-right:10px" }, i ? "Expanded YPP" : "YPP overview")))));
  return wrap;
};

PAGES.brief = async () => {
  const run = sessionGet("brief.run", "") === "1"; sessionSet("brief.run", "");
  const wrap = el("div", {});
  const go = async (btn, force) => {
    btn.disabled = true; const old = btn.textContent; btn.textContent = "Analyzing all dashboards… (up to a minute)";
    try { await api(T("brief"), { force }); route(true); } catch (e) { toast(e.message, true); btn.disabled = false; btn.textContent = old; }
  };
  const runBtn = el("button", { class: "btn gold", onclick: (e) => go(e.target, false) }, "✦ Analyze everything");
  const freshBtn = el("button", { class: "btn ghost", onclick: (e) => go(e.target, true) }, "Re-run fresh");
  wrap.append(ph("Growth brief", "What's happening and what to do next", "One click reads every dashboard (views, watch time, retention, search terms, audience, traffic, thumbnails, trends) and writes a recap plus a plan for the next episode.", runBtn, freshBtn));
  const d = await api(T("brief"));
  if (run) setTimeout(() => go(runBtn, false), 0);
  if (!d.brief) { wrap.append(emptyState({ title: "No brief yet.", body: "Press “Analyze everything”. It uses only your own data and changes nothing on YouTube." })); return wrap; }
  const b = d.brief, n = b.next_episode || {}, f = d.facts || {};
  const ul = (xs) => (xs && xs.length ? el("ul", { style: "margin:4px 0 0;padding-left:18px;line-height:1.65" }, xs.map((x) => el("li", {}, x))) : el("p", { class: "empty" }, "Not enough data yet."));
  const kv = (k, v) => (v ? el("div", { style: "margin:6px 0" }, el("b", {}, k + ": "), v) : null);
  wrap.append(el("div", { class: "callout sec", style: "font-size:16px" }, el("b", {}, b.headline || ""), el("div", { class: "faint", style: "font-size:12px;margin-top:4px" }, `${d.source} · ${ago(d.created_at)} · data through ${f.freshness || "—"}`)));
  wrap.append(el("div", { class: "grid g3 sec" },
    card("What's happening", null, ul(b.whats_happening)),
    card("What's working", null, ul(b.whats_working)),
    card("Where viewers leave", null, ul(b.where_viewers_leave))));
  wrap.append(el("section", { class: "card sec" }, el("div", { class: "card-h" }, el("h2", {}, "Next episode plan")),
    kv("Angle", n.angle), kv("Why", n.why), kv("Opening (first 30 s)", n.opening), kv("Ending", n.ending),
    n.title_words && n.title_words.length ? el("div", { style: "margin:8px 0" }, el("b", {}, "Words that show up in what works: "), n.title_words.map((w) => el("span", { class: "tag", style: "margin:2px 4px 2px 0" }, w))) : null,
    n.title_options && n.title_options.length ? el("div", {}, el("b", {}, "Title options"), el("ol", { style: "margin:4px 0;padding-left:20px" }, n.title_options.map((t) => el("li", {}, t)))) : null,
    kv("Thumbnail", n.thumbnail), n.shorts_to_cut && n.shorts_to_cut.length ? el("div", {}, el("b", {}, "Shorts to cut"), ul(n.shorts_to_cut)) : null));
  if ((b.competition || []).length || (b.seo || []).length || (b.title_rules || []).length) wrap.append(el("div", { class: "grid g3 sec" },
    card("Competition", null, ul(b.competition)), card("SEO & search", null, ul(b.seo)), card("Title rules", null, ul(b.title_rules))));
  wrap.append(el("div", { class: "grid g2 sec" },
    card("This week: 3 actions", null, el("ol", { style: "margin:4px 0 0;padding-left:20px;line-height:1.7" }, (b.this_week || []).map((x) => el("li", {}, x)))),
    card("Watch next", null, el("p", { style: "margin:0" }, b.watch_next || "—"))));
  const tw = f.title_words || {};
  const twRows = Object.entries(tw).flatMap(([fmt, rows]) => rows.map((r) => el("tr", {}, el("td", {}, r.word), el("td", {}, fmtName(fmt)), el("td", { class: "r" }, `${r.in_top} of ${r.top_n}`), el("td", { class: "r" }, `${r.in_rest} of ${r.rest_n}`))));
  const rp = f.retention || {};
  wrap.append(el("details", { class: "card sec" }, el("summary", { style: "cursor:pointer;font-weight:600" }, "The numbers behind this brief"),
    twRows.length ? el("div", { class: "tbl-wrap", style: "margin-top:10px" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Word in title", "Format", "Top quarter", "Everything else"].map((h, i) => el("th", { class: i > 1 ? "r" : "" }, h)))), el("tbody", {}, twRows))) : el("p", { class: "faint" }, "Title words need at least 8 settled videos per format."),
    Object.entries(rp).map(([fmt, r]) => el("p", { style: "font-size:13px" }, el("b", {}, `${fmtName(fmt)} retention (${r.videos} videos): `), Object.entries(r.still_watching_median_pct).map(([k, v]) => `${v ?? "—"}% still watching at ${k}`).join(" · "), r.drop_zones && Object.keys(r.drop_zones).length ? ` · sharp drops: ${Object.entries(r.drop_zones).map(([z, c]) => `${z} ${c}`).join(", ")}` : "")),
    f.competition ? el("div", { class: "tbl-wrap", style: "margin-top:10px" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Comparable channel", "Video", "Views", "Views/day"].map((h, i) => el("th", { class: i > 1 ? "r" : "" }, h)))),
      el("tbody", {}, f.competition.top_videos.map((v) => el("tr", {}, el("td", {}, v.channel), el("td", {}, v.title, el("span", { class: "faint" }, ` · ${v.format}`)), el("td", { class: "r" }, nf(v.views)), el("td", { class: "r" }, nf(v.views_per_day))))))) : el("p", { class: "faint" }, f.competition_note || "Competition data appears after the first research run."),
    (f.search_terms || []).length ? el("p", { style: "font-size:13px" }, el("b", {}, "Top search terms: "), f.search_terms.slice(0, 10).map((t) => `${t.term} (${nf(t.views)})`).join(" · ")) : null,
    el("p", { class: "faint", style: "font-size:12px" }, d.note)));
  if (d.history.length > 1) wrap.append(el("div", { class: "faint sec", style: "font-size:12px" }, `Previous briefs: ${d.history.slice(1).map((h) => ago(h.created_at)).join(" · ")}`));
  return wrap;
};

PAGES.autopilot = async () => {
  const d = await api(T("autopilot"));
  const w = d.write;
  const wrap = el("div", {}, ph("Operator", "YouTube Autopilot", "Every morning at 7:30 it reads the analytics and drafts new titles, descriptions, tags and thumbnails for the videos that need them. Approved changes go live on YouTube, get checked, and can be undone.",
    el("button", { class: "btn", onclick: async (e) => { e.target.disabled = true; try { const r = await api(T("autopilot/run"), {}); toast(`${r.proposed} new draft(s)${r.auto_applied ? `, ${r.auto_applied} applied` : ""}${r.errors.length ? ` · ${r.errors[0]}` : ""}`, !!r.errors.length); route(true); } catch (x) { toast(x.message, true); e.target.disabled = false; } } }, "Run now"),
    el("button", { class: "btn gold", title: "Removes the unrelated search-term tags added on Oct 29 and adds clean tags to videos that still have none. Titles and thumbnails are not touched.", onclick: async (e) => { e.target.disabled = true; try { await api(T("autopilot/cleanup"), {}); toast("Tag cleanup queued. Check Jobs in a few minutes."); } catch (x) { toast(x.message, true); e.target.disabled = false; } } }, "Fix tags (Oct 29 batch)")));
  wrap.append(el("div", { class: "grid g2 sec" },
    card("Write access", null, w.has_write ? el("p", { style: "margin:0" }, el("span", { class: "st ok" }, "ON"), ` Can change ${w.channel} (authorized by ${w.authorized_by || "owner"}).`)
      : el("div", {}, el("p", { style: "margin:0 0 8px" }, el("span", { class: "st warn" }, "READ-ONLY"), " ", w.note || ""), el("a", { class: "btn sm gold", href: "#/accounts" }, "Open Manage accounts → Grant write access"))),
    card("Mode", null, el("div", { class: "list" }, Object.entries(d.modes).map(([k, txt]) => el("label", { class: "li", style: "cursor:pointer;align-items:flex-start;gap:8px" },
      el("input", { type: "radio", name: "apmode", checked: d.mode === k, style: "margin-top:4px", onchange: async () => { try { await api(T("autopilot/mode"), { mode: k }); toast("Mode saved"); } catch (e) { toast(e.message, true); } route(true); } }),
      el("div", { class: "body" }, el("div", { class: "t" }, { approve: "Approve each change", auto_missing: "Auto-fill missing only", auto_all: "Fully automatic" }[k]), el("div", { class: "d" }, txt))))),
      el("div", { class: "row", style: "margin-top:10px;gap:8px;align-items:center" }, el("span", { class: "faint", style: "font-size:13px" }, "Changes per day:"),
        seg(d.cap_choices.map((n) => [String(n), String(n)]), String(d.daily_cap), async (v) => { try { await api(T("autopilot/cap"), { cap: Number(v) }); toast("Saved"); } catch (e) { toast(e.message, true); } route(true); })))));
  if (d.hosts_available.length) wrap.append(el("div", { class: "faint sec", style: "font-size:12.5px" }, `Host photos: ${d.hosts_available.join(", ")} (from your own episodes). Debate and ranking episodes get host thumbnails.`));
  else wrap.append(el("div", { class: "note sec", style: "font-size:13px" }, "No host photos yet, so thumbnails use the guest's photo from the video. Add clear photos of each host to data/brand/hosts/ (e.g. enrique.jpg, jamar.jpg) to unlock host and host + guest thumbnails."));
  const sel = {};
  const pend = d.pending.map((r) => {
    const p = r.proposal, ch = r.chosen; sel[r.id] = { ...ch };
    const titleOpts = [el("label", { style: "display:block" }, el("input", { type: "radio", name: `t_${r.id}`, checked: !ch.title, onchange: () => { sel[r.id].title = null; } }), " Keep: ", el("b", {}, p.current_title))]
      .concat((p.titles || []).map((t) => el("label", { style: "display:block" }, el("input", { type: "radio", name: `t_${r.id}`, checked: ch.title === t.title, onchange: () => { sel[r.id].title = t.title; } }), " ", t.title, el("span", { class: "faint", style: "font-size:11.5px" }, ` · ${(t.strategy || "").replaceAll("_", " ")}`))));
    const chk = (k, label) => el("label", { style: "display:block;margin-top:6px" }, el("input", { type: "checkbox", checked: !!ch[k], onchange: (e) => { sel[r.id][k] = e.target.checked ? (k === "thumbnail" ? p.thumbnail.file : true) : (k === "thumbnail" ? null : false); } }), " ", label);
    return el("section", { class: "card rec" },
      el("div", { class: "card-h" }, el("div", {}, el("span", { class: `st ${r.reason === "low_ctr" ? "warn" : "na"}` }, { low_ctr: "Low clicks", long_title: "Title too long", missing: "Missing info", new_upload: "New upload", thumb_changed: "Thumbnail changed" }[r.reason] || r.reason),
        el("h2", { style: "font-size:15px;margin-top:4px" }, r.video_title)), el("div", { class: "r" }, el("a", { class: "btn sm ghost", href: `#/episode/${r.asset_id}` }, "Episode"))),
      el("div", { class: "faint", style: "font-size:12.5px" }, r.evidence.join(" · ")),
      p.thumbnail_text ? el("div", { class: "sub" }, el("b", {}, "Thumbnail says: "), el("span", { class: "faint" }, `“${p.thumbnail_text.toUpperCase()}” (${p.thumbnail ? "the NEW thumbnail's headline" : "read from the current image"}; the title is written to go with it, not repeat it)`)) : null,
      el("div", { class: "sub" }, el("b", {}, "Title"), titleOpts),
      p.thumbnail ? el("div", { class: "sub" }, el("b", {}, "Thumbnail: current → new"), el("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-top:4px" },
        el("img", { src: r.current_thumb, alt: "current", style: "width:240px;border-radius:6px" }), el("img", { src: p.thumbnail.url, alt: "new", style: "width:240px;border-radius:6px" })), chk("thumbnail", "Use the new thumbnail")) : null,
      el("div", { class: "sub" }, chk("description", "Add to the top of the description (your current text stays below):"), el("pre", { style: "white-space:pre-wrap;font-size:12px;margin:4px 0 0" }, p.description_lines)),
      p.added_tags.length ? el("div", { class: "sub" }, chk("tags", "Add tags: "), p.added_tags.map((t) => el("span", { class: "tag", style: "margin:2px 4px 2px 0" }, t))) : null,
      el("div", { class: "row", style: "margin-top:10px;gap:6px" },
        el("button", { class: "btn sm gold", onclick: async (e) => { e.target.disabled = true; try { const x = await api(T(`autopilot/${r.id}/approve`), { chosen: sel[r.id] }); toast(x.status === "verified" ? "Live on YouTube and verified" : `${x.status}: ${x.error || ""}`, x.status !== "verified"); } catch (x) { toast(x.message, true); } route(true); } }, w.has_write ? "Approve & apply" : "Approve (applies once write access is on)"),
        el("button", { class: "btn sm ghost", onclick: async (e) => { e.target.disabled = true; e.target.textContent = "Redrafting…"; try { await api(T(`autopilot/${r.id}/redraft`), {}); } catch (x) { toast(x.message, true); } route(true); } }, "Redraft"),
        el("button", { class: "btn sm ghost", onclick: async () => { await api(T(`autopilot/${r.id}/skip`), {}); route(true); } }, "Skip")));
  });
  wrap.append(el("div", { class: "card-h sec" }, el("h2", {}, `Waiting for you (${d.pending.length})`), d.pending.length && w.has_write ? el("div", { class: "r" }, el("button", { class: "btn sm gold", onclick: async (e) => { if (!(await ask("Approve all?", [el("p", {}, `Applies the selected changes for ${d.pending.length} video(s) to YouTube now. Each one can be undone.`)], "Approve all"))) return; e.target.disabled = true; const x = await api(T("autopilot/approve-all"), {}); toast(`${x.results.filter((y) => y.status === "verified").length} verified, ${x.results.filter((y) => y.status !== "verified").length} need attention`); route(true); } }, "Approve all")) : null));
  wrap.append(pend.length ? el("div", { class: "grid", style: "gap:12px" }, pend) : emptyState({ title: "Nothing waiting.", body: "The 7:30 run drafts up to 3 changes a day for videos with low clicks, missing descriptions or tags, and new uploads." }));
  const lab = { verified: ["Live", "ok"], partial: ["Partly live", "warn"], failed: ["Failed", "bad"], rolled_back: ["Undone", "na"], skipped: ["Skipped", "na"], overridden: ["Changed by someone else", "na"], approved: ["Approved", "ok"] };
  if (d.done.length) wrap.append(card("History", null, el("div", { class: "list" }, d.done.map((r) => el("div", { class: "li" },
    el("span", { class: `st ${(lab[r.status] || ["", "na"])[1]}` }, (lab[r.status] || [r.status])[0]),
    el("div", { class: "body" }, el("div", { class: "t" }, r.video_title), el("div", { class: "d" }, `${r.chosen.title ? `Title → “${r.chosen.title}” · ` : ""}${r.applied_at ? ago(r.applied_at) : ago(r.created_at)}${r.auto ? " · automatic" : ""}${r.error ? ` · ${r.error}` : ""}`)),
    ["verified", "partial"].includes(r.status) ? el("button", { class: "btn sm ghost", onclick: async () => { if (!(await ask("Undo this change?", [el("p", {}, "Restores the original title, description, tags and thumbnail on YouTube.")], "Undo"))) return; try { await api(T(`autopilot/${r.id}/undo`), {}); toast("Restored"); } catch (e) { toast(e.message, true); } route(true); } }, "Undo")
      : r.status === "failed" ? el("button", { class: "btn sm ghost", onclick: async () => { try { await api(T(`autopilot/${r.id}/retry`), {}); } catch (e) { toast(e.message, true); } route(true); } }, "Retry") : null)))));
  wrap.append(el("div", { class: "faint sec", style: "font-size:12px" }, d.rules.join(" · ")));
  return wrap;
};

PAGES.insights = async () => {
  const d = await api(T("insights"));
  const w = d.weekly;
  const wrap = el("div", {}, ph("Thumbnail & subscriber growth", "Insights", "What's attracting new viewers and subscribers, which thumbnails work, and what to test next. Small samples are labelled; comparisons are observational."));
  const tbl = (head, rows) => el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, head.map((h, i) => el("th", { class: i ? "r" : "" }, h)))), el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c, i) => el("td", { class: i ? "r" : "" }, c ?? "—")))))));
  const hv = w.styles.host_vs_guest;
  wrap.append(el("div", { class: "grid g2 sec" },
    card("Hosts on the thumbnail vs guest-only", null, tbl(["", "Videos", "% viewed", "Avg view", "Subs/1k views", "CTR"],
      [["A host (Jamar / Enrique)", hv.host_inclusive], ["Guest only", hv.guest_only]].map(([l, g]) => [l, g.n, g.median_pct_viewed, g.median_avg_view_s != null ? dur(g.median_avg_view_s) : null, g.median_subs_per_1k, g.median_ctr])),
      el("p", { style: "font-size:13px" }, hv.verdict), el("div", { class: "foot" }, hv.method)),
    card("Experiments to run next", null, el("ol", { style: "margin:0;padding-left:20px;line-height:1.7" }, w.experiments.map((x) => el("li", {}, x))))));
  wrap.append(card("Episodes worth retesting", null, w.retest.length ? el("div", { class: "list" }, w.retest.map((r) => el("div", { class: "li" }, el("div", { class: "body" }, el("a", { class: "t", href: `#/episode/${r.asset_id}` }, r.title), el("div", { class: "d" }, r.why))))) : el("p", { class: "empty" }, "None right now.")));
  wrap.append(el("div", { class: "grid g2 sec" },
    card("Topics attracting new viewers", null, tbl(["Topic", "Videos", "Discovery share", "Sample"], w.topics_new_viewers.map((r) => [r.topic, r.videos, r.discovery_share != null ? `${r.discovery_share}%` : null, r.sample]))),
    card("Topics generating subscribers", null, tbl(["Topic", "Videos", "Subs/1k views", "Sample"], w.topics_subscribers.map((r) => [r.topic, r.videos, r.subs_per_1k, r.sample])))));
  wrap.append(card("Hook opportunities: first 30 seconds", el("span", { class: "faint", style: "font-size:12px" }, `typical: ${w.first30_median ?? "—"}% still watching at 0:30`),
    w.hooks.length ? tbl(["Episode", "At 0:30"], w.hooks.map((r) => [r.title, `${r.first30}%`])) : el("p", { class: "empty" }, "No episode is clearly below typical.")));
  wrap.append(card("First 7 days, every episode (equal age windows)", el("span", { class: "faint", style: "font-size:12px" }, `${w.age_matched.sample} · median ${nf(w.age_matched.median_d7_views)} views`),
    tbl(["Episode", "Published", "Views (7 d)", "Watch hrs (7 d)", "vs median"], w.age_matched.rows.map((r) => [r.title, r.published_at, nf(r.d7_views), nf(r.d7_hours), r.vs_median != null ? `${r.vs_median}×` : null]))));
  wrap.append(card("Per episode", null, tbl(["Episode", "CTR", "% viewed", "At 0:30", "Subs/1k", "From Shorts", "From end screens", "Discovery"],
    d.videos.map((r) => [r.title, r.ctr != null ? `${r.ctr}%` : null, r.pct_viewed, r.first30 != null ? `${r.first30}%` : null, r.subs_per_1k, nf(r.from_shorts), nf(r.from_end_screens), r.discovery_share != null ? `${r.discovery_share}%` : null])),
    el("div", { class: "foot" }, Object.values(w.not_in_api).join(" "))));
  wrap.append(card("CTR by traffic source", null, w.ctr_by_source.rows.length ? tbl(["Source", "Impressions", "CTR"], w.ctr_by_source.rows.map((r) => [r.source, nf(r.impressions), r.ctr != null ? `${r.ctr}%` : null])) : el("p", { class: "empty" }, w.ctr_by_source.note)));
  wrap.append(el("div", { class: "faint sec", style: "font-size:12px" }, w.notes.join(" ")));
  return wrap;
};

PAGES.discovery = async () => {
  const d = await api(T("discovery"));
  const wrap = el("div", {}, ph("Discovery", "Discovery & planning", "Where the show is listed, what people search, whether AI assistants mention it, what comparable channels publish, and a pre-recording episode planner. Public data only; nothing is invented.",
    el("button", { class: "btn", onclick: async (e) => { e.target.disabled = true; try { await api(T("discovery/distribution"), {}); route(true); } catch (x) { toast(x.message, true); e.target.disabled = false; } } }, "↻ Check listings")));
  const stCls = { "Connected analytics": "ok", "Verified listing only": "ok", "Imported report": "ok", "Needs authorization": "warn", "Not found": "bad", Unavailable: "na" };
  const det = (x) => { const v = x.detail || {}; return v.collectionViewUrl ? el("a", { href: v.collectionViewUrl, target: "_blank", rel: "noopener" }, `${v.collectionName} · ${v.trackCount ?? "?"} episodes`)
    : v.url ? el("span", {}, `${v.title || "feed"} · ${v.episodes ?? "?"} episodes · latest ${v.latest || "—"}`) : el("span", { class: "faint" }, v.why || v.error || v.account || ""); };
  wrap.append(card("Distribution health", el("span", { class: "faint", style: "font-size:12px" }, d.distribution[0] ? `checked ${ago(d.distribution[0].checked_at)}` : "not checked yet"),
    d.distribution.length ? el("div", { class: "list" }, d.distribution.map((x) => el("div", { class: "li" }, el("div", { class: "body" }, el("div", { class: "t" }, x.platform.replaceAll("_", " ")), el("div", { class: "d" }, det(x))), el("span", { class: `st ${stCls[x.status] || "na"}` }, x.status))))
      : el("p", { class: "empty" }, "Click “Check listings” to look the show up on Apple Podcasts (public search) and read its RSS feed.")));
  const k = d.keywords;
  wrap.append(el("div", { class: "grid g2 sec" },
    card("Search terms that found your videos", null, k.search_terms.length ? el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, el("th", {}, "Term"), el("th", { class: "r" }, "Views"), el("th", { class: "r" }, "Videos"))),
      el("tbody", {}, k.search_terms.slice(0, 20).map((x) => el("tr", {}, el("td", {}, x.term), el("td", { class: "r" }, nf(x.views)), el("td", { class: "r" }, x.videos)))))) : el("p", { class: "empty" }, "Appears after syncs collect YouTube search terms."), el("div", { class: "foot" }, k.note)),
    card("Brand topics", null, el("div", { class: "row", style: "flex-wrap:wrap;gap:6px" }, k.topics.map((x) => el("span", { class: "tag" }, `${x.keyword} · in ${x.in_titles} titles`))))));
  const a = d.ai_visibility;
  const f = { query: el("input", { placeholder: "Question asked", value: a.suggested_queries[0] }), engine: el("input", { placeholder: "AI tool + model (e.g. ChatGPT free)" }), mentioned: el("input", { type: "checkbox" }), cited_url: el("input", { placeholder: "Cited link (optional)" }), note: el("input", { placeholder: "Short excerpt / note" }) };
  wrap.append(card("AI visibility (manual samples)", null, el("p", { class: "faint", style: "font-size:12.5px" }, a.method),
    el("div", { class: "row", style: "flex-wrap:wrap;gap:6px" }, f.query, f.engine, el("label", { class: "row", style: "gap:4px" }, f.mentioned, "RYJ mentioned"), f.cited_url, f.note,
      el("button", { class: "btn sm", onclick: async () => { try { await api(T("discovery/ai-sample"), { query: f.query.value, engine: f.engine.value, mentioned: f.mentioned.checked, cited_url: f.cited_url.value, note: f.note.value }); route(true); } catch (e) { toast(e.message, true); } } }, "Log sample")),
    el("div", { class: "faint", style: "font-size:12px;margin-top:6px" }, "Suggested: ", a.suggested_queries.join(" · ")),
    a.summary.length ? el("div", { class: "list" }, a.summary.map((x) => el("div", { class: "li" }, el("div", { class: "body" }, el("div", { class: "t" }, x.query), el("div", { class: "d" }, `mentioned in ${x.mentioned} of ${x.samples} samples`))))) : null));
  const c = d.competitors;
  wrap.append(card("Competitor library", el("button", { class: "btn sm", onclick: async (e) => { e.target.disabled = true; e.target.textContent = "Searching YouTube…"; try { const r = await api(T("discovery/competitors"), {}); toast(`${r.channels.length} comparable channels, ${r.videos} recent videos`); } catch (x) { toast(x.message, true); } route(true); } }, "Find comparable channels"), c.library.length ? el("div", { class: "list" }, c.library.map((x) => el("div", { class: "li" }, el("div", { class: "body" }, el("div", { class: "t" }, x.name || x.ref),
    el("div", { class: "d" }, `${x.uploads_seen} recent uploads seen · ${x.days_between_uploads != null ? `every ~${x.days_between_uploads} days` : "cadence unknown"}${x.latest[0] ? ` · latest: ${x.latest[0].title}` : ""}`)))))
    : el("p", { class: "empty" }, "No competitor channels yet. Add them in Settings → Competitors; the trend radar reads their public feeds."),
    c.gaps.length ? el("div", { class: "sub" }, el("b", {}, "Topics they covered that you haven't: "), c.gaps.slice(0, 6).map((g) => el("div", { style: "font-size:13px" }, el("a", { href: g.url, target: "_blank", rel: "noopener" }, g.title), el("span", { class: "faint" }, ` · ${g.competitor} · ${(g.published_at || "").slice(0, 10)}`)))) : null,
    el("div", { class: "foot" }, c.note)));
  const topic = el("input", { placeholder: "Topic or viewer question (e.g. When should young athletes start lifting?)", style: "flex:1;min-width:240px" }), guest = el("input", { placeholder: "Guest (optional)" });
  const out = el("div", {});
  const showPlan = (p) => { const x = p.plan || {}; out.replaceChildren(el("div", { class: "sub" },
    x._unavailable ? el("div", { class: "note" }, `AI drafts unavailable (${x._unavailable}). Sources below are still real; write the questions yourself or enable AI in Settings.`) : null,
    x.viewer_question ? el("div", {}, el("b", {}, "Viewer question: "), x.viewer_question, x.trending_or_evergreen ? el("span", { class: "tag", style: "margin-left:6px" }, x.trending_or_evergreen) : null) : null,
    x.why_ryj ? el("div", {}, el("b", {}, "Why RYJ: "), x.why_ryj) : null, x.guest_expertise ? el("div", {}, el("b", {}, "Guest expertise: "), x.guest_expertise) : null,
    ...[["Questions", x.questions], ["Opening hooks", x.hooks], ["Follow-ups", x.follow_ups], ["Titles", x.titles], ["Thumbnail headlines", x.thumbnail_headlines], ["Clip themes", x.clip_themes]].filter(([, l]) => l && l.length)
      .map(([h, l]) => el("div", {}, el("b", {}, h), el("ol", { style: "margin:2px 0 6px;padding-left:20px" }, l.map((q) => el("li", {}, q))))),
    x.metric_to_watch ? el("div", {}, el("b", {}, "Metric to watch: "), x.metric_to_watch) : null,
    el("div", {}, el("b", {}, "Sources: "), (p.sources || []).length ? (p.sources || []).map((s) => el("div", { style: "font-size:12.5px" }, el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title), el("span", { class: "faint" }, ` · ${s.source} · ${(s.published_at || "").slice(0, 10)}`))) : el("span", { class: "faint" }, "no matching dated sources in the trend radar: treat as evergreen")),
    p.rules ? el("div", { class: "faint", style: "font-size:12px" }, p.rules) : null)); };
  wrap.append(card("Episode opportunity planner", null, el("div", { class: "row", style: "flex-wrap:wrap;gap:6px" }, topic, guest,
    el("button", { class: "btn gold sm", onclick: async (e) => { e.target.disabled = true; try { showPlan(await api(T("discovery/plan"), { topic: topic.value, guest: guest.value })); } catch (x) { toast(x.message, true); } e.target.disabled = false; } }, "Plan episode")),
    out, d.plans.length ? el("details", { class: "sub" }, el("summary", { class: "faint" }, `Saved plans (${d.plans.length})`), d.plans.map((p) => el("div", {}, el("a", { href: "#", onclick: (e) => { e.preventDefault(); showPlan(p); } }, p.topic), el("span", { class: "faint" }, ` · ${ago(p.created_at)}`)))) : null));
  return wrap;
};

PAGES.instagram = async () => {
  const acc = await api(T("accounts"));
  return el("div", {}, ph("Instagram intelligence", "Instagram", "Reach, views, Reels, engagement, follows, shares and saves, where Meta's API provides them.", stPill(acc.instagram.state)),
    el("div", { class: "grid g2" },
      card("What's needed to connect", null, el("ol", { style: "margin:0;padding-left:18px;line-height:1.8" },
        el("li", {}, "The Instagram account must be a professional (Business or Creator) account."),
        el("li", {}, "It must be linked to a Facebook Page you manage."),
        el("li", {}, "A Meta developer app (free) with Instagram Graph API permissions: instagram_basic, instagram_manage_insights, pages_read_engagement."),
        el("li", {}, "You authorize once; the app then verifies the account ID and you assign it to the brand, same as YouTube.")),
        el("div", { class: "foot" }, "No password scraping or private-account access. Metrics Meta doesn't expose will be shown as unavailable.")),
      card("Status", null, emptyState({ title: "Not connected.", body: "The Instagram connector is the next platform after the YouTube pilot. This page fills with real insights once it is connected and verified." }, goAccounts()))));
};

PAGES.podcasts = async () => {
  const p = await api(T("podcasts"));
  const wrap = el("div", {}, ph("Podcast analytics", "Spotify & Apple Podcasts", "Neither offers an open analytics API. Numbers come from reports you export and import here, mapped to the verified show."));
  const g = el("div", { class: "grid g2" });
  for (const [pl, x] of Object.entries(p)) {
    const metrics = Object.keys(x.series);
    const box = el("div", {});
    g.append(el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, pl === "spotify" ? "Spotify" : "Apple Podcasts"), el("div", { class: "r" }, stPill(x.account.state))),
      x.account.name ? el("p", { class: "muted", style: "margin:0 0 8px" }, x.account.name, " ", el("code", {}, x.account.id)) : null,
      metrics.length ? el("div", { class: "grid g2", style: "margin-bottom:10px" }, x.kpis.filter(Boolean).map((k) => kpiTile(k, null, `${k.metric} · 28 d`))) : null,
      metrics.length ? drawLater(box, () => C.line(box, metrics.slice(0, 2).map((m, i) => ({ name: m, points: x.series[m], color: ["--s1", "--s2"][i] })), {})) : emptyState({ title: "No imported data.", body: x.note }, goAccounts()),
      metrics.length > 1 ? el("div", { class: "legend" }, metrics.slice(0, 2).map((m, i) => el("span", {}, el("i", { style: `background:var(${["--s1", "--s2"][i]})` }), m))) : null,
      el("div", { class: "foot" }, x.account.data_as_of ? `Data through ${x.account.data_as_of}. ` : "", "Import more from Manage accounts → Import report.")));
  }
  wrap.append(g, el("div", { class: "callout sec" }, el("b", {}, "Discoverability. "), "Episode and show metadata audits for Spotify/Apple use your hosting provider's feed. Changes there are prepared as ready-to-paste text and marked as waiting for manual action, never claimed as done."));
  return wrap;
};

PAGES.thumbnails = async () => {
  const d = await api(T("thumbnails"));
  const wrap = el("div", {}, ph("Thumbnail intelligence", "Thumbnail lab", "Measured image features next to click-through, compared only with matching videos. Flags come from data; concepts are AI drafts you review."));
  if (!d.items.length) { wrap.append(emptyState(NO_DATA, goAccounts())); return wrap; }
  const feat = sessionGet("th.feat", "contrast");
  const sc = el("div", {});
  const pts = d.items.filter((i) => i.features && i.ctr != null && i.format === "long_form").map((i) => ({ x: i.features[feat], y: i.ctr, label: i.title, id: i.asset_id, flag: !!i.review }));
  const assoc = el("div", { class: "hbars" });
  wrap.append(el("div", { class: "grid g3" },
    el("section", { class: "card span2" }, el("div", { class: "card-h" }, el("h2", {}, "Feature vs CTR (long-form)"), el("div", { class: "r" },
      el("select", { class: "input", "aria-label": "Feature", onchange: (e) => { sessionSet("th.feat", e.target.value); route(true); } },
        ["luminance", "contrast", "colorfulness", "saturation", "edge_density", "focal_contrast"].map((f) => el("option", { value: f, selected: f === feat }, f.replace("_", " ")))))),
      drawLater(sc, () => C.scatter(sc, pts, { xLabel: feat.replace("_", " "), yLabel: "CTR", yfmt: (y) => `${y.toFixed(1)}%`, onClick: (p) => (location.hash = `#/episode/${p.id}`) })),
      el("div", { class: "legend" }, el("span", {}, el("i", { style: "background:var(--s1)" }), "video"), el("span", {}, el("i", { style: "background:var(--s3)" }), "flagged for review"))),
    card("Association with CTR", el("span", { class: "faint", style: "font-size:12px" }, `n=${d.association_n}`),
      Object.keys(d.association).length ? (() => { Object.entries(d.association).forEach(([k, r]) => assoc.append(el("div", { class: "hbar" }, el("span", { class: "hbar-l" }, k.replace("_", " ")),
        el("span", { class: "hbar-t", style: "position:relative" }, el("span", { class: "hbar-f", style: `position:absolute;left:${r < 0 ? 50 + r * 50 : 50}%;width:${Math.abs(r) * 50}%;background:var(${r < 0 ? "--s3" : "--s2"});border-radius:3px` })),
        el("span", { class: "hbar-v" }, r.toFixed(2))))); return assoc; })() : el("p", { class: "empty" }, "Needs 8+ long-form videos with CTR."),
      el("div", { class: "foot" }, d.association_note))));
  const fp = d.format_performance;
  wrap.append(el("div", { class: "grid g2 sec" },
    card("Format strategy: what works for RYJ", null,
      el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Video", "Thumbnail format", "Videos", "Median CTR", "Median views/day", "Median % viewed"].map((h, i) => el("th", { class: i > 1 ? "r" : "" }, h)))),
        el("tbody", {}, fp.rows.map((r) => el("tr", {}, el("td", {}, r.video_format === "long_form" ? "Long-form" : "Shorts"), el("td", {}, r.label, r.owner_tagged < r.n ? el("span", { class: "faint" }, ` (${r.owner_tagged}/${r.n} tagged)`) : null),
          el("td", { class: "r" }, r.n), el("td", { class: "r" }, pct(r.median_ctr)), el("td", { class: "r" }, nf(r.median_views_per_day, 1)), el("td", { class: "r" }, pct(r.median_pct_viewed))))))),
      el("div", { class: "foot" }, fp.note, " Three formats: guest-focused (guest is the hook), host + guest (a host's reaction or disagreement adds to the story), host-led (debates, rankings, analysis).")),
    card("Thumbnail experiments", null, d.experiments.length ? el("div", { class: "list" }, d.experiments.map((e) => el("div", { class: "li" }, el("div", { class: "body" },
      el("div", { class: "t" }, `${(d.items.find((i) => i.asset_id === e.asset_id) || {}).title || e.asset_id}`),
      el("div", { class: "d" }, `${e.method === "native" ? "YouTube Test & Compare" : "Sequential change"} · ${e.status} · ${e.variants.map((x) => x.label).join(" vs ")}${e.result.winner ? ` · winner: ${e.result.winner}` : ""}`),
      e.result.caveat ? el("div", { class: "faint", style: "font-size:12px" }, e.result.caveat) : null))))
      : el("p", { class: "empty" }, "No experiments yet. Render previews on an episode page and record a planned test. YouTube doesn't share Test & Compare results through its API, so enter the winner here when Studio shows it."))));
  const flagged = d.items.filter((i) => i.review);
  const show = sessionGet("th.show", "flagged");
  const grid = el("div", { class: "vgrid" });
  const list = show === "flagged" && flagged.length ? flagged : d.items;
  grid.append(...list.map((i) => {
    const c = vcard(i, { flag: i.review ? "review" : null, right: i.ctr_pctile != null ? `CTR p${i.ctr_pctile}` : "" });
    const sel = el("select", { class: "input", style: "font-size:12px;padding:4px 6px;margin-top:6px;width:100%", "aria-label": "Thumbnail format",
      onchange: async (e) => { try { await api(T(`thumbs/${i.asset_id}/format`), { format: e.target.value }); toast("Format saved"); } catch (err) { toast(err.message, true); } } },
      el("option", { value: "", disabled: true, selected: !i.thumb_format }, `Format? (suggested: ${d.formats[i.thumb_format_suggested]})`),
      Object.entries(d.formats).map(([k, l]) => el("option", { value: k, selected: k === i.thumb_format }, l)));
    return el("div", { class: "vwrap" }, c, sel);
  }));
  wrap.append(el("div", { class: "filters sec" }, el("h2", {}, show === "flagged" && flagged.length ? `Deserve review (${flagged.length})` : `All thumbnails (${d.items.length})`),
    seg([["flagged", "Flagged"], ["all", "All"]], show, (v) => { sessionSet("th.show", v); route(true); })), grid,
    el("p", { class: "faint", style: "font-size:12.5px" }, "Flag rule: CTR in the bottom quartile of matched peers, with ≥1,000 impressions and ≥7 days old. ", d.experiments_note));
  return wrap;
};

PAGES.titles = async () => {
  const d = await api(T("titles"));
  const wrap = el("div", {}, ph("Title intelligence", "Title lab", "Each title checked against your topics and real search terms, with revision history. Alternatives are AI drafts in six strategies; no virality scores."));
  if (!d.items.length) { wrap.append(emptyState(NO_DATA, goAccounts())); return wrap; }
  const lenBox = el("div", {});
  const lens = d.items.filter((i) => i.ctr != null && i.format === "long_form").map((i) => ({ x: i.length, y: i.ctr, label: i.title, id: i.asset_id }));
  wrap.append(el("div", { class: "grid g3" },
    el("section", { class: "card span2" }, el("div", { class: "card-h" }, el("h2", {}, "Title length vs CTR (long-form)")),
      drawLater(lenBox, () => C.scatter(lenBox, lens, { xLabel: "characters", yLabel: "CTR", xfmt: (x) => String(Math.round(x)), yfmt: (y) => `${y.toFixed(1)}%`, onClick: (p) => (location.hash = `#/episode/${p.id}`) })),
      el("div", { class: "foot" }, "Descriptive only. Many factors besides length affect CTR.")),
    card("Competitor title patterns", null, d.competitor_patterns ? el("dl", { class: "kv" },
      el("dt", {}, "Titles read"), el("dd", {}, d.competitor_patterns.n), el("dt", {}, "Median length"), el("dd", {}, `${d.competitor_patterns.median_length} chars`),
      el("dt", {}, "Questions"), el("dd", {}, `${Math.round(d.competitor_patterns.share_question * 100)}%`), el("dt", {}, "Contain a number"), el("dd", {}, `${Math.round(d.competitor_patterns.share_number * 100)}%`),
      el("dt", {}, "Use “|”"), el("dd", {}, `${Math.round(d.competitor_patterns.share_pipe * 100)}%`))
      : emptyState({ title: "No competitor channels yet.", body: "Add public competitor channel IDs in Settings. Their public feeds are read daily." }, el("a", { class: "btn sm", href: "#/settings" }, "Settings")))));
  const rows = d.items.slice().sort((a, b) => b.warnings - a.warnings || (a.ctr_pctile ?? 101) - (b.ctr_pctile ?? 101));
  wrap.append(el("section", { class: "card sec" }, el("div", { class: "card-h" }, el("h2", {}, "Titles"), el("div", { class: "r faint", style: "font-size:12px" }, "sorted by issues, then weakest CTR vs peers")),
    el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Title", "Chars", "Issues", "CTR", "vs peers", "Search terms", "Versions"].map((h, i) => el("th", { class: [1, 2, 3, 4, 6].includes(i) ? "r" : "" }, h)))),
      el("tbody", {}, rows.map((i) => el("tr", { class: "click", onclick: () => (location.hash = `#/episode/${i.asset_id}`) },
        el("td", { style: "max-width:380px" }, i.title, el("div", { class: "faint", style: "font-size:12px" }, i.checks.filter((c) => c.status === "warn").map((c) => c.label).join(" · "))),
        el("td", { class: "r" }, i.length), el("td", { class: "r" }, i.warnings ? el("span", { class: "st wait" }, i.warnings) : el("span", { class: "st ok" }, "0")),
        el("td", { class: "r" }, pct(i.ctr)), el("td", { class: "r" }, i.ctr_pctile != null ? `p${i.ctr_pctile}` : "—"),
        el("td", {}, i.search_terms.slice(0, 3).join(", ") || el("span", { class: "faint" }, "—")), el("td", { class: "r" }, i.revisions.length || 1))))))),
    el("p", { class: "faint", style: "font-size:12.5px" }, "Open any title for the full check and AI alternatives (", d.strategies.map((s) => s.replaceAll("_", " ")).join(", "), ")."));
  return wrap;
};

PAGES.seo = async () => {
  const d = await api(T("seo"));
  const wrap = el("div", {}, ph("SEO & discoverability", "Discoverability lab", "Description, chapters, keywords, tags and captions per video. Proposed changes always go through your approval."));
  if (!d.items.length) { wrap.append(emptyState(NO_DATA, goAccounts())); return wrap; }
  const labels = d.items[0].checks.map((c) => c.label);
  const totals = labels.map((l) => ({ label: l, v: d.items.filter((i) => (i.checks.find((c) => c.label === l) || {}).status === "warn").length }));
  const b = el("div", {});
  wrap.append(el("div", { class: "grid g3" },
    el("section", { class: "card" }, el("div", { class: "card-h" }, el("h2", {}, "Videos with each issue")), drawLater(b, () => C.bars(b, totals, { color: "--s3" }))),
    el("section", { class: "card span2" }, el("div", { class: "card-h" }, el("h2", {}, "Per video")),
      el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, el("th", {}, "Video"), labels.map((l) => el("th", {}, l)))),
        el("tbody", {}, d.items.slice().sort((x, y) => y.issues - x.issues).map((i) => el("tr", { class: "click", onclick: () => (location.hash = `#/episode/${i.asset_id}`) },
          el("td", { style: "max-width:280px" }, i.title), i.checks.map((c) => el("td", { title: c.note }, el("span", { class: `dotst ${{ ok: "ok", warn: "warn" }[c.status] || "na"}` }), c.value ?? "—"))))))))));
  wrap.append(el("div", { class: "callout sec" }, el("b", {}, "Write access is off. "), "This app has read-only YouTube access. Updating live titles or descriptions needs a separate write permission that is requested only when you enable approved changes, and each change records before/after and re-checks the result."));
  return wrap;
};

PAGES.trends = async () => {
  const status = sessionGet("tr.status", "");
  const d = await api(T(`trends${status ? `?status=${status}` : ""}`));
  const wrap = el("div", {}, ph("Trend & opportunity radar", "Opportunity radar", d.note,
    el("button", { class: "btn gold", onclick: async () => { await api("/api/jobs/trend_research/run", { tenant_id: S.brand }); toast("Trend research queued. It takes a few seconds."); } }, "Research now")));
  if (d.last_run) wrap.append(el("p", { class: "faint", style: "margin:-6px 0 14px;font-size:12.5px" }, `Last research: ${d.last_run.state} ${ago(d.last_run.finished_at)}${d.last_run.state === "failed" ? " — " + d.last_run.message : ""}`));
  wrap.append(el("div", { class: "filters" }, seg([["", "Active"], ["saved", "Saved"], ["calendar", "On calendar"], ["dismissed", "Dismissed"]], status, (v) => { sessionSet("tr.status", v); route(true); }),
    el("span", { class: "faint", style: "font-size:12.5px" }, `Topics: ${d.keywords.map((k) => k.keyword).join(", ") || "none set"}`), el("a", { class: "btn sm ghost", href: "#/settings" }, "Edit topics"),
    el("a", { class: "btn sm ghost", href: T("export/trends.csv") }, "CSV")));
  if (!d.items.length) wrap.append(emptyState({ title: "No opportunities yet.", body: d.keywords.length ? "Run research to read Google News, Google Trends and competitor feeds for your topics." : "Add topic keywords in Settings first." }));
  const g = el("div", { class: "grid g3" });
  for (const t of d.items) g.append(trendCard(t));
  wrap.append(g);
  if (d.gaps.length) wrap.append(card("Competitor publishing gaps", el("span", { class: "faint", style: "font-size:12px" }, "public feeds"),
    el("div", { class: "list" }, d.gaps.map((x) => el("div", { class: "li" }, el("div", { class: "body" }, el("a", { class: "t", href: x.url, target: "_blank", rel: "noopener noreferrer" }, x.title), el("div", { class: "d" }, `${x.competitor} · ${ago(x.published_at)} · topic not covered in your uploads`)))))));
  return wrap;
};
function trendCard(t) {
  const P = t.score_parts || {};
  const body = el("div", {});
  const ai = t.ai;
  const renderAI = (o) => el("div", { class: "alt" }, el("div", { class: "s" }, `AI draft · fit: ${o.fit}`), el("div", { class: "tt2" }, o.angle), el("div", { class: "muted", style: "font-size:13px" }, o.why_now),
    el("div", { style: "font-size:12.5px;margin-top:6px" }, el("b", {}, "Titles: "), (o.titles || []).join(" · ")),
    el("div", { style: "font-size:12.5px;margin-top:4px" }, el("b", {}, "Hooks: "), (o.hooks || []).join(" · ")),
    el("details", { style: "margin-top:6px;font-size:12.5px" }, el("summary", {}, "Interview questions & guests"), el("ol", {}, (o.questions || []).map((q) => el("li", {}, q))), el("div", {}, el("b", {}, "Guest types: "), (o.guests || []).join(", "))));
  if (ai) body.append(renderAI(ai));
  const setStatus = async (s) => { await api(T(`trends/${t.id}/status`), { status: s }); toast(`Marked ${s}`); route(true); };
  return el("section", { class: "card tcard" },
    el("div", { class: "row" }, el("div", { class: "score", title: "Heuristic opportunity score" }, Math.round(t.score)), el("span", { class: "tag" }, t.source_type.replace("_", " ")),
      el("span", { class: "faint", style: "font-size:12px;margin-left:auto" }, t.published_at ? ago(t.published_at) : "date unknown")),
    el("a", { href: t.url, target: "_blank", rel: "noopener noreferrer", style: "font-weight:600;text-decoration:none" }, t.title),
    el("div", { class: "faint", style: "font-size:12.5px" }, `${t.source}${t.matched_keywords ? " · matches " + t.matched_keywords : ""}`),
    el("div", { class: "parts" }, ["relevance", "freshness", "momentum", "novelty"].map((k) => el("div", {}, k, el("div", { class: "meter" }, el("i", { style: `width:${Math.round((P[k] || 0) * 100)}%` }))))),
    el("div", { class: "faint", style: "font-size:12px" }, `Uncertainty: ${t.uncertainty}. ${P.sources_in_cluster || 1} source(s) on this story.`),
    body,
    el("div", { class: "row" },
      el("button", { class: "btn sm", onclick: async (e) => { e.target.disabled = true; try { const r = await api(T(`ai/trend/${t.id}`), {}); body.replaceChildren(renderAI(r.output)); } catch (err) { toast(err.message, true); } e.target.disabled = false; } }, ai ? "Redo angle" : "Draft angle"),
      el("button", { class: "btn sm", onclick: () => addToCalendar(t) }, "Add to calendar"),
      t.status !== "saved" ? el("button", { class: "btn sm ghost", onclick: () => setStatus("saved") }, "Save") : null,
      t.status !== "dismissed" ? el("button", { class: "btn sm ghost", onclick: () => setStatus("dismissed") }, "Dismiss") : el("button", { class: "btn sm ghost", onclick: () => setStatus("new") }, "Restore")));
}
async function addToCalendar(t, day) {
  const title = el("input", { class: "input", value: t ? t.title : "" });
  const date = el("input", { class: "input", type: "date", value: day || new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10) });
  const kind = el("select", { class: "input" }, ["episode", "short", "post", "newsletter"].map((k) => el("option", { value: k }, k)));
  if (!(await ask("Add to content calendar", [el("label", {}, "Title"), title, el("label", {}, "Date"), date, el("label", {}, "Type"), kind], "Add"))) return;
  try { await api(T("calendar"), { title: title.value, day: date.value, kind: kind.value, trend_id: t ? t.id : null }); toast("Added to calendar"); route(true); } catch (e) { toast(e.message, true); }
}

const WF_LABEL = { suggested: "Analyzed", prepared: "Preview ready", awaiting_approval: "Awaiting approval", approved: "Approved", executed: "Monitoring", verified: "Verified · monitoring", evaluated: "Outcome reviewed", reverted: "Rolled back", dismissed: "Rejected", blocked: "Blocked", failed: "Failed" };
const WF_NEXT = { suggested: [["@prepare", "Prepare assets"], ["awaiting_approval", "Send for approval"]], prepared: [["@prepare", "Re-prepare"], ["awaiting_approval", "Send for approval"]],
  awaiting_approval: [["approved", "Approve"]], approved: [["@dryrun", "Operator dry run"], ["executed", "I applied it in YouTube Studio"]], blocked: [["executed", "I applied it in YouTube Studio"]],
  failed: [["approved", "Back to approved"]], executed: [["verified", "Verified live"], ["reverted", "Rolled back"]],
  verified: [["reverted", "Rolled back"]], evaluated: [], reverted: [], dismissed: [["suggested", "Restore"]] };
function prepBox(p) {
  if (!p) return null;
  const th = p.thumbnails;
  return el("div", { class: "sub prep" }, el("b", {}, "Asset pack (local drafts, nothing published)"),
    el("div", { class: "faint", style: "font-size:12px" }, `Keyword: ${p.keyword || "—"} (${p.keyword_basis}) · prepared ${ago(p.prepared_at)}`),
    el("ol", { style: "margin:6px 0;padding-left:20px;line-height:1.6" }, (p.titles || []).map((t) => el("li", {}, el("b", {}, t.title), el("span", { class: "faint" }, ` · ${(t.strategy || "").replaceAll("_", " ")} · ${t.source || ""}`)))),
    th ? el("a", { href: th.sheet, target: "_blank", rel: "noopener" }, el("img", { src: th.sheet, alt: "Current thumbnail next to two previews", style: "width:100%;max-width:640px;border-radius:8px;display:block" })) : null,
    th ? el("div", { class: "faint", style: "font-size:12px" }, th.source, " ", th.approval) : null,
    p.seo ? el("div", { style: "margin-top:6px;font-size:13px" }, el("b", {}, "Description, first lines: "), p.seo.first_lines,
      p.seo.chapters.length ? el("pre", { style: "margin:4px 0;font-size:12px;white-space:pre-wrap" }, p.seo.chapters.join("\n")) : el("div", { class: "faint", style: "font-size:12px" }, p.seo.chapters_note)) : null,
    (p.notes || []).map((n) => el("div", { class: "faint", style: "font-size:12px" }, n)));
}
function checkpointsBox(r, cps) {
  const done = (r.result && r.result.checkpoints) || {};
  if (!["executed", "verified", "evaluated"].includes(r.workflow)) return null;
  const b = r.baseline || {};
  return el("div", { class: "sub" }, el("b", {}, "Outcome checkpoints: "), (cps || [7, 14, 28]).map((n) => {
    const c = done[String(n)];
    return el("span", { class: "tag", style: "margin-right:6px" }, c ? `day ${n}: ${nf(c.views_per_day, 2)} views/day (was ${nf(b.views_per_day, 2)})` : `day ${n}: pending`);
  }), el("span", { class: "faint", style: "font-size:12px" }, " Observational before/after, not proof of cause."));
}
const DIAG = { content: ["Hold / content", "bad"], packaging: ["Packaging", "warn"], distribution: ["Distribution", "warn"], opportunity: ["Opportunity", "ok"], insufficient: ["Insufficient data", "na"] };
function evText(e) {
  const f = /CTR|%/.test(e.metric) ? pct : (x) => nf(x, 2);
  return `${e.metric}: ${typeof e.value === "number" ? f(e.value) : e.value}${e.peer_median != null ? ` · peers ${f(e.peer_median)}` : ""}${e.percentile != null ? ` · p${e.percentile}` : ""}`;
}
function recCard(r, wf, ctx = {}) {
  const dg = DIAG[r.diagnosis] || [r.kind.replaceAll("_", " "), "na"];
  const pipe = el("div", { class: "pipe" }, ["suggested", "prepared", "awaiting_approval", "approved", "executed", "evaluated"].map((s) => {
    const idx = wf.indexOf(r.workflow), sIdx = wf.indexOf(s);
    return el("span", { class: `step ${r.workflow === s ? "on" : idx > sIdx && r.workflow !== "dismissed" ? "done" : ""}` }, WF_LABEL[s]);
  }));
  const move = async (to) => { try { await api(T(`recommendations/${r.id}/workflow`), { to }); route(true); } catch (e) { toast(e.message, true); } };
  const special = {
    "@prepare": async (b) => { b.disabled = true; b.textContent = "Preparing…"; try { await api(T(`recommendations/${r.id}/prepare`), {}); route(true); } catch (e) { toast(e.message, true); b.disabled = false; } },
    "@dryrun": async () => { try { const x = await api(T(`recommendations/${r.id}/dry-run`), { channel_id: ctx.channel_id || "" }); toast(`${x.result}: ${x.reason}`, x.result !== "READY"); route(true); } catch (e) { toast(e.message, true); } },
  };
  const actions = (WF_NEXT[r.workflow] || []).filter(([to]) => to !== "@prepare" || (r.asset_id && !["double_down", "funnel"].includes(r.kind))).map(([to, label]) => el("button", { class: `btn sm ${to === "approved" || to === "@prepare" ? "gold" : "ghost"}`, onclick: (e) => (special[to] ? special[to](e.target) : move(to)) }, label));
  if (!["dismissed", "evaluated", "reverted"].includes(r.workflow)) actions.push(el("button", { class: "btn sm ghost", onclick: () => move("dismissed") }, "Dismiss"));
  const tp = r.test_plan || {};
  const res = r.result && r.result.before ? r.result : null;
  return el("section", { class: "card rec" },
    el("div", { class: "card-h" }, el("div", {},
      el("div", { class: "row", style: "gap:6px;flex-wrap:wrap;margin-bottom:4px" }, el("span", { class: `st ${dg[1]}` }, dg[0]),
        r.impact ? el("span", { class: "tag" }, `impact ${r.impact}`) : null, r.effort ? el("span", { class: "tag" }, `effort ${r.effort}`) : null,
        r.confidence ? el("span", { class: "tag" }, `${r.confidence} confidence`) : null, basisTag(r.basis)),
      el("h2", { style: "font-size:16px" }, r.title)), el("div", { class: "r" }, r.asset_id ? el("a", { class: "btn sm ghost", href: `#/episode/${r.asset_id}` }, "Open episode") : null)),
    el("p", { class: "muted", style: "margin:0 0 8px;font-size:13.5px" }, r.detail),
    el("div", { class: "ev" }, r.evidence.slice(0, 6).map((e) => el("span", {}, evText(e)))),
    r.hypotheses.length ? el("div", { class: "sub" }, el("b", {}, "Possible reasons (not proven): "), r.hypotheses.map((h) => `${h.cause} (${h.confidence})`).join(" · ")) : null,
    r.steps.length ? el("div", { class: "sub" }, el("b", {}, "Steps"), el("ol", { style: "margin:4px 0 0;padding-left:20px;line-height:1.6" }, r.steps.map((x) => el("li", {}, x)))) : null,
    tp.metric ? el("div", { class: "sub" }, el("b", {}, "Test: "), `${tp.metric}; baseline ${tp.baseline != null ? nf(tp.baseline, 2) : "—"}; success = ${tp.success}; reassess ${tp.reassess}.`) : null,
    prepBox(r.prepared),
    !r.prepared && r.asset_id && !["double_down", "funnel"].includes(r.kind) && ["suggested", "prepared"].includes(r.workflow) ? el("div", { class: "sub faint" }, "“Prepare assets” drafts 3 titles (search, curiosity, hybrid), 2 RYJ-style thumbnail previews and an SEO draft. Nothing is published.") : null,
    checkpointsBox(r, ctx.checkpoints),
    res ? el("div", { class: "sub" }, el("b", {}, "Before → after: "), `views/day ${nf(res.before.views_per_day, 2)} → ${nf(res.after.views_per_day, 2)} · % viewed ${pct(res.before.averageViewPercentage)} → ${pct(res.after.averageViewPercentage)} · CTR ${pct(res.before.videoThumbnailImpressionsClickRate)} → ${pct(res.after.videoThumbnailImpressionsClickRate)}. `, el("span", { class: "faint" }, res.note)) : null,
    r.evaluate_after && ["executed", "verified"].includes(r.workflow) ? el("div", { class: "sub faint" }, `Baseline saved. Next checkpoint on ${r.evaluate_after}.`) : null,
    pipe,
    el("div", { class: "row", style: "margin-top:8px;gap:6px;flex-wrap:wrap" }, actions, el("span", { class: "faint", style: "font-size:12px;margin-left:auto" }, `${r.state_label || WF_LABEL[r.workflow]} · created ${ago(r.created_at)}`)),
    r.ledger.length ? el("details", { class: "sub" }, el("summary", { class: "faint" }, `History (${r.ledger.length})`),
      r.ledger.map((l) => el("div", { class: "faint", style: "font-size:12px" }, `${l.at.slice(0, 16).replace("T", " ")} · ${l.actor}: ${WF_LABEL[l.from_state] || l.from_state} → ${WF_LABEL[l.to_state]}${l.note ? ` (${l.note})` : ""}`))) : null);
}

PAGES.recommendations = async () => {
  const d = await api(T("recommendations"));
  const f = sessionGet("rec.f", "open");
  const items = d.items.filter((r) => f === "all" || r.status === f);
  const wrap = el("div", {}, ph("Growth recommendations", "Recommendations", "Each card states what was measured, possible reasons, exact steps, a test, and where it is in the approval flow. Nothing is applied automatically.",
    el("button", { class: "btn", onclick: async () => { await api("/api/jobs/daily_review/run", { tenant_id: S.brand }); await api("/api/jobs/packaging_check/run", { tenant_id: S.brand }); toast("Review queued; refresh in a minute"); } }, "Run review now"),
    el("a", { class: "btn ghost", href: T("export/recommendations.csv") }, "CSV")));
  wrap.append(el("div", { class: "note sec", style: "font-size:13px" }, d.write_note));
  wrap.append(el("div", { class: "filters" }, seg([["open", "Open"], ["accepted", "Approved"], ["done", "Done"], ["dismissed", "Dismissed"], ["all", "All"]], f, (v) => { sessionSet("rec.f", v); route(true); })));
  if (!items.length) { wrap.append(emptyState({ title: "Nothing here.", body: "The daily review (7:00) adds up to 3 new opportunities a day when the data supports them. Videos under 7 days old or with under 100 views are left to settle." })); return wrap; }
  wrap.append(el("div", { class: "grid", style: "gap:12px" }, items.map((r) => recCard(r, d.workflow, d))));
  return wrap;
};

PAGES.calendar = async () => {
  const month = sessionGet("cal.m", new Date().toISOString().slice(0, 7));
  const d = await api(T(`calendar?month=${month}`));
  const [y, m] = month.split("-").map(Number);
  const shift = (n) => { const dt = new Date(Date.UTC(y, m - 1 + n, 1)); sessionSet("cal.m", dt.toISOString().slice(0, 7)); route(true); };
  const label = new Date(Date.UTC(y, m - 1, 1)).toLocaleString(undefined, { month: "long", year: "numeric", timeZone: "UTC" });
  const wrap = el("div", {}, ph("Content calendar", label, "Planned episodes and posts next to what actually published. Add items from the trend radar or here.",
    el("button", { class: "btn ghost", onclick: () => shift(-1), "aria-label": "Previous month" }, "←"), el("button", { class: "btn ghost", onclick: () => shift(1), "aria-label": "Next month" }, "→"),
    el("button", { class: "btn gold", onclick: () => addToCalendar(null) }, "+ Add")));
  const cal = el("div", { class: "cal", role: "grid" });
  ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach((x) => cal.append(el("div", { class: "dow" }, x)));
  const first = new Date(Date.UTC(y, m - 1, 1)); const offset = (first.getUTCDay() + 6) % 7;
  const today = new Date().toISOString().slice(0, 10);
  for (let i = 0; i < 42; i++) {
    const dt = new Date(Date.UTC(y, m - 1, 1 - offset + i)); const iso = dt.toISOString().slice(0, 10);
    if (i >= 35 && dt.getUTCMonth() !== m - 1) break;
    const cell = el("div", { class: `day ${dt.getUTCMonth() !== m - 1 ? "out" : ""} ${iso === today ? "today" : ""}`, onclick: (e) => { if (e.target === cell || e.target.classList.contains("n")) addToCalendar(null, iso); } },
      el("span", { class: "n" }, dt.getUTCDate()));
    d.published.filter((p) => p.day === iso).forEach((p) => cell.append(el("a", { class: "chip pub", href: `#/episode/${p.asset_id}`, title: `Published: ${p.title}` }, p.title)));
    d.items.filter((p) => p.day === iso).forEach((p) => cell.append(el("span", { class: `chip ${p.status === "idea" ? "idea" : ""}`, title: `${p.kind} · ${p.status}`, onclick: (e) => { e.stopPropagation(); editCal(p); } }, p.title)));
    cal.append(cell);
  }
  wrap.append(cal, el("div", { class: "legend" }, el("span", {}, el("i", { style: "background:var(--s1)" }), "published"), el("span", {}, el("i", { style: "background:var(--s3)" }), "idea"), el("span", {}, el("i", { style: "background:var(--s2)" }), "planned / in production")));
  return wrap;
};
async function editCal(p) {
  const title = el("input", { class: "input", value: p.title });
  const date = el("input", { class: "input", type: "date", value: p.day });
  const status = el("select", { class: "input" }, ["idea", "planned", "recording", "editing", "scheduled", "published"].map((k) => el("option", { value: k, selected: k === p.status }, k)));
  const notes = el("textarea", { class: "input" }, p.notes || "");
  const del = el("button", { type: "button", class: "btn sm danger", onclick: async () => { $("#dlg").close("cancel"); await api(T("calendar"), { id: p.id, delete: true }); route(true); } }, "Delete");
  if (!(await ask("Edit item", [el("label", {}, "Title"), title, el("label", {}, "Date"), date, el("label", {}, "Status"), status, el("label", {}, "Notes"), notes, el("div", { style: "margin-top:10px" }, del)], "Save"))) return;
  await api(T("calendar"), { id: p.id, title: title.value, day: date.value, status: status.value, kind: p.kind, notes: notes.value }); route(true);
}

PAGES.reports = async () => {
  const list = await api(T("reports"));
  const wrap = el("div", {}, ph("Automated reports", "Reports", "Weekly (Mondays 08:00) and monthly (1st, 08:30) reports generate automatically. Each is saved, viewable here, and exportable as PDF.",
    el("button", { class: "btn gold", onclick: async () => { try { const r = await api(T("reports/generate"), { kind: "manual" }); toast(r.reused ? "Nothing changed; opened the existing report" : "Report generated"); location.hash = `#/reports`; route(true); } catch (e) { toast(e.message, true); } } }, "Generate now (last 28 days)")));
  const viewer = el("iframe", { title: "Report preview", style: "width:100%;height:70vh;border:1px solid var(--line);border-radius:12px;background:#fff" });
  const sel = sessionGet("rep.sel", list[0] && list[0].id);
  const cur = list.find((r) => r.id === sel) || list[0];
  wrap.append(el("div", { class: "grid g3" },
    card("Saved reports", null, list.length ? el("div", { class: "list" }, list.map((r) => el("div", { class: "li" }, el("div", { class: "body" },
      el("a", { href: "#/reports", class: "t", onclick: (e) => { e.preventDefault(); sessionSet("rep.sel", r.id); route(true); } }, `${r.kind[0].toUpperCase() + r.kind.slice(1)} · ${r.period_start} → ${r.period_end}`),
      el("div", { class: "d" }, `created ${ago(r.created_at)}`))))) : el("p", { class: "empty" }, "No reports yet.")),
    el("section", { class: "card span2" }, el("div", { class: "card-h" }, el("h2", {}, cur ? cur.title : "Preview"), el("div", { class: "r" },
      cur ? el("a", { class: "btn sm", href: T(`reports/${cur.id}.html`), target: "_blank" }, "Open") : null,
      cur ? el("a", { class: "btn sm", href: T(`reports/${cur.id}.pdf`) }, "PDF") : null)), cur ? viewer : el("p", { class: "empty" }, "Generate a report to preview it."))));
  if (cur) viewer.src = T(`reports/${cur.id}.html`);
  wrap.append(card("CSV exports", null, el("div", { class: "row" }, [["videos", "Videos"], ["daily", "Daily metrics"], ["trends", "Trends"], ["recommendations", "Recommendations"]].map(([k, l]) => el("a", { class: "btn sm", href: T(`export/${k}.csv`) }, `${l} CSV`)))));
  wrap.lastChild.classList.add("sec");
  return wrap;
};

PAGES.jobs = async () => {
  const d = await api("/api/jobs");
  const wrap = el("div", {}, ph("Operations", "Jobs & integrations", "Background jobs run while this app is open on your computer, even when the browser tab is closed. No Claude chat is needed.",
    el("span", { class: `st ${d.scheduler_alive ? "ok" : "bad"}` }, d.scheduler_alive ? "Scheduler running" : "Scheduler not running"),
    el("button", { class: "btn sm ghost", title: "Reloads the app with the latest code. It also reloads by itself when an update is copied in.", onclick: async (e) => {
      e.target.disabled = true; e.target.textContent = "Restarting…";
      try { await api("/api/restart", {}); } catch (err) { /* connection drops during restart */ }
      const t0 = Date.now(); const poll = async () => { try { await api("/api/app"); location.reload(); } catch (err) { if (Date.now() - t0 < 90000) setTimeout(poll, 2000); } };
      setTimeout(poll, 4000);
    } }, "Restart app")));
  const open = d.alerts.filter((a) => !a.acked_at);
  if (open.length) wrap.append(card(`Alerts (${open.length})`, null, el("div", { class: "list" }, open.map((a) => el("div", { class: "li" }, el("span", { class: "dotst bad" }),
    el("div", { class: "body" }, el("div", { class: "t" }, a.source), el("div", { class: "d" }, a.message), el("div", { class: "faint", style: "font-size:12px" }, ago(a.created_at))),
    el("button", { class: "btn sm ghost", onclick: async () => { await api(`/api/alerts/${a.id}/ack`, {}); route(true); } }, "Dismiss"))))));
  wrap.append(el("section", { class: "card sec" }, el("div", { class: "card-h" }, el("h2", {}, "Schedules")),
    el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Job", "When", "Next run", "Last success", "Last status", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, d.schedules.map((s) => el("tr", {},
        el("td", {}, el("b", {}, s.description), el("div", { class: "faint", style: "font-size:12px" }, s.name)),
        el("td", {}, s.describe), el("td", {}, s.enabled ? ago(s.next_run_at) : el("span", { class: "faint" }, "paused")), el("td", {}, ago(s.last_success_at)),
        el("td", {}, s.last_status ? el("span", { class: `st ${s.last_status === "failed" ? "bad" : s.last_status === "succeeded" ? "ok" : ""}`, title: s.last_error || "" }, s.last_status) : "—"),
        el("td", {}, el("div", { class: "row" },
          el("button", { class: "btn sm", onclick: async () => { const r = await api(`/api/jobs/${s.kind}/run`, {}); toast(r.queued ? "Queued" : "Already queued or running"); setTimeout(() => route(true), 600); } }, "Run now"),
          el("button", { class: "btn sm ghost", onclick: async () => { await api(`/api/schedules/${s.name}`, { enabled: !s.enabled }); route(true); } }, s.enabled ? "Pause" : "Resume"))))))))));
  wrap.append(el("section", { class: "card sec" }, el("div", { class: "card-h" }, el("h2", {}, "Recent runs")),
    el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Job", "Brand", "Trigger", "State", "Progress", "Message", "Finished"].map((h) => el("th", {}, h)))),
      el("tbody", {}, d.runs.map((r) => el("tr", {}, el("td", {}, r.kind.replaceAll("_", " ")), el("td", {}, r.tenant_id || "all"), el("td", {}, r.trigger),
        el("td", {}, el("span", { class: `st ${r.state === "failed" ? "bad" : r.state === "succeeded" ? "ok" : r.state === "running" || r.state === "retry" ? "wait" : ""}` }, r.state + (r.attempt > 1 ? ` (try ${r.attempt})` : ""))),
        el("td", { style: "min-width:90px" }, el("div", { class: "meter" }, el("i", { style: `width:${r.progress}%` }))), el("td", { class: "muted", style: "max-width:320px;font-size:12.5px" }, r.message || ""),
        el("td", {}, r.finished_at ? ago(r.finished_at) : r.next_retry_at ? `retry ${ago(r.next_retry_at)}` : "—"))))))));
  const L = { youtube: "YouTube", instagram: "Instagram", spotify: "Spotify", apple_podcasts: "Apple Podcasts" };
  wrap.append(el("div", { class: "grid g2 sec" },
    card("Integrations", null, el("div", { class: "tbl-wrap" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Brand", "Platform", "State", "Account", "Data as of"].map((h) => el("th", {}, h)))),
      el("tbody", {}, d.integrations.map((i) => el("tr", {}, el("td", {}, i.brand, i.kind === "demo" ? el("span", { class: "tag synthetic", style: "margin-left:6px" }, "demo") : null), el("td", {}, L[i.platform]), el("td", {}, stPill(i.state)), el("td", {}, i.name || "—"), el("td", {}, i.data_as_of || "—"))))))),
    card("Usage today", null, el("dl", { class: "kv" },
      el("dt", {}, "YouTube OAuth client"), el("dd", {}, d.env.youtube_client ? "configured" : "not configured"),
      el("dt", {}, "API request budget"), el("dd", {}, `${d.env.api_budget_per_day}/day per brand`),
      el("dt", {}, "AI drafts"), el("dd", {}, d.ai.cli_found ? `${d.ai.enabled ? "on" : "off"} · ${d.ai.used_today}/${d.ai.daily_cap} calls · est. $${d.ai.cost_estimate_today_usd} list-price equivalent (covered by subscription)` : d.ai.reason),
      el("dt", {}, "PDF export"), el("dd", {}, d.env.pdf_browser ? "Edge/Chrome found" : "no browser found; use Print → Save as PDF")),
      d.usage.length ? el("div", { class: "tbl-wrap", style: "margin-top:10px" }, el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, ["Kind", "Endpoint / model", "Calls", "Cache hits", "Quota", "Tokens in/out", "Errors"].map((h) => el("th", {}, h)))),
        el("tbody", {}, d.usage.map((u) => el("tr", {}, el("td", {}, u.kind), el("td", { style: "font-size:12px" }, u.name), el("td", { class: "r" }, u.calls), el("td", { class: "r" }, u.cache_hits), el("td", { class: "r" }, u.quota_units), el("td", { class: "r" }, `${nf(u.tokens_in)}/${nf(u.tokens_out)}`), el("td", { class: "r" }, u.errors))))))
        : el("p", { class: "empty" }, "No API or AI calls today."))));
  return wrap;
};

PAGES.accounts = async () => {
  const tiles = await api(T("tiles"));
  const b = brand();
  const wrap = el("div", {}, ph("Manage accounts", b.display_name, "Nothing syncs until you verify the exact platform ID and assign it to this brand. Each brand's tokens and data are kept separate.",
    el("button", { class: "btn", onclick: newBrand }, "+ New brand")));
  const disc = new URLSearchParams(location.search).get("discovered");
  if (disc) wrap.append(el("div", { class: "callout", style: "margin-bottom:14px" }, `Google returned ${disc} channel(s). Verify the correct one below; nothing has been imported yet.`));
  if (b.is_demo) wrap.append(el("div", { class: "callout", style: "margin-bottom:14px" }, "This is the synthetic demo brand. Its accounts are fake and cannot be connected."));
  const g = el("div", { class: "tiles" });
  const L = { youtube: "YouTube", instagram: "Instagram", spotify: "Spotify", apple_podcasts: "Apple Podcasts" };
  const G = { youtube: "YT", instagram: "IG", spotify: "SP", apple_podcasts: "AP" };
  for (const t of tiles) {
    const kids = [el("div", { class: "tile-h" }, el("div", { class: "pic" }, G[t.platform]), el("h2", {}, L[t.platform]), el("span", { style: "margin-left:auto" }, stPill(t.state)))];
    if (t.primary) kids.push(acctBlock(t.primary));
    t.candidates.forEach((c) => kids.push(el("div", { style: "border-top:1px dashed var(--line);margin-top:12px;padding-top:4px" }, acctBlock(c))));
    if (!t.primary && !t.candidates.length) kids.push(el("p", { class: "empty" }, "No account connected."));
    if (!t.primary && !b.is_demo) kids.push(el("div", { class: "row", style: "margin-top:10px" }, el("button", { class: t.candidates.length ? "btn" : "btn gold", onclick: () => connect(t) }, t.candidates.length ? "Connect another" : "Connect")));
    kids.push(el("div", { class: "foot" }, t.note, t.platform === "youtube" && t.client_configured === false ? " OAuth client file not set up yet (README → Connect YouTube)." : ""));
    g.append(el("section", { class: "card" }, kids));
  }
  wrap.append(g);
  const audit = await api(T("audit"));
  wrap.append(el("details", { class: "card sec" }, el("summary", { style: "cursor:pointer;font-weight:600" }, `Audit log (${audit.length})`),
    el("ol", { style: "font-size:12.5px;color:var(--muted);padding-left:18px" }, audit.map((a) => { const x = JSON.parse(a.detail_json || "{}");
      return el("li", {}, el("b", { style: "color:var(--text)" }, a.event), x.to ? ` ${x.platform} ${x.platform_account_id}: ${x.from} → ${x.to}` : x.platform_account_id ? ` ${x.platform || ""} ${x.platform_account_id}` : "", ` · ${a.actor} · ${ago(a.at)}`); }))));
  return wrap;
};
function acctBlock(a) {
  const st = a.state; const acts = [];
  const act = async (action, body = {}) => {
    try { const r = await api(T(`accounts/${a.id}/${action}`), body);
      if (action === "test") toast(`First sync OK: ${r.channel_title}. ${r.daily_rows} daily rows, data through ${r.available_through || "n/a"}.`);
      if (action === "import") toast(r.skipped || `Imported ${r.values} values through ${r.available_through}`);
    } catch (e) { toast(e.message, true); }
    route(true);
  };
  if (st === "AUTHORIZED_UNASSIGNED") {
    acts.push(el("button", { class: "btn gold sm", onclick: async () => {
      const input = el("input", { class: "input", autocomplete: "off", spellcheck: "false", "aria-label": "Platform ID" });
      if (await ask(`Is this ${brand().display_name}'s account?`, [el("p", {}, a.account_name || "(no name)", " ", a.handle || ""), el("p", {}, "ID: ", el("code", {}, a.platform_account_id)),
        el("p", {}, "Authorized by: ", a.connected_identity || "unknown"), el("label", {}, "Type the ID to confirm"), input], "Verify identity")) act("verify", { confirm_id: input.value });
    } }, "Verify identity"));
    acts.push(el("button", { class: "btn sm danger", onclick: () => act("reject") }, "Not this account"));
  }
  if (["ASSIGNED", "ACTIVE", "SYNCING", "SYNC_FAILED"].includes(st) && a.platform === "youtube" && a.access_level !== "WRITE_METADATA")
    acts.push(el("button", { class: "btn sm", onclick: async () => { if (await ask("Grant write access?", [el("p", {}, "Lets the Autopilot change titles, descriptions, tags and thumbnails on this channel, only as you approve (or as the Autopilot mode you choose allows)."), el("p", {}, "Sign in with the Google account that owns the channel. Afterwards, verify the ID and assign it again (a safety step whenever access changes).")], "Continue to Google")) connect({ platform: "youtube", write: true }); } }, "Grant write access"));
  if (st === "NEEDS_REAUTH" && a.platform === "youtube") acts.unshift(el("button", { class: "btn gold sm", onclick: () => connect({ platform: "youtube" }) }, "Reconnect YouTube"));
  if (st === "OWNER_VERIFIED") acts.push(el("button", { class: "btn gold sm", onclick: () => act("assign") }, "Assign to brand"));
  if (["ASSIGNED", "ACTIVE", "SYNC_FAILED", "PERMISSION_LIMITED"].includes(st) && a.platform === "youtube") acts.push(el("button", { class: "btn sm", onclick: () => act("test") }, "Test connection"));
  if (st === "ASSIGNED" && ["spotify", "apple_podcasts"].includes(a.platform)) acts.push(el("button", { class: "btn gold sm", onclick: () => act("enable_import") }, "Enable import"));
  if (st === "IMPORT_ONLY") {
    const file = el("input", { type: "file", accept: ".csv,text/csv", hidden: true, onchange: async (e) => { const f = e.target.files[0]; if (f) act("import", { filename: f.name, csv: await f.text() }); } });
    acts.push(file, el("button", { class: "btn gold sm", onclick: () => file.click() }, "Import report (CSV)"));
  }
  if (!["DISCONNECTED", "REVOKED", "REJECTED", "AUTHORIZED_UNASSIGNED"].includes(st)) acts.push(el("button", { class: "btn sm ghost", onclick: async () => { if (await ask("Disconnect?", [el("p", {}, "Stops sync and deletes stored tokens. History stays with this brand.")], "Disconnect")) act("disconnect"); } }, "Disconnect"));
  if (a.platform === "youtube" && !["REVOKED", "REJECTED", "DISCONNECTED"].includes(st)) acts.push(el("button", { class: "btn sm ghost danger", onclick: async () => { if (await ask("Revoke Google access?", [el("p", {}, "Revokes the token at Google and pauses all jobs for this channel.")], "Revoke")) act("revoke"); } }, "Revoke"));
  return el("div", {},
    el("dl", { class: "kv" }, el("dt", {}, "Account"), el("dd", {}, el("b", {}, a.account_name || "(unnamed)"), " ", a.handle || ""),
      el("dt", {}, "ID"), el("dd", {}, el("code", {}, a.platform_account_id)), el("dt", {}, "Verified"), el("dd", {}, a.verified_by ? `${a.verified_by} · ${ago(a.verified_at)}` : "not yet"),
      el("dt", {}, "Access"), el("dd", {}, a.access_level), el("dt", {}, "Last sync"), el("dd", {}, ago(a.last_successful_sync)), el("dt", {}, "Data as of"), el("dd", {}, a.data_as_of || "—")),
    a.last_error ? el("div", { class: "err" }, a.last_error) : null,
    st === "NEEDS_REAUTH" && a.platform === "youtube" ? el("div", { class: "note", style: "font-size:12.5px;margin-top:8px" },
      `Google signed this app out. Click “Reconnect YouTube”, sign in as ${a.connected_identity || "the Google account that owns the channel"} and click Continue. Back here, click “Verify identity” (type the ID above), then “Assign to brand”. History is kept.`) : null,
    el("div", { class: "row", style: "margin-top:10px" }, acts));
}
async function connect(t) {
  try {
    if (t.platform === "youtube") { const r = await api(T("connect/youtube"), { write: !!t.write }); location.href = r.auth_url; return; }
    if (t.platform === "instagram") { location.hash = "#/instagram"; return; }
    const input = el("input", { class: "input", placeholder: t.platform === "spotify" ? "https://open.spotify.com/show/…" : "Apple Podcasts show ID (numbers)" });
    if (!(await ask(`Find ${t.platform === "spotify" ? "Spotify" : "Apple Podcasts"} show`, [el("p", {}, "A public match only identifies the show. It doesn't prove ownership or give analytics access."), input], "Find show"))) return;
    await api(T(`connect/${t.platform}`), { show: input.value }); route(true);
  } catch (e) { toast(e.message, true); }
}
async function newBrand() {
  const name = el("input", { class: "input", placeholder: "Brand name" });
  if (!(await ask("Create brand", [el("p", {}, "Each brand is isolated: its own accounts, tokens, data and reports."), name], "Create"))) return;
  try { const r = await api("/api/brands", { display_name: name.value }); S.brand = r.tenant_id; await loadApp(); location.hash = "#/accounts"; route(true); } catch (e) { toast(e.message, true); }
}

PAGES.settings = async () => {
  const d = await api(T("settings"));
  const topics = el("textarea", { class: "input", rows: 8, "aria-label": "Topics" }, d.topics.map((t) => (t.weight !== 1 ? `${t.keyword} | ${t.weight}` : t.keyword)).join("\n"));
  const comps = el("textarea", { class: "input", rows: 5, "aria-label": "Competitors", placeholder: "UCxxxxxxxxxxxxxxxxxxxxxx | Channel name" }, d.competitors.map((c) => `${c.ref} | ${c.name}`).join("\n"));
  const aiOn = el("input", { type: "checkbox", checked: d.ai.enabled });
  const cap = el("input", { class: "input", type: "number", min: 0, max: 500, value: d.ai_daily_calls, style: "width:100px" });
  return el("div", {}, ph("Settings", `${brand().display_name}`, "Topics drive trend relevance and keyword checks. Competitors are public YouTube channels read through their public feeds."),
    el("div", { class: "grid g2" },
      card("Topics", null, el("p", { class: "muted", style: "margin-top:0;font-size:13px" }, "One per line. Optional weight after “|” (default 1)."), topics,
        el("div", { class: "row end", style: "margin-top:10px" }, el("button", { class: "btn gold", onclick: async () => {
          const list = topics.value.split("\n").map((l) => l.split("|")).filter((p) => p[0].trim()).map((p) => ({ keyword: p[0].trim(), weight: p[1] ? Number(p[1]) || 1 : 1 }));
          try { await api(T("settings"), { topics: list }); toast("Topics saved"); } catch (e) { toast(e.message, true); } } }, "Save topics"))),
      card("Competitor channels", null, el("p", { class: "muted", style: "margin-top:0;font-size:13px" }, "Channel ID (starts with UC) | name. Find it on the channel's About page → Share → Copy channel ID."), comps,
        el("div", { class: "row end", style: "margin-top:10px" }, el("button", { class: "btn gold", onclick: async () => {
          const list = comps.value.split("\n").map((l) => l.split("|")).filter((p) => p[0].trim()).map((p) => ({ ref: p[0].trim(), name: (p[1] || "").trim() }));
          try { await api(T("settings"), { competitors: list }); toast("Competitors saved"); } catch (e) { toast(e.message, true); } } }, "Save competitors")))),
    el("div", { class: "grid g2 sec" },
      card("AI drafts", null, el("p", { class: "muted", style: "margin-top:0;font-size:13px" }, "Titles, thumbnail concepts and trend angles are drafted with your Claude Code subscription (no API key). Inputs are compact; results are cached so unchanged videos are never re-sent."),
        el("label", { class: "row" }, aiOn, " Enable AI drafts"), el("label", { class: "row", style: "margin-top:8px" }, "Daily call cap ", cap),
        el("p", { class: "faint", style: "font-size:12.5px" }, d.ai.cli_found ? `Claude Code CLI found · ${d.ai.used_today} calls today` : d.ai.reason),
        el("div", { class: "row end" }, el("button", { class: "btn gold", onclick: async () => { await api("/api/settings", { ai_enabled: aiOn.checked, ai_daily_calls: Number(cap.value) }); toast("Saved"); } }, "Save"))),
      card("This computer", null, el("dl", { class: "kv" }, el("dt", {}, "Dashboard"), el("dd", {}, el("code", {}, location.origin + "/")),
        el("dt", {}, "Install as app"), el("dd", {}, "In Edge/Chrome: menu → Apps → Install this site as an app."),
        el("dt", {}, "Theme"), el("dd", {}, el("button", { class: "btn sm", onclick: () => $("#theme").click() }, "Toggle light/dark"))))));
};

/* ── boot ──────────────────────────────────────────────────────────── */
(async () => {
  try { await loadApp(); } catch (e) { $("#main").replaceChildren(el("div", { class: "callout" }, "Can't reach the Growth OS server. Is it running? ", e.message)); return; }
  route();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
