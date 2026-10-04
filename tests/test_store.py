import copy
from contextlib import closing
import json
from pathlib import Path
import unittest
import sqlite3
import tempfile

from atlas.export import to_cytoscape, to_jsonld
from atlas.model import ValidationError, validate_bundle
from atlas.store import GraphStore


FIXTURE = Path(__file__).parents[1] / "data" / "fixtures" / "atlas-demo.json"


def fixture_bundle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class GraphStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = GraphStore()

    def tearDown(self):
        self.store.close()

    def test_fixture_validates_and_round_trips(self):
        bundle = fixture_bundle()
        self.assertEqual(validate_bundle(bundle), [])
        stats = self.store.load_bundle(bundle)
        self.assertEqual(stats, {"nodes": 23, "sources": 4, "claims": 30, "evidence": 30, "coverage": 7})
        self.assertEqual(self.store.bundle(), bundle)

    def test_opening_unrelated_sqlite_does_not_add_tables_or_change_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'existing.sqlite'
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('CREATE TABLE nodes (nid INTEGER PRIMARY KEY, id TEXT, label TEXT)')
                connection.execute("INSERT INTO nodes VALUES (1, 'original', 'Keep this record')")
            original=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'not a curated Atlas database'):
                GraphStore(str(path))
            self.assertEqual(path.read_bytes(),original)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute('SELECT label FROM nodes').fetchone()[0],'Keep this record')
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0],1)

    def test_matching_column_names_without_identity_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lookalike.sqlite'
            with closing(sqlite3.connect(path)) as connection, connection:
                for name in ('metadata', 'nodes', 'sources', 'claims', 'evidence', 'coverage'):
                    columns = [row[1] for row in self.store._conn.execute(f'PRAGMA table_info({name})')]
                    connection.execute(f"CREATE TABLE {name} ({', '.join(column + ' TEXT' for column in columns)})")
                connection.execute("INSERT INTO nodes(id,label) VALUES ('private-record','Keep this data')")
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'not a curated Atlas database'):
                GraphStore(str(path))
            self.assertEqual(path.read_bytes(), original)

    def test_existing_curated_database_reopens_without_losing_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'atlas.sqlite'
            bundle=fixture_bundle()
            with GraphStore(str(path)) as store:store.load_bundle(bundle)
            with GraphStore(str(path)) as store:self.assertEqual(store.bundle(),bundle)

    def test_rejects_missing_references_and_bad_endpoint_types(self):
        missing = fixture_bundle()
        missing["claims"][0]["object"] = "absent-node"
        self.assertTrue(any("existing node ID" in e for e in validate_bundle(missing)))

        wrong_type = fixture_bundle()
        wrong_type["claims"][0]["object"] = "demo:gene-a"
        self.assertTrue(any("does not accept Gene as object" in e for e in validate_bundle(wrong_type)))

    def test_malformed_json_shapes_return_validation_errors(self):
        cases = []
        for field, bad in (("type", []),):
            bundle = fixture_bundle()
            bundle["nodes"][0][field] = bad
            cases.append(bundle)
        for field, bad in (("url", None), ("url", []), ("url", 17)):
            bundle = fixture_bundle()
            bundle["sources"][0][field] = bad
            cases.append(bundle)
        for section, field, bad in (("claims", "effect", []), ("evidence", "stance", [])):
            bundle = fixture_bundle()
            if section == "claims":
                bundle[section][0]["context"][field] = bad
            else:
                bundle[section][0][field] = bad
            cases.append(bundle)
        for bundle in cases:
            self.assertTrue(validate_bundle(bundle))

    def test_missing_confidence_and_nonfinite_nested_values_are_rejected(self):
        bundle = fixture_bundle()
        del bundle["claims"][0]["extraction_confidence"]
        self.assertTrue(any("extraction_confidence" in e for e in validate_bundle(bundle)))

        bundle = fixture_bundle()
        bundle["nodes"][0]["properties"]["bad"] = float("nan")
        self.assertTrue(any("NaN or infinity" in e for e in validate_bundle(bundle)))

        bundle = fixture_bundle()
        bundle["claims"][0]["context"]["nested"] = {"value": float("inf")}
        self.assertTrue(any("NaN or infinity" in e for e in validate_bundle(bundle)))

    def test_invalid_load_is_atomic(self):
        original = fixture_bundle()
        self.store.load_bundle(original)
        invalid = copy.deepcopy(original)
        invalid["evidence"][0]["claim_id"] = "unknown"
        with self.assertRaises(ValidationError):
            self.store.load_bundle(invalid)
        self.assertEqual(self.store.bundle(), original)

    def test_alias_and_exact_search_order(self):
        bundle = fixture_bundle()
        self.store.load_bundle(bundle)
        result = self.store.search("Aurora")
        self.assertGreaterEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "demo:disease-a")
        self.assertEqual(self.store.search("AURORA SYNDROME")[0]["id"], "demo:disease-a")
        self.assertIsNone(self.store.get_node("no-such-node"))

    def test_exports_keep_negation_and_provenance(self):
        bundle = fixture_bundle()
        negated = next(c for c in bundle["claims"] if c["predicate"] == "HAS_PHENOTYPE")
        negated["context"]["negated"] = True
        evidence = next(e for e in bundle["evidence"] if e["claim_id"] == negated["id"])
        jsonld = to_jsonld(bundle)
        claim_record = next(x for x in jsonld["@graph"] if x["@id"] == negated["id"])
        self.assertTrue(claim_record["context"]["negated"])
        self.assertEqual(claim_record["@type"], "atlas:Claim")
        evidence_record = next(x for x in jsonld["@graph"] if x["@id"] == evidence["id"])
        self.assertEqual(evidence_record["source"]["@id"], evidence["source_id"])
        self.assertEqual(jsonld["@context"]["context"]["@type"], "@json")
        cy = to_cytoscape(bundle)
        claim_element = next(x for x in cy["elements"] if x["data"].get("record_id") == negated["id"])
        self.assertTrue(claim_element["data"]["context"]["negated"])
        self.assertTrue(any(x["data"].get("record_id") == evidence["id"] for x in cy["elements"]))
        self.assertFalse(any(x["data"].get("source") or x["data"].get("target") for x in cy["elements"] if "record_id" in x["data"]))


if __name__ == "__main__":
    unittest.main()
