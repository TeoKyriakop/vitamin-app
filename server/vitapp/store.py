"""Builds the data the app downloads: one tiny index plus one small file per entry.

Layout written to <app>/data/:
  index.json            names + search keywords for every entry (~20-30 KB)
  e/<type>/<id>.json    one entry with everything its three windows need (3-10 KB)
Types: i = vitamin/supplement, s = symptom, h = habit, f = food, g = lifestyle goal.
"""
import json, os, re, hashlib, unicodedata, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"
STATE = Path(os.environ.get("VITAPP_STATE", ROOT / "state"))
APP = Path(os.environ.get("VITAPP_APP", ROOT.parent / "app"))


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("ς", "σ")
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]", " ", s)).strip()


def slug(s):
    n = norm(s)
    a = re.sub(r"[^a-z0-9 ]", "", n).strip().replace(" ", "-")[:50]
    return (a or "x") + "-" + hashlib.sha1(n.encode()).hexdigest()[:6]


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return data


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_entities(include_content=True):
    """All entries keyed by (type, id): curated seed files + entries discovered from searches.
    Types: i supplement, s condition, h habit, g goal, f food, q frequent question."""
    v = read_json(SEED / "vitamins.json")
    l = read_json(SEED / "lifestyle.json")
    f = read_json(SEED / "foods.json")
    c = (read_json(SEED / "content.json") if include_content else None) or {}
    ents = {}
    for t, rows in (("i", v["items"] + c.get("items", [])), ("s", v["symptoms"] + c.get("symptoms", [])),
                    ("h", l["habits"] + c.get("habits", [])), ("g", l["goals"]), ("f", f["foods"] + c.get("foods", [])),
                    ("q", c.get("faq", []))):
        for r in rows:
            ents[(t, r["id"])] = dict(r)
    for f in c.get("extra_studies", []):
        if (f[0], f[1]) in ents:
            ents[(f[0], f[1])].setdefault("s", []).append(f[2:9])
    for r in read_json(STATE / "discovered.json", []) or []:   # older single-file format
        ents.setdefault((r["t"], r["id"]), dict(r))
    for p in sorted((STATE / "discovered").glob("*/*.json")):   # one file per entry
        r = read_json(p)
        if r:
            ents.setdefault((r["t"], r["id"]), dict(r))
    return ents


def auto_path(t, id_):
    return STATE / "auto" / t / f"{id_}.json"


# ------------------------------------------------------------------ search terms
def pubmed_term(t, e, ents):
    if e.get("pq"):
        base = e["pq"]
    else:
        parts = [p.strip() for p in re.split(r"[/()]", e.get("en") or e["n"]) if p.strip()]
        base = " OR ".join(f'"{p}"[tiab]' for p in parts)
    if t == "s":
        names = [ents[("i", x[0])].get("en", "").split("/")[0].split("(")[0].strip() for x in e.get("v", []) if ("i", x[0]) in ents]
        extra = " OR ".join(f'"{n}"[tiab]' for n in names if n) or "supplement*[tiab] OR vitamin*[tiab]"
        base = f'({e.get("en") or e["n"]}) AND ({extra})'
    elif t == "g":
        base = f"({base}) AND (lifestyle[tiab] OR exercise[tiab] OR diet[tiab] OR smoking[tiab] OR sleep[tiab])"
    return base


def forum_query(t, e):
    en = re.split(r"[/(]", e.get("en") or e["n"])[0].strip()
    return {"s": f"{en} supplement", "g": f"improve {en}"}.get(t, en)


SUBS = {"i": ["Supplements", "Nootropics", "Biohackers", "vitamins"],
        "s": ["Supplements", "Nootropics", "Biohackers", "AskDocs"],
        "h": ["DecidingToBeBetter", "getdisciplined", "Biohackers"],
        "f": ["nutrition", "EatCheapAndHealthy", "Biohackers"],
        "g": ["DecidingToBeBetter", "Fitness", "Biohackers"]}


# ------------------------------------------------------------------ build
GRADE = {"A": 3, "B": 2, "C": 1}


def _rank_study(s):
    t = (s[3] + s[2]).lower()
    return (0 if re.search("μετα-ανάλυση|cochrane|συστηματική|ομπρέλα", t) else 1 if "rct" in t else 2, -int(s[1] or 0) if str(s[1]).isdigit() else 0)


def _studies_of(refs, ents, t):
    out = []
    for rid in refs:
        e = ents.get((t, rid))
        if e:
            out += [list(s) + [e["n"]] for s in e.get("s", [])]
    return sorted(out, key=_rank_study)


