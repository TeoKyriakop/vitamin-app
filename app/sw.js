// Keeps the app usable offline while staying small on the phone:
// app shell is cached; entries are cached on first view, at most MAX_ENTRIES of them.
const SHELL = "vc-shell-v1", DATA = "vc-data-v1", MAX_ENTRIES = 150;
self.addEventListener("install", e => e.waitUntil(caches.open(SHELL).then(c => c.addAll(["./", "icon.svg", "manifest.webmanifest"])).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => ![SHELL, DATA].includes(k)).map(k => caches.delete(k)))).then(() => self.clients.claim())));
async function trim(){
  const c = await caches.open(DATA), keys = await c.keys();
  for(let i = 0; i < keys.length - MAX_ENTRIES; i++) await c.delete(keys[i]);
}
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if(e.request.method !== "GET" || url.origin !== location.origin || url.pathname.includes("/api/")) return;
  if(url.pathname.includes("/data/e/")){            // entries: cache first, refresh in background
    e.respondWith(caches.open(DATA).then(async c => {
      const hit = await c.match(e.request);
      const net = fetch(e.request).then(r => { if(r.ok){ c.put(e.request, r.clone()); trim(); } return r; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  // shell and index: network first, cache as fallback for offline use
  e.respondWith(fetch(e.request).then(r => { if(r.ok){ const cp = r.clone(); caches.open(SHELL).then(c => c.put(e.request, cp)); } return r; }).catch(() => caches.match(e.request)));
});
