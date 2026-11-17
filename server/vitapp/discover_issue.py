"""Turns a GitHub issue "Προσθήκη: ..." into a new entry: validates it, harvests it,
rebuilds the data. Reads the issue from the environment set by the workflow.
Prints a short Greek result line used as the issue comment."""
import os, re, sys
from . import store, harvest

KINDS = {"i", "s", "h", "f", "g"}


def parse(body):
    vals = {}
    for line in (body or "").splitlines():
        m = re.match(r"\s*(kind|q|en)\s*:\s*(.*)$", line, re.I)
        if m:
            vals[m.group(1).lower()] = m.group(2).strip()
    kind, q, en = vals.get("kind", ""), vals.get("q", "")[:80], vals.get("en", "")[:80]
    if kind not in KINDS:
        raise ValueError("Λείπει ή είναι λάθος το είδος (kind).")
    if not q:
        raise ValueError("Λείπει ο όρος αναζήτησης (q).")
    if not re.fullmatch(r"[A-Za-z0-9 \-+'.,]{2,80}", en or ""):
        raise ValueError("Χρειάζεται ο όρος στα αγγλικά (en), μόνο λατινικοί χαρακτήρες.")
    return kind, q, en


def add(kind, q, en):
    disc = store.read_json(store.STATE / "discovered.json", []) or []
    id_ = "d-" + store.slug(en)
    if not any(d["id"] == id_ and d["t"] == kind for d in disc):
        cat = {"i": "Από αναζήτηση", "s": "Από αναζήτηση", "h": "Συνήθεια (από αναζήτηση)", "f": "Τροφή (από αναζήτηση)", "g": "Στόχος (από αναζήτηση)"}[kind]
        disc.append({"t": kind, "id": id_, "n": q[:1].upper() + q[1:], "en": en, "k": [q, en], "cat": cat,
                     "sum": "Νέα καταχώριση από αναζήτηση. Περιέχει μόνο αυτόματα αντλημένα δεδομένα.", "b": [], "u": [], "s": [], "f": [], "v": []})
        store.write_json(store.STATE / "discovered.json", disc)
    a = harvest.harvest_one(kind, id_, store.load_entities())
    store.build_all()
    return id_, a


if __name__ == "__main__":
    try:
        kind, q, en = parse(os.environ.get("ISSUE_BODY", ""))
        id_, a = add(kind, q, en)
        print(f"Προστέθηκε το «{q}»: {len(a.get('ps', []))} μελέτες, {a.get('fn', 0)} αναρτήσεις φόρουμ. "
              f"Θα εμφανιστεί στην εφαρμογή σε λίγα λεπτά (#{kind}-{id_}).")
    except ValueError as e:
        print(f"Δεν προστέθηκε: {e}")
        sys.exit(0)
