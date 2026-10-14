// Offline shell only. API data is always fetched live (never served stale from cache).
const CACHE = "kgos-shell-v1";
const SHELL = ["/app.css", "/app.js", "/charts.js", "/icon.svg", "/icon-192.png", "/manifest.webmanifest"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/oauth")) return;
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).catch(() => new Response(
      "<!doctype html><meta name=viewport content='width=device-width'><body style='font:16px system-ui;background:#0b0b0b;color:#eee;padding:40px'>" +
      "<h1>Klip Growth OS isn't running</h1><p>Start it from the desktop shortcut, then reload.</p>", { headers: { "Content-Type": "text/html" } })));
    return;
  }
  if (SHELL.includes(url.pathname)) {
    e.respondWith(fetch(e.request).then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r; }).catch(() => caches.match(e.request)));
  }
});
