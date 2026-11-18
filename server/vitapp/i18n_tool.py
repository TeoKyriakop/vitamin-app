"""Helps translate the content into another language.

  python -m vitapp.i18n_tool export en 0 40   -> Greek text of entries 0..39 that are not translated yet (one JSON per line)
  python -m vitapp.i18n_tool merge en FILE    -> checks a file of translations and merges it into i18n/en.json
  python -m vitapp.i18n_tool status en        -> how many entries are translated

A translation line is {"key": "t/id", ...translated fields}. Fields per type:
  i: n k cat sum b u f fd w s     s: n k alert avoid diff lifex why_v why_u s     h: n k cat sum b u f w s
  f: n k sum b u f w s            g: n k why_v why_u why_x why_fd                q: n k a
The checker refuses a line if ids, grades, numbers or list lengths differ from the Greek."""
import json, re, sys
from . import store

FIELDS = {"i": "n k cat sum b u f fd w s", "s": "n k alert avoid diff lifex why_v why_u s", "h": "n k cat sum b u f w s",
          "f": "n k sum b u f w s", "g": "n k why_v why_u why_x why_fd", "q": "n k a"}
WHY = {"why_v": ("v", None), "why_u": ("u", 1), "why_x": ("x", 1), "why_fd": ("fd", 2)}


def greek(e, t):
    out = {}
    for f in FIELDS[t].split():
        if f in WHY:
            lst, col = WHY[f]
            col = col if col is not None else (2 if t in ("s", "g") else 1)
            vals = [x[col] if len(x) > col else "" for x in e.get(lst, [])]
            if any(vals):
                out[f] = vals
        elif e.get(f) not in (None, "", []):
            out[f] = e[f]
    return out


def _shape(v):   # what must stay identical: ids, grades, numbers, lengths
    if isinstance(v, list):
        return [_shape(x) for x in v]
    if isinstance(v, (int, float)) or v is None:
        return v
    s = str(v)
    if re.fullmatch(r"[ABC]|[a-z0-9_\-]+|\d[\d.,\-–]*", s):
        return s
    return "·"


def check(key, tr, src):
    errs = []
    t = key.split("/")[0]
    for f, v in tr.items():
        if f == "key":
            continue
        if f not in FIELDS[t].split():
            errs.append(f"{key}: άγνωστο πεδίο {f}")
        elif f not in src:
            errs.append(f"{key}: το {f} δεν υπάρχει στα ελληνικά")
        elif f in ("s", "avoid", "diff", "lifex", "b", "f", "fd", "u") and _shape(v) != _shape(src[f]):
            # studies: author/year/journal are kept, so compare length only for those columns
            if not (isinstance(v, list) and len(v) == len(src[f]) and all(isinstance(a, list) and len(a) == len(b) for a, b in zip(v, src[f]))):
                errs.append(f"{key}: διαφορετική δομή στο {f}")
            else:
                for a, b in zip(v, src[f]):
                    for x, y in zip(a, b):
                        if _shape(x) != _shape(y) and _shape(y) != "·":
                            errs.append(f"{key}: άλλαξε η τιμή «{y}» στο {f}")
        elif f != "k" and isinstance(src[f], list) and (not isinstance(v, list) or len(v) != len(src[f])):
            errs.append(f"{key}: διαφορετικό μήκος στο {f}")
    return errs


def main():
    cmd, lang = sys.argv[1], sys.argv[2]
    path = store.ROOT / "i18n" / f"{lang}.json"
    done = store.read_json(path, {}) or {}
    ents = store.load_entities()
    keys = [k for k in sorted(ents) if not ents[k]["id"].startswith("d-")]
    if cmd == "export":
        a, n = int(sys.argv[3]), int(sys.argv[4])
        todo = [k for k in keys if f"{k[0]}/{k[1]}" not in done][a:a + n]
        for k in todo:
            print(json.dumps({"key": f"{k[0]}/{k[1]}", **greek(ents[k], k[0])}, ensure_ascii=False, separators=(",", ":")))
    elif cmd == "merge":
        errs, added = [], 0
        for line in open(sys.argv[3], encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tr = json.loads(line)
            t, id_ = tr["key"].split("/", 1)
            src = greek(ents[(t, id_)], t)
            e = check(tr["key"], tr, src)
            if e:
                errs += e
                continue
            done[tr["key"]] = {k: v for k, v in tr.items() if k != "key"}
            added += 1
        store.write_json(path, done)
        print(f"προστέθηκαν {added}, σύνολο {len(done)}/{len(keys)}")
        if errs:
            print("\n".join(errs))
            sys.exit(1)
    elif cmd == "status":
        print(f"{len(done)}/{len(keys)}")


if __name__ == "__main__":
    main()
