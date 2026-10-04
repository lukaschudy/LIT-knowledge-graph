"""Contract checks against the installed optional SDK, without network or secrets."""
import importlib.util
import unittest

from atlas.search.topk import make_query, make_read_query, schema, wire_documents


@unittest.skipUnless(importlib.util.find_spec("topk_sdk"), "Install the search extra for SDK contract tests")
class SDKTests(unittest.TestCase):
    def test_bulk_read_is_one_filtered_query(self):
        q = make_read_query([{"_id": "a", "content": "text"}, {"_id": "b", "pmcid": "PMC123"}])
        self.assertIn("pmcid", repr(q))
        self.assertIn("content", repr(q))
        self.assertIn("Limit { k: 2 }", repr(q))

    def test_both_channels_with_logical_and_text_filters(self):
        for mode in ("keyword", "semantic"):
            q = make_query("GRIN2B S541R current", "snapshot", mode, 10,
                           gene="GRIN2B", protein="S541R", kind="curated_evidence")
            self.assertIn("snapshot_id", repr(q))
            self.assertIn("S541R", repr(q))
        self.assertIn("content", schema())

    def test_empty_lists_have_explicit_wire_type(self):
        row = wire_documents([{"_id": "a", "genes": [], "proteins": ["S541R"]}])[0]
        self.assertEqual(row["_id"], "a")
        self.assertNotIsInstance(row["genes"], list)
