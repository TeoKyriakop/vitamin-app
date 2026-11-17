"""Clients for the external databases. Standard library only.

PubMed (NCBI E-utilities)  - studies: title, journal, year, publication type
Europe PMC                 - citation counts for those studies (and a fallback search)
Reddit                     - forum posts and top comments, for user experiences
NIH DSLD                   - real supplement products on the market
"""
import gzip, html, json, os, re, time, base64, threading, urllib.parse, urllib.request, urllib.error, logging

log = logging.getLogger("vitapp.sources")
UA = os.environ.get("VITAPP_USER_AGENT", "VitaminCompass/1.0 (research aggregator)")
_last = {}
_lock = threading.Lock()
MIN_GAP = {"eutils.ncbi.nlm.nih.gov": 0.4 if not os.environ.get("NCBI_API_KEY") else 0.12,
           "www.ebi.ac.uk": 0.2, "www.reddit.com": 2.5, "oauth.reddit.com": 1.1, "api.ods.od.nih.gov": 0.5,
           "www.googleapis.com": 0.2, "hn.algolia.com": 0.3, "api.stackexchange.com": 0.6}


class SourceError(Exception):
    pass


class QuotaError(SourceError):
    """The daily allowance of an API is used up: stop calling it for this run."""


def _err_body(e):
    try:
        raw = e.read()
        return (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8", "replace")
    except Exception:
        return ""


def clean_text(t):
    """HTML to plain text."""
    t = re.sub(r"<[^>]+>", " ", t or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def _get(url, headers=None, data=None, tries=3, timeout=25):
    host = urllib.parse.urlparse(url).hostname
    for attempt in range(tries):
        with _lock:  # polite per-host pacing
            wait = _last.get(host, 0) + MIN_GAP.get(host, 0.3) - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[host] = time.time()
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json",
                                                               "Accept-Encoding": "gzip", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 403 and "quota" in _err_body(e).lower():
                raise QuotaError(f"{host}: quota exceeded") from e
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** (attempt + 1) * 2)
                continue
            raise SourceError(f"{host}: HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise SourceError(f"{host}: {e}") from e


# ---------------------------------------------------------------- PubMed
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
STUDY_FILTER = ('(meta-analysis[pt] OR systematic review[pt] OR randomized controlled trial[pt] OR clinical trial[pt]) '
                'NOT (animals[mh] NOT humans[mh])')


def _eparams(**kw):
    kw.update(tool="vitamin-compass", retmode="json")
    if os.environ.get("NCBI_API_KEY"):
        kw["api_key"] = os.environ["NCBI_API_KEY"]
    if os.environ.get("NCBI_EMAIL"):
        kw["email"] = os.environ["NCBI_EMAIL"]
    return urllib.parse.urlencode(kw)


OTHER_FILTER = "NOT (animals[mh] NOT humans[mh]) NOT (comment[pt] OR editorial[pt] OR letter[pt])"


def pubmed_search(term, retmax=20, strong=True):
    """Return a list of study dicts for a PubMed query: the strongest study types (strong=True)
    or any other human study (observational, small studies, reviews, case reports)."""
    q = f"({term}) AND {STUDY_FILTER}" if strong else f"({term}) {OTHER_FILTER} NOT ({STUDY_FILTER.split(' NOT ')[0]})"
    ids = _get(EUTILS + "esearch.fcgi?" + _eparams(db="pubmed", term=q, retmax=retmax, sort="relevance"))
    ids = ids.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    summ = _get(EUTILS + "esummary.fcgi?" + _eparams(db="pubmed", id=",".join(ids)))
    return parse_esummary(summ)


def parse_esummary(summ):
    res = summ.get("result", {})
    out = []
    for uid in res.get("uids", []):
        d = res.get(uid, {})
        pts = [p.lower() for p in d.get("pubtype", [])]
        if "meta-analysis" in pts:
            kind = "Μετα-ανάλυση"
        elif "systematic review" in pts:
            kind = "Συστηματική ανασκόπηση"
        elif "randomized controlled trial" in pts:
            kind = "RCT"
        elif "clinical trial" in pts:
            kind = "Κλινική μελέτη"
        elif "observational study" in pts:
            kind = "Παρατηρητική μελέτη"
        elif "review" in pts:
            kind = "Ανασκόπηση"
        elif "case reports" in pts:
            kind = "Αναφορά περιστατικού"
        else:
            kind = "Μελέτη"
        authors = d.get("authors") or []
        out.append({"pmid": uid, "title": (d.get("title") or "").rstrip("."), "year": (d.get("pubdate") or "")[:4],
                    "journal": d.get("source") or d.get("fulljournalname") or "", "type": kind,
                    "author": (authors[0].get("name") if authors else "") or ""})
    return out


# ---------------------------------------------------------------- Europe PMC
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?"


def europepmc_citations(pmids):
    """{pmid: citedByCount} for up to ~50 PMIDs in one request."""
    if not pmids:
        return {}
    q = "(" + " OR ".join(f"EXT_ID:{p}" for p in pmids) + ") AND SRC:MED"
    r = _get(EPMC + urllib.parse.urlencode({"query": q, "format": "json", "resultType": "lite", "pageSize": 100}))
    return {x.get("pmid"): int(x.get("citedByCount") or 0) for x in r.get("resultList", {}).get("result", []) if x.get("pmid")}


def europepmc_search(term, n=20):
    """Fallback when PubMed is unreachable."""
    q = f'({term}) AND (PUB_TYPE:"meta-analysis" OR PUB_TYPE:"systematic-review" OR PUB_TYPE:"randomized controlled trial")'
    r = _get(EPMC + urllib.parse.urlencode({"query": q, "format": "json", "resultType": "core", "pageSize": n}))
    out = []
    for x in r.get("resultList", {}).get("result", []):
        pts = " ".join((x.get("pubTypeList") or {}).get("pubType", [])).lower()
        kind = "Μετα-ανάλυση" if "meta" in pts else "Συστηματική ανασκόπηση" if "systematic" in pts else "RCT" if "random" in pts else "Μελέτη"
        out.append({"pmid": x.get("pmid") or "", "title": (x.get("title") or "").rstrip("."), "year": str(x.get("pubYear") or ""),
                    "journal": (x.get("journalInfo") or {}).get("journal", {}).get("medlineAbbreviation", "") or x.get("journalTitle", ""),
                    "type": kind, "author": (x.get("authorString") or "").split(",")[0], "cites": int(x.get("citedByCount") or 0)})
    return out


# ---------------------------------------------------------------- Reddit
_reddit_token = {"v": None, "exp": 0}


def _reddit_base():
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and sec):
        return "https://www.reddit.com", {}
    if time.time() > _reddit_token["exp"] - 60:
        auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        r = _get("https://www.reddit.com/api/v1/access_token", headers={"Authorization": "Basic " + auth},
                 data=b"grant_type=client_credentials")
        _reddit_token.update(v=r["access_token"], exp=time.time() + int(r.get("expires_in", 3600)))
    return "https://oauth.reddit.com", {"Authorization": "Bearer " + _reddit_token["v"]}


def reddit_texts(query, subs, posts=60, comment_posts=10):
    """Collect one text blob per post (title + body + top comments)."""
    base, hdr = _reddit_base()
    sr = "+".join(subs)
    qs = urllib.parse.urlencode({"q": query, "restrict_sr": 1, "sort": "relevance", "t": "all", "limit": min(posts, 100), "raw_json": 1})
    ext = "" if "oauth" in base else ".json"
    listing = _get(f"{base}/r/{sr}/search{ext}?{qs}", headers=hdr)
    children = [c.get("data", {}) for c in listing.get("data", {}).get("children", [])]
    texts = []
    for i, p in enumerate(children):
        blob = (p.get("title") or "") + "\n" + (p.get("selftext") or "")
        if i < comment_posts and p.get("num_comments", 0) > 0 and p.get("id"):
            try:
                path = f"/comments/{p['id']}{ext}"
                th = _get(f"{base}{path}?" + urllib.parse.urlencode({"limit": 40, "depth": 1, "sort": "top", "raw_json": 1}), headers=hdr)
                blob += "\n" + "\n".join(c.get("data", {}).get("body", "") for c in th[1]["data"]["children"] if c.get("kind") == "t1")
            except (SourceError, KeyError, IndexError, TypeError) as e:
                log.debug("comments %s: %s", p.get("id"), e)
        texts.append(blob)
    return texts


# ---------------------------------------------------------------- NIH DSLD
def dsld_products(term, n=6):
    """A few real products from the NIH Dietary Supplement Label Database."""
    r = _get("https://api.ods.od.nih.gov/dsld/v9/search-filter?" + urllib.parse.urlencode({"q": term, "size": n}))
    hits = r.get("hits") if isinstance(r, dict) else r
    if isinstance(hits, dict):
        hits = hits.get("hits", [])
    out = []
    for h in hits or []:
        s = h.get("_source", h) if isinstance(h, dict) else {}
        name = s.get("fullName") or s.get("productName") or s.get("name")
        if name:
            out.append([name, s.get("brandName") or "", str(h.get("_id") or s.get("id") or "")])
    return out[:n]


# ---------------------------------------------------------------- YouTube (comments)
YT = "https://www.googleapis.com/youtube/v3/"


def youtube_texts(query, videos=6, per_video=100):
    """Top comments under the most relevant videos. Needs YOUTUBE_API_KEY (free).
    Cost: 100 quota units for the search + 1 per video; the free daily quota is 10,000."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise SourceError("youtube: no YOUTUBE_API_KEY")
    r = _get(YT + "search?" + urllib.parse.urlencode({"part": "snippet", "q": query, "type": "video", "maxResults": videos,
                                                       "order": "relevance", "safeSearch": "strict", "key": key}))
    texts = []
    for it in r.get("items", []):
        vid = (it.get("id") or {}).get("videoId")
        if not vid:
            continue
        try:
            c = _get(YT + "commentThreads?" + urllib.parse.urlencode({"part": "snippet", "videoId": vid, "maxResults": per_video,
                                                                       "order": "relevance", "textFormat": "plainText", "key": key}), tries=1)
        except QuotaError:
            raise
        except SourceError:  # comments disabled on this video
            continue
        for t in c.get("items", []):
            texts.append(clean_text(t["snippet"]["topLevelComment"]["snippet"].get("textDisplay", "")))
    return [t for t in texts if len(t) >= 25]


# ---------------------------------------------------------------- Hacker News (Algolia)
def hackernews_texts(query, n=100):
    r = _get("https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({"query": query, "tags": "comment", "hitsPerPage": n}))
    texts = [clean_text(h.get("comment_text")) for h in r.get("hits", [])]
    return [t for t in texts if len(t) >= 25]


# ---------------------------------------------------------------- Stack Exchange
SE_SITES = {"i": ["fitness", "medicalsciences"], "s": ["medicalsciences", "fitness"], "h": ["fitness", "medicalsciences"],
            "f": ["cooking", "fitness"], "g": ["fitness", "medicalsciences"]}


def stackexchange_texts(query, kind="i", n=30):
    texts = []
    for site in SE_SITES.get(kind, ["fitness"]):
        params = {"order": "desc", "sort": "relevance", "q": query, "site": site, "filter": "withbody", "pagesize": n}
        if os.environ.get("STACKEXCHANGE_KEY"):
            params["key"] = os.environ["STACKEXCHANGE_KEY"]
        r = _get("https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode(params))
        texts += [clean_text((q.get("title") or "") + " " + (q.get("body") or "")) for q in r.get("items", [])]
        if r.get("quota_remaining", 1) <= 1:
            raise QuotaError("stackexchange: quota exceeded")
    return [t for t in texts if len(t) >= 25]


# ---------------------------------------------------------------- Lemmy
def lemmy_texts(query, n=50):
    inst = os.environ.get("LEMMY_INSTANCE", "lemmy.world")
    texts = []
    for typ, key in (("Comments", "comments"), ("Posts", "posts")):
        r = _get(f"https://{inst}/api/v3/search?" + urllib.parse.urlencode({"q": query, "type_": typ, "sort": "TopAll", "limit": n}))
        for x in r.get(key, []):
            if typ == "Comments":
                texts.append(clean_text((x.get("comment") or {}).get("content")))
            else:
                p = x.get("post") or {}
                texts.append(clean_text((p.get("name") or "") + " " + (p.get("body") or "")))
    return [t for t in texts if len(t) >= 25]
