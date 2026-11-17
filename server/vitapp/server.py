"""HTTP server: serves the app (installable on phones), its data files, and a small API.

  python -m vitapp.server            -> http://0.0.0.0:8080

API
  GET  /api/health                     {"ok":true, ...}
  POST /api/discover {"kind","q","en"} adds a new entry from a search, harvests it, returns {"t","id"}
  POST /api/refresh  (Bearer ADMIN_TOKEN) harvest everything that is stale, in the background
Background: every hour, refreshes up to BATCH stale entries (default 8)."""
import gzip, hashlib, json, logging, os, re, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from . import store, harvest, site

log = logging.getLogger("vitapp.server")
PORT = int(os.environ.get("PORT", 8080))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
BATCH = int(os.environ.get("BATCH", 8))
INTERVAL = float(os.environ.get("INTERVAL_MIN", 60)) * 60
MAX_DISCOVERED = int(os.environ.get("MAX_DISCOVERED", 500))
TYPES = {"i", "s", "h", "f", "g"}
MIME = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json", ".png": "image/png"}
work_lock = threading.Lock()          # one harvest at a time
_last_discover = {"t": 0.0}


def rebuild():
    with work_lock:
        return store.build_all()


class Handler(BaseHTTPRequestHandler):
    server_version = "VitaminCompass"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, code, body, ctype, cache="no-cache", etag=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        if etag and self.headers.get("If-None-Match") == etag:
            self.send_response(304); self.send_header("ETag", etag); self.end_headers(); return
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(body) > 600 and not ctype.startswith("image/png")
        if gz:
            body = gzip.compress(body, 6)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")
        if gz:
            self.send_header("Content-Encoding", "gzip"); self.send_header("Vary", "Accept-Encoding")
        if etag:
            self.send_header("ETag", etag)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), MIME[".json"])

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            idx = store.read_json(store.APP / "data" / "index.json", {}) or {}
            return self._json(200, {"ok": True, "mode": "server", "entries": len(idx.get("e", [])), "updated": idx.get("v")})
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (store.APP / rel).resolve()
        if store.APP.resolve() not in f.parents or not f.is_file():
            return self._json(404, {"error": "not found"})
        body = f.read_bytes()
        if rel == "index.html":  # the page is written as body content; wrap it into a full installable document
            body = site.wrap(body)
        etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'
        # Entry files change only when re-harvested: let phones keep them a day and revalidate cheaply.
        cache = "public, max-age=86400" if rel.startswith("data/e/") else "no-cache"
        self._send(200, body, MIME.get(f.suffix, "application/octet-stream"), cache, etag)

    def _body(self):
        n = min(int(self.headers.get("Content-Length") or 0), 10000)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/refresh":
            if not ADMIN_TOKEN or self.headers.get("Authorization") != "Bearer " + ADMIN_TOKEN:
                return self._json(403, {"error": "Λάθος ή κενό ADMIN_TOKEN"})
            threading.Thread(target=lambda: _locked(harvest.run), daemon=True).start()
            return self._json(202, {"ok": True})
        if path == "/api/discover":
            return self._discover(self._body())
        self._json(404, {"error": "not found"})

    def _discover(self, b):
        kind, q, en = b.get("kind"), str(b.get("q") or "").strip()[:80], str(b.get("en") or "").strip()[:80]
        if kind not in TYPES or not q:
            return self._json(400, {"error": "Χρειάζεται είδος και όρος αναζήτησης"})
        if not en and re.search(r"[a-zA-Z]", q):
            en = q
        if not en or not re.fullmatch(r"[A-Za-z0-9 \-+'.,]+", en):
            return self._json(400, {"error": "Γράψτε τον όρο και στα αγγλικά, για αναζήτηση στο PubMed"})
        if time.time() - _last_discover["t"] < 5:
            return self._json(429, {"error": "Πολλά αιτήματα. Δοκιμάστε ξανά σε λίγα δευτερόλεπτα."})
        _last_discover["t"] = time.time()
        disc = store.read_json(store.STATE / "discovered.json", []) or []
        id_ = "d-" + store.slug(en)
        if not any(d["id"] == id_ and d["t"] == kind for d in disc):
            if len(disc) >= MAX_DISCOVERED:
                return self._json(507, {"error": "Η βάση νέων αναζητήσεων είναι γεμάτη"})
            cat = {"i": "Από αναζήτηση", "s": "Από αναζήτηση", "h": "Συνήθεια (από αναζήτηση)", "f": "Τροφή (από αναζήτηση)", "g": "Στόχος (από αναζήτηση)"}[kind]
            disc.append({"t": kind, "id": id_, "n": q[:1].upper() + q[1:], "en": en, "k": [q, en], "cat": cat,
                         "sum": "Νέα καταχώριση από αναζήτηση. Περιέχει μόνο αυτόματα αντλημένα δεδομένα.", "b": [], "u": [], "s": [], "f": [], "v": []})
            store.write_json(store.STATE / "discovered.json", disc)
        try:
            with work_lock:
                ents = store.load_entities()
                harvest.harvest_one(kind, id_, ents)
                store.build_all()
        except Exception as e:  # report, keep serving
            log.exception("discover failed")
            return self._json(502, {"error": f"Η άντληση απέτυχε: {e}"})
        self._json(200, {"t": kind, "id": id_})


def _locked(fn, *a, **kw):
    with work_lock:
        return fn(*a, **kw)


def scheduler():
    while True:
        try:
            n = _locked(harvest.run, None, False, BATCH)
            log.info("scheduled refresh: %d entries", n)
        except Exception:
            log.exception("scheduled refresh failed")
        time.sleep(INTERVAL)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("building data: %d entries", rebuild())
    if os.environ.get("VITAPP_SCHEDULER", "1") != "0":
        threading.Thread(target=scheduler, daemon=True).start()
    log.info("serving %s on :%d", store.APP, PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
