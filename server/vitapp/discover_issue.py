"""Adds a new entry from a user search: from a GitHub issue ("Προσθήκη: ...") or from the
Cloudflare Worker (workflow inputs). Validates it, harvests it and keeps it only if the
sources returned enough material. Prints a short Greek result line."""
import os, re, sys
from . import store, harvest

KINDS = {"i", "s", "h", "f", "g"}
NAME_RE = re.compile(r"[\w \-+'.,()/]{2,80}")
MIN_STUDIES, MIN_TEXTS = 3, 20


def parse(body):
    vals = {}
    for line in (body or "").splitlines():
        m = re.match(r"\s*(kind|q|en)\s*:\s*(.*)$", line, re.I)
        if m:
            vals[m.group(1).lower()] = m.group(2).strip()
    return check(vals.get("kind", ""), vals.get("q", ""), vals.get("en", ""))


def check(kind, q, en):
    kind, q, en = (kind or "").strip(), (q or "").strip()[:80], (en or "").strip()[:80]
    if kind == "g":
        kind = "h"
    if kind not in KINDS:
        raise ValueError("Λείπει ή είναι λάθος το είδος (kind).")
    if not q or not NAME_RE.fullmatch(q):
        raise ValueError("Λείπει ή δεν είναι έγκυρος ο όρος αναζήτησης (q).")
    if not re.fullmatch(r"[A-Za-z0-9 \-+'.,]{2,80}", en or ""):
        raise ValueError("Χρειάζεται ο όρος στα αγγλικά (en), μόνο λατινικοί χαρακτήρες.")
    return kind, q, en


def add(kind, q, en):
    id_ = "d-" + store.slug(en)
    path = store.STATE / "discovered" / kind / f"{id_}.json"
    ents = store.load_entities()
    if (kind, id_) in ents and not path.exists():
        return id_, store.read_json(store.auto_path(kind, id_), {}) or {}
    cat = {"i": "Από αναζήτηση", "s": "Από αναζήτηση", "h": "Συνήθεια (από αναζήτηση)", "f": "Τροφή (από αναζήτηση)"}[kind]
    entry = {"t": kind, "id": id_, "n": q[:1].upper() + q[1:], "en": en, "k": [q, en], "cat": cat,
             "sum": "Νέα καταχώριση από αναζήτηση χρήστη. Περιέχει μόνο αυτόματα αντλημένα δεδομένα.", "b": [], "u": [], "s": [], "f": [], "v": []}
    if kind == "s":
        entry.update(doctor=True, alert="Αυτόματη καταχώριση χωρίς ιατρικό έλεγχο. Οι μελέτες και τα σχόλια μπορεί να αφορούν παρόμοια αλλά διαφορετική πάθηση. Μην ξεκινήσετε συμπλήρωμα χωρίς τον γιατρό σας.")
    store.write_json(path, entry)
    a = harvest.harvest_one(kind, id_, store.load_entities())
    if len(a.get("ps", [])) + len(a.get("po", [])) < MIN_STUDIES:   # needs real studies, comments alone are not enough
        path.unlink(missing_ok=True)
        store.auto_path(kind, id_).unlink(missing_ok=True)
        raise ValueError(f"Βρέθηκαν λιγότερες από {MIN_STUDIES} μελέτες για το «{en}», οπότε δεν προστέθηκε.")
    store.build_all()
    return id_, a


if __name__ == "__main__":
    try:
        if os.environ.get("DISCOVER_EN"):
            kind, q, en = check(os.environ.get("DISCOVER_KIND"), os.environ.get("DISCOVER_Q"), os.environ.get("DISCOVER_EN"))
        else:
            kind, q, en = parse(os.environ.get("ISSUE_BODY", ""))
        id_, a = add(kind, q, en)
        print(f"Προστέθηκε το «{q}»: {len(a.get('ps', []))} μελέτες, {a.get('fn', 0)} σχόλια χρηστών (#{kind}-{id_}).")
    except ValueError as e:
        print(f"Δεν προστέθηκε: {e}")
