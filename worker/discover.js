// Cloudflare Worker: receives a new search from the app and starts the GitHub harvest for it.
// Settings (Cloudflare → Worker → Settings → Variables and Secrets):
//   GITHUB_TOKEN   (secret)  fine-grained token, only this repository, permission Actions: Read and write
//   REPO           (text)    e.g. TeoKyriakop/vitamin-app
//   ALLOWED_ORIGIN (text)    e.g. https://teokyriakop.github.io
//   SITE_URL       (text)    e.g. https://teokyriakop.github.io/vitamin-app/
//   DAILY_LIMIT    (text)    optional, default 150 new entries per day

const KINDS = new Set(["i", "s", "h", "f"]);
const EN_RE = /^[A-Za-z0-9 \-+'.,]{2,80}$/;
const NAME_RE = /^[\p{L}\p{N} \-+'.,()/]{2,80}$/u;

function norm(s) {
  return s.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "").replace(/ς/g, "σ")
    .replace(/[^\p{L}\p{N}_ ]/gu, " ").replace(/\s+/g, " ").trim();
}
async function slug(s) {   // must match server/vitapp/store.py slug()
  const n = norm(s);
  const a = n.replace(/[^a-z0-9 ]/g, "").trim().replace(/ +/g, "-").slice(0, 50);
  const h = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(n));
  const hex = [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, "0")).join("");
  return (a || "x") + "-" + hex.slice(0, 6);
}
const json = (obj, status, cors) => new Response(JSON.stringify(obj), {status, headers: {"Content-Type": "application/json; charset=utf-8", ...cors}});

// Small counters in the edge cache: per visitor per hour and for the whole day (best effort).
async function bump(key, ttl) {
  const cache = caches.default, url = "https://counter.local/" + encodeURIComponent(key);
  const hit = await cache.match(url);
  const n = (hit ? +(await hit.text()) : 0) + 1;
  await cache.put(url, new Response(String(n), {headers: {"Cache-Control": `max-age=${ttl}`}}));
  return n;
}

export default {
  async fetch(req, env) {
    const origin = req.headers.get("Origin") || "";
    const allowed = (env.ALLOWED_ORIGIN || "").split(",").map(s => s.trim()).filter(Boolean);
    const cors = allowed.includes(origin) ? {"Access-Control-Allow-Origin": origin, "Vary": "Origin"} : {};
    if (req.method === "OPTIONS") return new Response(null, {status: 204, headers: {...cors, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400"}});
    if (req.method !== "POST") return json({ok: true, service: "vitamin-compass discover"}, 200, cors);
    if (!cors["Access-Control-Allow-Origin"]) return json({error: "origin"}, 403, cors);

    let b; try { b = await req.json(); } catch { return json({error: "Λάθος αίτημα"}, 400, cors); }
    const kind = String(b.kind || ""), en = String(b.en || "").trim(), name = String(b.name || b.q || "").trim();
    if (!KINDS.has(kind) || !EN_RE.test(en) || !NAME_RE.test(name)) return json({error: "Μη έγκυρος όρος"}, 400, cors);

    const id = "d-" + await slug(en);
    // Already in the shared base? Nothing to do.
    try {
      const idx = await (await fetch(new URL("data/index.json", env.SITE_URL), {cf: {cacheTtl: 300}})).json();
      if (idx.e.some(r => r[0] === kind && r[1] === id)) return json({ok: true, t: kind, id, exists: true}, 200, cors);
    } catch {}

    const ip = req.headers.get("CF-Connecting-IP") || "x";
    if (await bump("ip:" + ip + ":" + new Date().toISOString().slice(0, 13), 3600) > 10) return json({error: "Πολλά αιτήματα. Δοκιμάστε αργότερα."}, 429, cors);
    if (await bump("day:" + new Date().toISOString().slice(0, 10), 86400) > (+env.DAILY_LIMIT || 150)) return json({error: "Συμπληρώθηκε το ημερήσιο όριο νέων καταχωρίσεων."}, 429, cors);
    if (await bump("term:" + kind + ":" + id, 3600) > 1) return json({ok: true, t: kind, id, queued: true}, 200, cors);

    const r = await fetch(`https://api.github.com/repos/${env.REPO}/actions/workflows/harvest.yml/dispatches`, {
      method: "POST",
      headers: {"Authorization": "Bearer " + env.GITHUB_TOKEN, "Accept": "application/vnd.github+json", "User-Agent": "vitamin-compass-worker", "X-GitHub-Api-Version": "2022-11-28"},
      body: JSON.stringify({ref: "main", inputs: {kind, q: name, en}})
    });
    if (r.status !== 204) return json({error: "Η προσθήκη δεν ξεκίνησε (" + r.status + ")"}, 502, cors);
    return json({ok: true, t: kind, id, queued: true}, 202, cors);
  }
};
