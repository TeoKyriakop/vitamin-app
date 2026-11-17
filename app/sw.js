// Keeps the app usable offline. Entries are stored by the page itself (IndexedDB, size chosen
// by the user), so the worker caches only the app shell and the index.
const SHELL = "vc-shell-v2";
self.addEventListener("install", e => e.waitUntil(caches.open(SHELL).then(c => c.addAll(["./", "icon.svg", "manifest.webmanifest", "data/index.json"])).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if(e.request.method !== "GET" || url.origin !== location.origin || url.pathname.includes("/api/") || url.pathname.includes("/data/e/")) return;
  e.respondWith(fetch(e.request).then(r => { if(r.ok){ const cp = r.clone(); caches.open(SHELL).then(c => c.put(e.request, cp)); } return r; }).catch(() => caches.match(e.request, {ignoreSearch:true})));
});
