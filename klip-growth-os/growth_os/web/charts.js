"use strict";
/* Tiny SVG chart kit. One y-axis per chart, thin marks, recessive grid,
   hover crosshair + tooltip, colors from CSS tokens (--s1..--s3). */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const s = (tag, attrs = {}) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  const nf = (v, d = 0) => v == null ? "—" : Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + "M"
    : Math.abs(v) >= 1e4 ? (v / 1e3).toFixed(1) + "K" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }
  function tooltip(host) {
    let t = host.querySelector(".tt");
    if (!t) { t = document.createElement("div"); t.className = "tt"; t.hidden = true; host.append(t); }
    return t;
  }
  function placeTip(tip, host, x, y) {
    const w = tip.offsetWidth, hw = host.clientWidth;
    tip.style.left = Math.max(4, Math.min(hw - w - 4, x + 12)) + "px";
    tip.style.top = Math.max(4, y - 10) + "px";
  }

  /* series: [{name, color:'--s1', points:[{d|x, v}]}]; opts: {height, yfmt, xfmt, area, yMax, markers:[{x,label,kind}], xKey} */
  function line(host, series, opts = {}) {
    host.classList.add("chart");
    host.replaceChildren();
    const xKey = opts.xKey || "d";
    const pts0 = series[0] ? series[0].points : [];
    if (!pts0.length || pts0.length < 2) {
      host.append(Object.assign(document.createElement("p"), { className: "empty", textContent: opts.empty || "No data for this range yet." }));
      return;
    }
    const W = Math.max(280, host.clientWidth || 600), H = opts.height || 220;
    const L = 46, R = opts.endLabels === false ? 12 : 56, T = 10, B = 24;
    const iw = W - L - R, ih = H - T - B;
    const xs = pts0.map((p) => p[xKey]);
    const numericX = typeof xs[0] === "number";
    const xMin = numericX ? xs[0] : 0, xMax = numericX ? xs[xs.length - 1] : xs.length - 1;
    const xi = (p, i) => L + ((numericX ? p[xKey] : i) - xMin) / ((xMax - xMin) || 1) * iw;
    const maxV = opts.yMax || niceMax(Math.max(...series.flatMap((sr) => sr.points.map((p) => p.v || 0))));
    const yi = (v) => T + ih - (v / maxV) * ih;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img",
      "aria-label": opts.label || series.map((x) => x.name).join(", ") });
    for (const f of [0, 0.25, 0.5, 0.75, 1]) {
      const y = T + ih * f;
      svg.append(s("line", { x1: L, x2: L + iw, y1: y, y2: y, class: "grid" }));
      const tx = s("text", { x: L - 6, y: y + 4, "text-anchor": "end", class: "axis" });
      tx.textContent = (opts.yfmt || nf)(maxV * (1 - f));
      svg.append(tx);
    }
    const xf = opts.xfmt || ((v) => (typeof v === "string" ? v.slice(5) : v));
    for (const i of [0, Math.floor((xs.length - 1) / 2), xs.length - 1]) {
      const tx = s("text", { x: xi(pts0[i], i), y: H - 6, "text-anchor": i === 0 ? "start" : i === xs.length - 1 ? "end" : "middle", class: "axis" });
      tx.textContent = xf(xs[i]);
      svg.append(tx);
    }
    for (const m of opts.markers || []) {
      const i = xs.indexOf(m.x);
      const x = numericX ? xi({ [xKey]: m.x }, 0) : i >= 0 ? xi(pts0[i], i) : null;
      if (x == null) continue;
      svg.append(s("line", { x1: x, x2: x, y1: T, y2: T + ih, class: "marker " + (m.kind || "") }));
    }
    series.forEach((sr) => {
      const d = sr.points.map((p, i) => `${i ? "L" : "M"}${xi(p, i).toFixed(1)},${yi(p.v || 0).toFixed(1)}`).join("");
      if (opts.area && series.length === 1) {
        svg.append(s("path", { d: `${d}L${xi(sr.points.at(-1), sr.points.length - 1)},${T + ih}L${L},${T + ih}Z`,
          style: `fill:var(${sr.color || "--s1"});opacity:.12` }));
      }
      svg.append(s("path", { d, fill: "none", style: `stroke:var(${sr.color || "--s1"})`, "stroke-width": 2, "stroke-linejoin": "round" }));
      const last = sr.points.at(-1);
      if (opts.endLabels !== false) {
        const lx = xi(last, sr.points.length - 1), ly = yi(last.v || 0);
        svg.append(s("circle", { cx: lx, cy: ly, r: 3.5, style: `fill:var(${sr.color || "--s1"})` }));
        const tx = s("text", { x: lx + 7, y: ly + 4, class: "endlabel" });
        tx.textContent = series.length > 1 ? sr.name : (opts.yfmt || nf)(last.v);
        svg.append(tx);
      }
    });
    const cross = s("line", { y1: T, y2: T + ih, class: "cross", visibility: "hidden" });
    const dots = series.map((sr) => { const c = s("circle", { r: 4, style: `fill:var(${sr.color || "--s1"});stroke:var(--panel);stroke-width:2`, visibility: "hidden" }); svg.append(c); return c; });
    svg.append(cross);
    const hit = s("rect", { x: L, y: T, width: iw, height: ih, fill: "transparent" });
    svg.append(hit);
    host.append(svg);
    const tip = tooltip(host);
    function show(evt) {
      const r = svg.getBoundingClientRect();
      const px = (evt.clientX - r.left) * (W / r.width);
      let best = 0, bd = Infinity;
      pts0.forEach((p, i) => { const dd = Math.abs(xi(p, i) - px); if (dd < bd) { bd = dd; best = i; } });
      const x = xi(pts0[best], best);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
      tip.replaceChildren();
      const h = document.createElement("b"); h.textContent = opts.tipX ? opts.tipX(xs[best]) : xs[best]; tip.append(h);
      series.forEach((sr, k) => {
        const p = sr.points[best]; if (!p) return;
        dots[k].setAttribute("cx", x); dots[k].setAttribute("cy", yi(p.v || 0)); dots[k].setAttribute("visibility", "visible");
        const row = document.createElement("div");
        row.innerHTML = `<i style="background:var(${sr.color || "--s1"})"></i>`;
        row.append(`${sr.name}: ${(opts.yfmt || nf)(p.v)}`);
        tip.append(row);
      });
      for (const m of opts.markers || []) if (m.x === xs[best]) { const row = document.createElement("div"); row.className = "tt-note"; row.textContent = m.label; tip.append(row); }
      tip.hidden = false;
      placeTip(tip, host, (x / W) * r.width, (evt.clientY - r.top));
    }
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); });
    if (opts.onClick) hit.addEventListener("click", (evt) => {
      const r = svg.getBoundingClientRect(); const px = (evt.clientX - r.left) * (W / r.width);
      let best = 0, bd = Infinity; pts0.forEach((p, i) => { const dd = Math.abs(xi(p, i) - px); if (dd < bd) { bd = dd; best = i; } });
      opts.onClick(xs[best], best);
    });
  }

  /* rows: [{label, v, note}] horizontal bars, one hue, value labels at bar end. */
  function bars(host, rows, opts = {}) {
    host.classList.add("chart");
    host.replaceChildren();
    if (!rows.length) { host.append(Object.assign(document.createElement("p"), { className: "empty", textContent: opts.empty || "No data yet." })); return; }
    const max = Math.max(...rows.map((r) => r.v || 0)) || 1;
    const wrap = document.createElement("div"); wrap.className = "hbars";
    const tip = tooltip(host);
    for (const r of rows) {
      const row = document.createElement("div"); row.className = "hbar";
      const lab = document.createElement("span"); lab.className = "hbar-l"; lab.textContent = r.label;
      const track = document.createElement("span"); track.className = "hbar-t";
      const fill = document.createElement("span"); fill.className = "hbar-f";
      fill.style.width = Math.max(1, (r.v / max) * 100) + "%"; fill.style.background = `var(${opts.color || "--s1"})`;
      track.append(fill);
      const val = document.createElement("span"); val.className = "hbar-v"; val.textContent = (opts.fmt || nf)(r.v);
      row.append(lab, track, val);
      row.addEventListener("pointerenter", (e) => {
        tip.replaceChildren(Object.assign(document.createElement("b"), { textContent: r.label }), document.createTextNode(` ${(opts.fmt || nf)(r.v)}`));
        if (r.note) tip.append(Object.assign(document.createElement("div"), { className: "tt-note", textContent: r.note }));
        tip.hidden = false; const hr = host.getBoundingClientRect(); placeTip(tip, host, e.clientX - hr.left, e.clientY - hr.top);
      });
      row.addEventListener("pointerleave", () => (tip.hidden = true));
      wrap.append(row);
    }
    host.append(wrap);
  }

  function spark(host, points, color = "--s1") {
    host.replaceChildren();
    if (!points || points.length < 2) return;
    const W = 120, H = 32, vs = points.map((p) => p.v || 0), max = Math.max(...vs) || 1, min = Math.min(...vs);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, "aria-hidden": "true", preserveAspectRatio: "none" });
    const d = vs.map((v, i) => `${i ? "L" : "M"}${(i / (vs.length - 1) * (W - 4) + 2).toFixed(1)},${(H - 3 - (v - min) / ((max - min) || 1) * (H - 6)).toFixed(1)}`).join("");
    svg.append(s("path", { d, fill: "none", style: `stroke:var(${color})`, "stroke-width": 1.6, "vector-effect": "non-scaling-stroke" }));
    host.append(svg);
  }

  /* points: [{x, y, label, id}] ; single hue, >=8px markers */
  function scatter(host, points, opts = {}) {
    host.classList.add("chart");
    host.replaceChildren();
    if (points.length < 3) { host.append(Object.assign(document.createElement("p"), { className: "empty", textContent: "Not enough data points." })); return; }
    const W = Math.max(280, host.clientWidth || 600), H = opts.height || 240, L = 46, R = 14, T = 10, B = 34;
    const iw = W - L - R, ih = H - T - B;
    const xmin = Math.min(...points.map((p) => p.x)), xmax = Math.max(...points.map((p) => p.x));
    const ymax = niceMax(Math.max(...points.map((p) => p.y)));
    const X = (v) => L + (v - xmin) / ((xmax - xmin) || 1) * iw, Y = (v) => T + ih - v / ymax * ih;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img", "aria-label": opts.label || "scatter" });
    for (const f of [0, 0.5, 1]) {
      svg.append(s("line", { x1: L, x2: L + iw, y1: T + ih * f, y2: T + ih * f, class: "grid" }));
      const tx = s("text", { x: L - 6, y: T + ih * f + 4, "text-anchor": "end", class: "axis" }); tx.textContent = (opts.yfmt || nf)(ymax * (1 - f)); svg.append(tx);
    }
    for (const [v, a] of [[xmin, "start"], [xmax, "end"]]) { const tx = s("text", { x: X(v), y: T + ih + 16, "text-anchor": a, class: "axis" }); tx.textContent = (opts.xfmt || ((x) => x.toFixed(2)))(v); svg.append(tx); }
    const xl = s("text", { x: L + iw / 2, y: H - 2, "text-anchor": "middle", class: "axis" }); xl.textContent = opts.xLabel || ""; svg.append(xl);
    const tip = tooltip(host);
    for (const p of points) {
      const c = s("circle", { cx: X(p.x), cy: Y(p.y), r: 5, class: "dot", style: `fill:var(${p.flag ? "--s3" : "--s1"})` });
      c.addEventListener("pointerenter", (e) => {
        tip.replaceChildren(Object.assign(document.createElement("b"), { textContent: p.label }));
        tip.append(Object.assign(document.createElement("div"), { textContent: `${opts.xLabel}: ${(opts.xfmt || ((x) => x.toFixed(2)))(p.x)} · ${opts.yLabel}: ${(opts.yfmt || nf)(p.y)}` }));
        tip.hidden = false; const hr = host.getBoundingClientRect(); placeTip(tip, host, e.clientX - hr.left, e.clientY - hr.top);
      });
      c.addEventListener("pointerleave", () => (tip.hidden = true));
      if (opts.onClick) c.addEventListener("click", () => opts.onClick(p));
      svg.append(c);
    }
    host.append(svg);
  }

  window.Charts = { line, bars, spark, scatter, nf };
})();
