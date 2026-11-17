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
REDDIT = os.environ.get("VITAPP_REDDIT", "1") != "0"


def is_stale(t, id_):
    a = store.read_json(store.auto_path(t, id_))
    return not a or time.time() - a.get("ts", 0) > REFRESH_DAYS * 86400


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
        rank = {"Μετα-ανάλυση": 0, "Συστηματική ανασκόπηση": 1, "RCT": 2}
        studies.sort(key=lambda s: (rank.get(s["type"], 3), -s.get("cites", 0)))
        auto["ps"] = [[s["pmid"], s["title"], s["year"], s["journal"], s["type"], s.get("cites", 0), s["author"]] for s in studies[:15]]
        auto["lit"] = [[r[0], r[1]] for r in lexicon.tally([s["title"] for s in studies]) if r[1] >= 2][:8]
        auto["pq"] = term

    # 2) forum experiences: count how often each effect repeats across posts
    if REDDIT:
        try:
            texts = sources.reddit_texts(store.forum_query(t, e), store.SUBS[t])
            auto["fc"], auto["fn"] = [r for r in lexicon.tally(texts) if r[1] >= 2][:12], len(texts)
        except sources.SourceError as err:
            auto["err"].append(str(err))
            auto["fc"], auto["fn"] = prev.get("fc", []), prev.get("fn", 0)

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
    keys = [tuple(only.split("/", 1))] if only else [k for k in sorted(ents) if everything or is_stale(*k)]
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
