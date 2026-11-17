"""Fetches studies and forum experiences for every entry and caches them in state/auto.
Run:  python -m vitapp.harvest            (only entries older than REFRESH_DAYS)
      python -m vitapp.harvest --all      (everything)
      python -m vitapp.harvest --only i/mg (one entry)
      python -m vitapp.harvest --build    (no network, just rebuild app/data)"""
import argparse, logging, os, time
from . import sources, lexicon, store

log = logging.getLogger("vitapp.harvest")
REFRESH_DAYS = float(os.environ.get("REFRESH_DAYS", 7))
DSLD = os.environ.get("VITAPP_DSLD", "1") != "0"
_exhausted = set()   # sources whose daily quota ran out during this run

FORUM_SOURCES = [
    ("youtube", lambda t, e: sources.youtube_texts(store.forum_query(t, e) + {"i": " experience", "s": " what helped", "f": " benefits", "h": " results", "g": " tips"}[t])),
    ("hackernews", lambda t, e: sources.hackernews_texts(store.forum_query(t, e))),
    ("stackexchange", lambda t, e: sources.stackexchange_texts(store.forum_query(t, e), t)),
    ("lemmy", lambda t, e: sources.lemmy_texts(store.forum_query(t, e))),
    ("reddit", lambda t, e: sources.reddit_texts(store.forum_query(t, e), store.SUBS[t])),
]


def is_stale(t, id_):
    a = store.read_json(store.auto_path(t, id_))
    if not a or time.time() - a.get("ts", 0) > REFRESH_DAYS * 86400:
        return True
    if "po" not in a:   # harvested before "other studies" existed
        return True
    # YouTube has a daily quota: entries still missing it are retried on the next days
    return bool(os.environ.get("YOUTUBE_API_KEY")) and "youtube" not in (a.get("fsrc") or {})


def harvest_one(t, id_, ents):
    e = ents[(t, id_)]
    prev = store.read_json(store.auto_path(t, id_), {}) or {}
    auto = {"ts": time.time(), "upd": time.strftime("%Y-%m-%d"), "err": []}

    # 1) studies: PubMed, falling back to Europe PMC
    term = store.pubmed_term(t, e, ents)
    try:
        studies = sources.pubmed_search(term, retmax=20)
        try:
            cites = sources.europepmc_citations([s["pmid"] for s in studies])
            for s in studies:
                s["cites"] = cites.get(s["pmid"], 0)
        except sources.SourceError as err:
            auto["err"].append(str(err))
    except sources.SourceError as err:
        auto["err"].append(str(err))
        try:
            studies = sources.europepmc_search(term.replace("[tiab]", ""), 20)
        except sources.SourceError as err2:
            auto["err"].append(str(err2))
            studies = None
    if studies is None:
        auto["ps"], auto["lit"] = prev.get("ps", []), prev.get("lit", [])
    else:
        rank = {"Μετα-ανάλυση": 0, "Συστηματική ανασκόπηση": 1, "RCT": 2, "Κλινική μελέτη": 3}
        studies.sort(key=lambda s: (rank.get(s["type"], 3), -s.get("cites", 0)))
        auto["ps"] = [[s["pmid"], s["title"], s["year"], s["journal"], s["type"], s.get("cites", 0), s["author"]] for s in studies[:15]]
        auto["lit"] = [[r[0], r[1]] for r in lexicon.tally([s["title"] for s in studies]) if r[1] >= 2][:8]
        auto["pq"] = term

    # 1b) other studies (observational, small, reviews): weaker evidence, shown separately
    try:
        others = sources.pubmed_search(term, retmax=12, strong=False)
        auto["po"] = [[s["pmid"], s["title"], s["year"], s["journal"], s["type"], 0, s["author"]] for s in others[:10]]
    except sources.SourceError as err:
        auto["err"].append(str(err))
        auto["po"] = prev.get("po", [])

    # 2) user experiences: count how often each effect repeats, per source
    per = dict(prev.get("fsrc") or {})
    for src, fn in FORUM_SOURCES:
        if src in _exhausted or os.environ.get(f"VITAPP_{src.upper()}", "1") == "0":
            continue
        try:
            texts = fn(t, e)
            per[src] = {"n": len(texts), "k": lexicon.tally_keys(texts), "upd": auto["upd"]}
        except sources.QuotaError as err:
            _exhausted.add(src)          # stop using this source until the next run
            auto["err"].append(str(err))
        except sources.SourceError as err:
            auto["err"].append(str(err))
    if per:
        auto["fsrc"] = per
        auto["fn"] = sum(d.get("n", 0) for d in per.values())
        auto["fc"] = [r for r in lexicon.combine(per) if r[1] >= 2][:12]

    # 3) products on the market (supplements only)
    if DSLD and t == "i":
        try:
            auto["dsld"] = sources.dsld_products((e.get("en") or e["n"]).split("/")[0].split("(")[0].strip())
        except sources.SourceError as err:
            auto["err"].append(str(err))
            auto["dsld"] = prev.get("dsld", [])

    if not auto["err"]:
        auto.pop("err")
    store.write_json(store.auto_path(t, id_), auto)
    return auto


def run(only=None, everything=False, limit=None):
    ents = store.load_entities()
    if only:
        keys = [tuple(only.split("/", 1))]
    else:   # oldest (or never harvested) first, so daily batches rotate through everything
        keys = [k for k in ents if k[0] != "q" and (everything or is_stale(*k))]
        def order(k):
            a = store.read_json(store.auto_path(*k), {}) or {}
            return (bool(a), "youtube" in (a.get("fsrc") or {}), a.get("ts", 0))   # never harvested, then missing YouTube, then oldest
        keys.sort(key=order)
    limit = limit or int(os.environ.get("HARVEST_LIMIT") or 0) or None
    if limit:
        keys = keys[:limit]
    for i, (t, id_) in enumerate(keys, 1):
        a = harvest_one(t, id_, ents)
        log.info("[%d/%d] %s/%s: %d studies, %d forum posts%s", i, len(keys), t, id_, len(a.get("ps", [])),
                 a.get("fn", 0), " (errors: " + "; ".join(a["err"]) + ")" if a.get("err") else "")
    n = store.build_all()
    log.info("built %d entries", n)
    return len(keys)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if a.build:
        print("built", store.build_all(), "entries")
    else:
        run(a.only, a.all, a.limit)
