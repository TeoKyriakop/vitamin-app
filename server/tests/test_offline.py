"""Offline tests: parsers, repetition counting, and a full harvest with the network mocked."""
import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.mkdtemp()
os.environ["VITAPP_STATE"] = TMP + "/state"
os.environ["VITAPP_APP"] = TMP + "/app"
from vitapp import lexicon, sources, store, harvest  # noqa: E402

ESUMMARY = {"result": {"uids": ["111", "222"],
    "111": {"title": "Magnesium supplementation and sleep quality: a meta-analysis.", "pubdate": "2021 Mar", "source": "BMC Complement Med Ther",
            "pubtype": ["Journal Article", "Meta-Analysis"], "authors": [{"name": "Mah J"}]},
    "222": {"title": "Oral magnesium for leg cramps: randomized trial", "pubdate": "2017", "source": "JAMA Intern Med",
            "pubtype": ["Randomized Controlled Trial"], "authors": [{"name": "Roguin Maor N"}]}}}
POSTS = ["Magnesium glycinate helped my sleep a lot, way better now",
         "mag citrate gave me diarrhea, stopped taking it",
         "Sleep improved and fewer leg cramps after 2 weeks",
         "No difference in anxiety for me, nothing changed",
         "Calmer, less anxiety, and my sleep is deeper"]


class T(unittest.TestCase):
    def test_parse_esummary(self):
        s = sources.parse_esummary(ESUMMARY)
        self.assertEqual([x["type"] for x in s], ["Μετα-ανάλυση", "RCT"])
        self.assertEqual(s[0]["year"], "2021")
        self.assertEqual(s[0]["author"], "Mah J")

    def test_tally_counts_repetitions(self):
        rows = {r[0]: r for r in lexicon.tally(POSTS)}
        self.assertEqual(rows["Ύπνος"][1], 3)          # mentioned in 3 posts
        self.assertGreaterEqual(rows["Ύπνος"][2], 2)   # mostly positive
        self.assertEqual(rows["Διάρροια"][4], True)    # flagged as side effect
        self.assertEqual(rows["Άγχος / ηρεμία"][1], 2)

    def test_full_harvest_and_build(self):
        with mock.patch.object(sources, "pubmed_search", return_value=sources.parse_esummary(ESUMMARY)), \
             mock.patch.object(sources, "europepmc_citations", return_value={"111": 42}), \
             mock.patch.object(sources, "reddit_texts", return_value=POSTS * 2), \
             mock.patch.object(sources, "dsld_products", return_value=[["Magnesium Glycinate 200 mg", "Brand", "123"]]):
            harvest.run(only="i/mg")
        e = json.loads((Path(TMP) / "app/data/e/i/mg.json").read_text())
        self.assertEqual(e["auto"]["ps"][0][0], "111")
        self.assertEqual(e["auto"]["ps"][0][5], 42)
        self.assertEqual(e["auto"]["fn"], 10)
        self.assertEqual(e["auto"]["fc"][0][0], "Ύπνος")
        self.assertTrue(e["auto"]["dsld"])
        self.assertIn("foods", e)
        idx = json.loads((Path(TMP) / "app/data/index.json").read_text())
        self.assertGreater(len(idx["e"]), 90)

    def test_source_failure_keeps_previous_data(self):
        with mock.patch.object(sources, "pubmed_search", side_effect=sources.SourceError("down")), \
             mock.patch.object(sources, "europepmc_search", side_effect=sources.SourceError("down")), \
             mock.patch.object(sources, "reddit_texts", side_effect=sources.SourceError("down")), \
             mock.patch.object(sources, "dsld_products", side_effect=sources.SourceError("down")):
            store.write_json(store.auto_path("i", "zn"), {"ts": 0, "ps": [["9", "old", "2020", "J", "RCT", 1, "A"]], "fc": [["Ύπνος", 3, 1, 0, False]], "fn": 3})
            a = harvest.harvest_one("i", "zn", store.load_entities())
        self.assertEqual(a["ps"][0][0], "9")
        self.assertEqual(a["fn"], 3)
        self.assertTrue(a["err"])

    def test_issue_request(self):
        from vitapp import discover_issue, site
        k, q, en = discover_issue.parse("kind: h\nq: Νηστεία\nen: intermittent fasting\n\nσχόλιο")
        self.assertEqual((k, q, en), ("h", "Νηστεία", "intermittent fasting"))
        for bad in ["kind: x\nq: a\nen: b c", "kind: h\nq: a\nen: $(rm -rf /)", "kind: h\nen: abc"]:
            with self.assertRaises(ValueError):
                discover_issue.parse(bad)
        with mock.patch.object(sources, "pubmed_search", return_value=[]), \
             mock.patch.object(sources, "europepmc_citations", return_value={}), \
             mock.patch.object(sources, "reddit_texts", return_value=POSTS):
            id_, a = discover_issue.add(k, q, en)
        self.assertTrue((Path(TMP) / f"app/data/e/h/{id_}.json").exists())
        import shutil
        for f in ("index.html", "sw.js", "icon.svg", "manifest.webmanifest"):
            shutil.copy(Path(__file__).resolve().parents[2] / "app" / f, Path(TMP) / "app" / f)
        out = site.build_site(Path(TMP) / "site")
        html = (out / "index.html").read_text()
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertTrue((out / "data/index.json").exists())

    def test_queries(self):
        ents = store.load_entities()
        self.assertIn("meta", sources.STUDY_FILTER)
        self.assertIn('"Magnesium"[tiab]', store.pubmed_term("i", ents[("i", "mg")], ents))
        self.assertIn("insomnia", store.pubmed_term("s", ents[("s", "insomnia")], ents))
        self.assertIn("smoking cessation", store.pubmed_term("h", ents[("h", "quit-smoking")], ents))


if __name__ == "__main__":
    unittest.main(verbosity=2)
