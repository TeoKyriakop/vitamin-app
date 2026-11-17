"""Compact content files -> seed entries.

Each file in server/content/ holds one entry per line; fields are separated by " | ",
list items by ";" and sub-fields by "~". Lines starting with # are comments.

items.txt     id | name | english | keywords | category | summary | benefits | forms | foods | warning
symptoms.txt  id | name | english | keywords | doctor(0/1) | alert | helps | avoid | not-to-confuse | habits | goal
habits.txt    id | name | english | keywords | category | summary | benefits | steps | warning
foods.txt     id | name | english | keywords | summary | benefits | how-to | nutrients(item ids, comma) | warning
faq.txt       id | question | keywords | answer | grade | links(t:id, comma)

benefits:  text~grade~note        forms/steps/foods: what~amount~note
helps:     item_id~grade~why      avoid: what~why~item_id   not-to-confuse: symptom_id~name~why
habits:    what~why~grade
Run: python -m vitapp.content   (validates and writes seed/content.json)"""
import json, sys
from pathlib import Path
from . import store

DIR = store.ROOT / "content"


def _l(s, n):
    out = []
    for part in [p for p in (s or "").split(";") if p.strip()]:
        f = [x.strip() for x in part.split("~")]
        out.append((f + [""] * n)[:n])
    return out


def _rows(name, n):
    p = DIR / name
    if not p.exists():
        return []
    rows = []
    for no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        f = [x.strip() for x in line.split(" | ")]
        if len(f) != n:
            raise ValueError(f"{name}:{no}: {len(f)} πεδία αντί για {n}: {line[:80]}")
        rows.append(f)
    return rows


def kw(s):
    return [k.strip() for k in s.split(",") if k.strip()]


def parse():
    out = {"items": [], "symptoms": [], "habits": [], "foods": [], "faq": []}
    for f in _rows("items.txt", 10):
        out["items"].append({"id": f[0], "n": f[1], "en": f[2], "k": kw(f[3]), "cat": f[4], "sum": f[5],
                             "b": _l(f[6], 3), "u": [], "s": [], "f": _l(f[7], 3), "fd": _l(f[8], 3), "fl": [], "w": f[9]})
    for f in _rows("symptoms.txt", 11):
        e = {"id": f[0], "n": f[1], "en": f[2], "k": kw(f[3]), "v": _l(f[6], 3), "u": [], "s": []}
        if f[4] == "1":
            e["doctor"] = True
        if f[5]:
            e["alert"] = f[5]
        if f[7]:
            e["avoid"] = [[a, b, c or None] for a, b, c in _l(f[7], 3)]
        if f[8]:
            e["diff"] = _l(f[8], 3)
        if f[9]:
            e["lifex"] = _l(f[9], 3)
        if f[10]:
            e["goal"] = f[10]
        out["symptoms"].append(e)
    for f in _rows("habits.txt", 9):
        out["habits"].append({"id": f[0], "n": f[1], "en": f[2], "k": kw(f[3]), "cat": f[4], "sum": f[5],
                              "b": _l(f[6], 3), "u": [], "s": [], "f": _l(f[7], 3), "w": f[8], "pq": f[2]})
    for f in _rows("foods.txt", 9):
        out["foods"].append({"id": f[0], "n": f[1], "en": f[2], "k": kw(f[3]), "cat": "Τροφή", "sum": f[4],
                             "b": _l(f[5], 3), "u": [], "s": [], "f": _l(f[6], 3), "nut": kw(f[7]), "w": f[8], "pq": f[2]})
    for f in _rows("faq.txt", 6):
        out["faq"].append({"id": f[0], "n": f[1], "k": kw(f[2]), "a": f[3], "g": f[4] if f[4] in "ABC" and f[4] else "",
                           "links": [x.strip().split(":", 1) for x in f[5].split(",") if ":" in x], "cat": "Συχνή ερώτηση"})
    return out


def validate(c):
    """Every link must point to an entry that exists; ids must be unique per type."""
    base = store.load_entities(include_content=False)
    ids = {t: {k[1] for k in base if k[0] == t} for t in "ishfgq"}
    for t, key in (("i", "items"), ("s", "symptoms"), ("h", "habits"), ("f", "foods"), ("q", "faq")):
        for e in c[key]:
            if e["id"] in ids[t]:
                raise ValueError(f"διπλό id {t}/{e['id']}")
            ids[t].add(e["id"])
    errs = []
    for e in c["symptoms"]:
        errs += [f"s/{e['id']}: άγνωστο συμπλήρωμα {x[0]}" for x in e["v"] if x[0] not in ids["i"]]
        errs += [f"s/{e['id']}: avoid άγνωστο {a[2]}" for a in e.get("avoid", []) if a[2] and a[2] not in ids["i"]]
        errs += [f"s/{e['id']}: diff άγνωστο {d[0]}" for d in e.get("diff", []) if d[0] not in ids["s"]]
        errs += [f"s/{e['id']}: βαθμός {x[1]}" for x in e["v"] if x[1] not in ("A", "B", "C")]
        if e.get("goal") and e["goal"] not in ids["g"]:
            errs.append(f"s/{e['id']}: άγνωστος στόχος {e['goal']}")
    for key in ("items", "habits", "foods"):
        for e in c[key]:
            errs += [f"{key}/{e['id']}: βαθμός {b[1]}" for b in e["b"] if b[1] not in ("A", "B", "C")]
    for e in c["foods"]:
        errs += [f"f/{e['id']}: άγνωστο θρεπτικό {x}" for x in e["nut"] if x not in ids["i"]]
    for e in c["faq"]:
        errs += [f"q/{e['id']}: άγνωστος σύνδεσμος {t}:{i}" for t, i in e["links"] if i not in ids.get(t, ())]
    if errs:
        raise ValueError("\n".join(errs))


if __name__ == "__main__":
    c = parse()
    validate(c)
    store.write_json(store.SEED / "content.json", c)
    print({k: len(v) for k, v in c.items()})
