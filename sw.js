// Gør forsiden installérbar som app (Android/Chrome) og åbner den også uden net. Dashboardet selv ligger på din server.
const V = "hubai-v1";
const SHELL = ["./", "download/", "assets/site.css", "assets/logo.svg", "assets/favicon.svg", "assets/icon-192.png", "assets/icon-512.png",
  "assets/apple-touch-icon.png", "manifest.webmanifest"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== V).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;          // kun egne filer; aldrig dashboardet
  if (req.mode === "navigate") {                                               // sider: nyeste først, ellers den gemte
    e.respondWith(fetch(req).then((r) => { const c = r.clone(); caches.open(V).then((x) => x.put(req, c)); return r; })
      .catch(() => caches.match(req).then((m) => m || caches.match("./"))));
    return;
  }
  e.respondWith(caches.match(req).then((m) => m || fetch(req).then((r) => { const c = r.clone(); caches.open(V).then((x) => x.put(req, c)); return r; })));
});