def build_entry(t, id_, ents):
    e = dict(ents[(t, id_)])
    e["t"] = t
    name = lambda tt, x: ents[(tt, x)]["n"] if (tt, x) in ents else None
    if t == "i":
        e["foods"] = [[x, name("f", x)] for x in e.get("fl", []) if name("f", x)]
        e["syms"] = [[k[1], v["n"]] for k, v in ents.items() if k[0] == "s" and any(x[0] == id_ for x in v.get("v", []) + v.get("u", []))]
    elif t == "s":
        ids = list(dict.fromkeys([x[0] for x in e.get("v", []) + e.get("u", [])] + [a[2] for a in e.get("avoid", []) if a[2]]))
        e["ref"] = {x: {"n": name("i", x), "f0": (ents[("i", x)].get("f") or [None])[0], "fd0": (ents[("i", x)].get("fd") or [None])[0]} for x in ids if name("i", x)}
        allst = _studies_of([x[0] for x in e.get("v", [])], ents, "i")
        words = [w for w in {norm(x) for x in [e.get("en", "")] + e.get("k", [])} if len(w) > 3]
        rel = [s for s in allst if any(w[:max(4, len(w) - 2)] in norm(s[5] + " " + s[6]) for w in words)]
        own = sorted([list(x) for x in e.get("s", [])], key=_rank_study)
        e["st"] = (own + rel)[:14]   # never fill with unrelated studies; the PubMed harvest adds condition-specific ones
        g = ents.get(("g", e.get("goal")))
        if g:
            e["life"] = [["h", x[0], name("h", x[0]), x[1], x[2]] for x in g.get("v", []) if name("h", x[0])][:5] + \
                        [["f", x[0], name("f", x[0]), x[1], x[2]] for x in g.get("fd", []) if name("f", x[0])][:4]
            e["goalref"] = [e["goal"], g["n"]]
    elif t == "g":
        e["ref"] = {}
        for x in e.get("v", []) + e.get("u", []):
            h = ents.get(("h", x[0]))
            if h:
                e["ref"]["h:" + x[0]] = {"n": h["n"], "f0": (h.get("f") or [None])[0]}
        for x in e.get("fd", []):
            if name("f", x[0]):
                e["ref"]["f:" + x[0]] = {"n": name("f", x[0])}
        for x in e.get("x", []):
            if name("i", x[0]):
                e["ref"]["i:" + x[0]] = {"n": name("i", x[0])}
        e["st"] = sorted(_studies_of([x[0] for x in e.get("v", [])], ents, "h") + _studies_of([x[0] for x in e.get("fd", [])], ents, "f"), key=_rank_study)[:16]
    elif t in ("h", "f"):
        key = "v" if t == "h" else "fd"
        e["goals"] = [[k[1], v["n"]] for k, v in ents.items() if k[0] == "g" and any(x[0] == id_ for x in v.get(key, []))]
        if t == "f":
            e["nutr"] = [[x, name("i", x)] for x in e.get("nut", []) if name("i", x)]
    if t == "q":
        e["refs"] = [[lt, li, ents[(lt, li)]["n"]] for lt, li in e.get("links", []) if (lt, li) in ents]
    if t in ("i", "s", "h", "f", "g"):
        e["faq"] = [[k[1], v["n"]] for k, v in ents.items() if k[0] == "q" and [t, id_] in v.get("links", [])][:6]
    auto = read_json(auto_path(t, id_))
    if auto:
        e["auto"] = auto
    for k in ("pq", "subs", "fl", "nut"):
        e.pop(k, None)
    return e


def build_all():
    ents = load_entities()
    out = APP / "data"
    index = []
    keep = set()
    for (t, id_), e in sorted(ents.items()):
        data = write_json(out / "e" / t / f"{id_}.json", build_entry(t, id_, ents))
        keep.add(out / "e" / t / f"{id_}.json")
        kw = " ".join(dict.fromkeys(norm(x) for x in [e["n"], e.get("en", "")] + e.get("k", []) if x))
        index.append([t, id_, e["n"], e.get("cat", ""), kw, hashlib.sha1(data.encode()).hexdigest()[:10]])
    for p in (out / "e").glob("*/*.json"):
        if p not in keep:
            p.unlink()
    write_json(out / "index.json", {"v": time.strftime("%Y-%m-%d %H:%M"), "e": index})
    return len(index)
