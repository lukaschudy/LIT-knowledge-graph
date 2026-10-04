from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from atlas.benchmark.contracts import digest, source_index
from atlas.benchmark.prepare import file_sha
from atlas.benchmark.snapshots import build, parse_article
from tests_benchmark.fixtures import example


HTML = '''<html><body><p>Outside the article</p><article><h1>Test paper</h1>
<section><h2>Methods</h2><p>Hold at <em>−60</em> mV.<script>ignore_me()</script></p></section>
<section class="tw" id="T1"><h3>Table 1</h3><div class="caption"><p>Measurements</p></div>
<table><tr><th rowspan="2">Variant</th><th colspan="2">Endpoint</th></tr>
<tr><th>Value</th><th>n</th></tr><tr><td>A1V</td><td>3 ± 1</td><td>5</td></tr>
<tr><td>A2V</td><td><img src="/figure.png" alt="untranscribed"/></td><td></td></tr></table>
<div class="tw-foot"><p>Values are mean ± SEM.</p></div></section></article></body></html>'''


class SnapshotTests(unittest.TestCase):
    def test_geometry_preserves_spans_and_empty_image_cells(self):
        units, ledger = parse_article(HTML, "PMC1", "https://example.org/article/")
        table = ledger["tables"][0]
        self.assertEqual((table["row_count"], table["column_count"]), (4, 3))
        self.assertEqual([(c["row"], c["column"]) for c in table["cells"][:4]], [(1, 1), (1, 2), (2, 2), (2, 3)])
        image_cell = next(c for c in table["cells"] if c["row"] == 4 and c["column"] == 2)
        self.assertIsNone(image_cell["unit_id"])
        self.assertEqual(image_cell["images"][0]["url"], "https://example.org/figure.png")
        self.assertEqual(ledger["counts"]["empty_cells"], 2)
        self.assertEqual(ledger["counts"]["image_bearing_cells"], 1)
        self.assertNotIn("untranscribed", " ".join(u["text"] for u in units))

    def test_article_boundary_scripts_and_unique_caption_footnote_units(self):
        units, ledger = parse_article(HTML, "PMC1", "https://example.org/")
        text = " ".join(u["text"] for u in units)
        self.assertNotIn("Outside", text)
        self.assertNotIn("ignore_me", text)
        self.assertEqual(sum(u["text"] == "Measurements" for u in units), 1)
        self.assertEqual(sum(u["kind"] == "footnote" for u in units), 1)
        self.assertTrue(any(u["kind"] == "methods" and "−60" in u["text"] for u in units))
        self.assertEqual(ledger["article_tree_repairs"], [])
        self.assertEqual(parse_article(HTML, "PMC1", "https://example.org/"), (units, ledger))

    def test_unsupported_nested_and_invalid_table_spans_fail(self):
        for value in [HTML.replace('rowspan="2"', 'rowspan="0"'),
                      '<article><table><tr><td><table><tr><td>x</td></tr></table></td></tr></table></article>']:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_article(value, "PMC1", "https://example.org/")

    def test_missing_article_is_not_silently_treated_as_full_text(self):
        with self.assertRaisesRegex(ValueError, "exactly one article"):
            parse_article("<html>access denied</html>", "PMC1", "https://example.org/")

    def test_unsafe_image_url_not_exposed(self):
        _, ledger = parse_article(HTML.replace('/figure.png', 'javascript:alert(1)'), "PMC1", "https://example.org/")
        self.assertIsNone(ledger["images"][0]["url"])

    def test_package_verifies_originals_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "data/benchmarks/grin-v1"
            target.mkdir(parents=True)
            raw = root / "data/raw/harvest/grin_primary_pages/PMC1.html"
            raw.parent.mkdir(parents=True)
            raw.write_text(HTML)
            manifests = root / "data/harvest-manifests"
            manifests.mkdir()
            m, _, _, _ = example()
            m.update(synthetic=False, state="draft")
            doc = deepcopy(m["documents"][0])
            doc.update(document_id="PMC1", study_id="pending-PMC1", source_sha256=None, grouping_reviewed=False)
            m["documents"] = [doc]
            (target / "development-manifest.json").write_text(json.dumps(m))
            (target / "candidate-inventory.json").write_text(json.dumps({"documents": [{"document_id": "PMC1", "title": "Test", "url": "https://example.org/"}]}))
            (manifests / "grin_primary_pages.json").write_text(json.dumps({"artifacts": {"PMC1.html": {
                "path": str(raw.relative_to(root)), "sha256": file_sha(raw), "license": "synthetic"}}}))
            output = root / "out"
            receipt = build(root, output)
            source = json.loads((output / "sources.json").read_text())
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertTrue(source_index(manifest, source))
            self.assertEqual(receipt["sources_sha256"], digest(source))
            self.assertEqual((output / "originals/PMC1.html").read_text(), HTML)
            self.assertEqual(receipt["annotation_status"], "blank_unassigned_not_independently_reviewed")
            with self.assertRaisesRegex(ValueError, "immutable"):
                build(root, output)
            raw.write_text(HTML + "modified")
            with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
                build(root, root / "out2")
            self.assertFalse((root / "out2").exists())


if __name__ == "__main__":
    unittest.main()
