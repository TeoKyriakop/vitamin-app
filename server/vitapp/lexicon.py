"""Outcome lexicon: finds which effects a text talks about, and roughly whether
it says something good or bad about it. Used for forum posts and study titles."""
import re

# (key, Greek label, regex, is_side_effect)
OUTCOMES = [
    ("sleep", "Ύπνος", r"\b(sleep\w*|insomnia|fell asleep|falling asleep|slept)\b", False),
    ("anxiety", "Άγχος / ηρεμία", r"\b(anxi\w+|calm\w*|stress\w*|panic)\b", False),
    ("energy", "Ενέργεια / κόπωση", r"\b(energy|energi\w+|fatigue\w*|tired\w*|exhaust\w*|letharg\w*)\b", False),
    ("mood", "Διάθεση", r"\b(mood|depress\w*|happier|motivation)\b", False),
    ("focus", "Συγκέντρωση / μνήμη", r"\b(focus\w*|concentrat\w+|brain fog|clarity|memory|cogniti\w+)\b", False),
    ("cramps", "Κράμπες / σπασμοί", r"\b(cramp\w*|twitch\w*|spasm\w*)\b", False),
    ("headache", "Πονοκέφαλος / ημικρανία", r"\b(headache\w*|migraine\w*)\b", False),
    ("digestion", "Πέψη / φούσκωμα", r"\b(bloat\w*|digest\w*|constipat\w+|gut|bowel\w*)\b", False),
    ("diarrhea", "Διάρροια", r"\b(diarrh\w+|loose stool\w*|laxative)\b", True),
    ("nausea", "Ναυτία / ενόχληση στομάχου", r"\b(nause\w+|upset stomach|stomach (ache|upset|pain))\b", True),
    ("skin", "Δέρμα / ακμή", r"\b(skin|acne|pimple\w*|breakout\w*|complexion)\b", False),
    ("hair", "Μαλλιά", r"\b(hair)\b", False),
    ("nails", "Νύχια", r"\b(nails?)\b", False),
    ("immune", "Κρυολογήματα / ανοσοποιητικό", r"\b(colds?|flu|immun\w+|infection\w*|getting sick)\b", False),
    ("endurance", "Αντοχή / αναπνοή", r"\b(endurance|stamina|cardio|breath\w*|vo2\s?max|running)\b", False),
    ("strength", "Δύναμη / μύες", r"\b(strength|muscle\w*|gains|lifts?|hypertroph\w+)\b", False),
    ("recovery", "Αποκατάσταση / πιάσιμο", r"\b(recover\w*|soreness|doms)\b", False),
    ("heart", "Καρδιά / πίεση", r"\b(heart rate|palpitation\w*|blood pressure|hypertension|cardiovascular)\b", False),
    ("weight", "Βάρος / όρεξη", r"\b(weight|appetite|craving\w*|calorie\w*)\b", False),
    ("libido", "Λίμπιντο", r"\b(libido|sex drive|testosterone)\b", False),
    ("dreams", "Ζωηρά όνειρα", r"\b(vivid dreams?|dreams?|nightmares?)\b", True),
    ("joints", "Αρθρώσεις", r"\b(joints?|knees?|arthritis|osteoarthritis)\b", False),
    ("pain", "Πόνος", r"\b(pain\w*)\b", False),
    ("sugar", "Σάκχαρο", r"\b(blood sugar|glucose|insulin|glycemic|diabet\w+)\b", False),
    ("lipids", "Χοληστερίνη / τριγλυκερίδια", r"\b(cholesterol|triglycerid\w+|ldl|lipid\w*)\b", False),
    ("withdrawal", "Στερητικά / ευερεθιστότητα", r"\b(withdrawal\w*|irritab\w+)\b", True),
    ("senses", "Γεύση / όσφρηση", r"\b(taste|smell)\b", False),
    ("mortality", "Μακροζωία / θνησιμότητα", r"\b(mortality|longevity|lifespan|death)\b", False),
    ("bone", "Οστά", r"\b(bones?|fractures?|osteopor\w+|bone mineral density)\b", False),
]
_COMPILED = [(k, lbl, re.compile(rx, re.I), side) for k, lbl, rx, side in OUTCOMES]
_POS = re.compile(r"\b(help\w*|improv\w*|better|great|amazing|less|fewer|reduc\w*|gone|works?|worked|noticeabl\w*|game.?changer|life.?changing|fixed|cured)\b", re.I)
_NEG = re.compile(r"\b(worse|side.?effects?|stopped taking|nothing|no difference|didn'?t (help|work|notice)|bad|terrible|made me)\b", re.I)


def outcomes_in(text):
    """Return {key: polarity} for every outcome mentioned. polarity is +1, -1 or 0,
    judged from words within ~80 characters of the mention."""
    found = {}
    for key, _lbl, rx, _side in _COMPILED:
        m = rx.search(text)
        if not m:
            continue
        window = text[max(0, m.start() - 80): m.end() + 80]
        p, n = len(_POS.findall(window)), len(_NEG.findall(window))
        found[key] = 1 if p > n else -1 if n > p else 0
    return found


def tally(texts):
    """Count, over a list of texts (one per post), how many mention each outcome.
    Returns [[label, count, positive, negative, is_side_effect], ...] sorted by count."""
    agg = {}
    for t in texts:
        for key, pol in outcomes_in(t).items():
            a = agg.setdefault(key, [0, 0, 0])
            a[0] += 1
            if pol > 0:
                a[1] += 1
            elif pol < 0:
                a[2] += 1
    meta = {k: (lbl, side) for k, lbl, _rx, side in OUTCOMES}
    rows = [[meta[k][0], c, p, n, meta[k][1]] for k, (c, p, n) in agg.items()]
    rows.sort(key=lambda r: -r[1])
    return rows
