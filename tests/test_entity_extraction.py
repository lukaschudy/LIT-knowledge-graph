"""Safety and grounding tests for entity/relation extraction proposals."""
from copy import deepcopy
from hashlib import sha256
import unittest

from atlas.ai import ModelError
from atlas.entity_extraction import extract_entities_and_relationships, _schema


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.prompt = None
        self.schema = None

    def generate_json(self, prompt, schema, schema_name):
        self.prompt, self.schema, self.schema_name = prompt, schema, schema_name
        return {"data": deepcopy(self.data), "metadata": {"provider": "fake", "model": "fake-model", "mode": "mock"}}


def doc(text="EPG5 is associated with BPAN in human cells.", source_id="paper-1"):
    return {"source_id": source_id, "title": "A source", "url": "https://example.org/paper",
            "license": "CC BY 4.0", "text": text, "version": sha256(text.encode()).hexdigest()}


def proposal(text="EPG5 is associated with BPAN in human cells.", existing_gene=None):
    gene = {"type": "Gene", "mention": "EPG5", "excerpt": "EPG5 is associated with BPAN", "existing_id": existing_gene,
            "confidence": 0.9}
    disease = {"type": "Disease", "mention": "BPAN", "excerpt": "EPG5 is associated with BPAN", "existing_id": None,
               "confidence": 0.8}
    return {"entities": [gene, disease], "relations": [{
        "subject_index": 0, "predicate": "ASSOCIATED_WITH_DISEASE", "object_index": 1,
        "assertion_type": "reported", "negated": False, "species": "human",
        "context": "source reports association", "confidence": 0.71, "excerpt": "EPG5 is associated with BPAN",
    }]}


class EntityExtractionTests(unittest.TestCase):
    def test_generates_source_scoped_nodes_grounded_claim_evidence_and_metadata(self):
        text = "EPG5 is associated with BPAN in human cells."
        client = FakeClient(proposal(text))
        result = extract_entities_and_relationships(doc(text), [], client)
        self.assertEqual(len(result["nodes"]), 2)
        self.assertTrue(all(n["id"].startswith("mention:") for n in result["nodes"]))
        self.assertTrue(all(n["properties"]["resolution_status"] == "unresolved_source_mention" for n in result["nodes"]))
        self.assertTrue(all(n["properties"]["provenance"]["excerpt"] == "EPG5 is associated with BPAN" for n in result["nodes"]))
        claim = result["claims"][0]
        evidence = result["evidence"][0]
        self.assertEqual(claim["predicate"], "ASSOCIATED_WITH_DISEASE")
        self.assertEqual(claim["context"], {"species": "human", "source_context": "source reports association"})
        self.assertEqual(claim["extraction_confidence"], 0.71)
        self.assertEqual(claim["review_status"], "unreviewed")
        self.assertEqual(claim["confidence_calibration"], "uncalibrated")
        self.assertEqual(evidence["source_version"], sha256(text.encode()).hexdigest())
        start, end = map(int, evidence["locator"].split("characters [", 1)[1].removesuffix(")").split(","))
        self.assertEqual(text[start:end], evidence["excerpt"])
        self.assertEqual(result["metadata"]["mode"], "mock")
        self.assertEqual(len(result["identity_candidates"]), 2)

    def test_only_known_type_compatible_server_ids_can_resolve_mentions(self):
        text = "EPG5 is associated with BPAN in human cells."
        known = [{"id": "gene:EPG5", "type": "Gene", "label": "EPG5", "aliases": []}]
        raw = proposal(text, existing_gene="gene:EPG5")
        client = FakeClient(raw)
        result = extract_entities_and_relationships(doc(text), known, client)
        self.assertEqual(result["nodes"][0]["label"], "BPAN")
        self.assertEqual(result["claims"][0]["subject"], "gene:EPG5")
        self.assertEqual(result["identity_candidates"][0]["node_id"], result["nodes"][0]["id"])
        self.assertIn("gene:EPG5", client.schema["properties"]["entities"]["items"]["properties"]["existing_id"]["enum"])

    def test_new_mention_ids_are_source_scoped_not_name_global(self):
        text = "EPG5 is associated with BPAN in human cells."
        first = extract_entities_and_relationships(doc(text, "paper-1"), [], FakeClient(proposal(text)))
        second = extract_entities_and_relationships(doc(text, "paper-2"), [], FakeClient(proposal(text)))
        self.assertNotEqual(first["nodes"][0]["id"], second["nodes"][0]["id"])

    def test_negation_is_preserved_as_supported_negative_assertion(self):
        text = "EPG5 is not associated with BPAN in human cells."
        raw = proposal(text)
        raw["entities"][0]["excerpt"] = "EPG5 is not associated with BPAN"
        raw["entities"][1]["excerpt"] = "EPG5 is not associated with BPAN"
        raw["relations"][0].update({"negated": True, "excerpt": "EPG5 is not associated with BPAN"})
        result = extract_entities_and_relationships(doc(text), [], FakeClient(raw))
        self.assertEqual(result["claims"][0]["context"]["negated"], True)
        self.assertEqual(result["evidence"][0]["stance"], "supports")

    def test_fabricated_or_ambiguous_quotes_reject_whole_response(self):
        raw = proposal()
        raw["relations"][0]["excerpt"] = "EPG5 strongly activates LC3"
        with self.assertRaises(ModelError) as caught:
            extract_entities_and_relationships(doc(), [], FakeClient(raw))
        self.assertEqual(caught.exception.code, "invalid_evidence")
        raw = proposal("EPG5 binds LC3. EPG5 binds LC3.")
        raw["entities"][0]["excerpt"] = "EPG5 binds LC3"
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc("EPG5 binds LC3. EPG5 binds LC3."), [], FakeClient(raw))
        text = "EPG5 AAAA BPAN"
        raw = {"entities": [{"type": "Gene", "mention": "EPG5", "excerpt": "EPG5", "existing_id": None, "confidence": 0.5},
                            {"type": "Disease", "mention": "BPAN", "excerpt": "BPAN", "existing_id": None, "confidence": 0.5}],
               "relations": [{"subject_index": 0, "predicate": "ASSOCIATED_WITH_DISEASE", "object_index": 1,
               "assertion_type": "reported", "negated": False, "species": None, "context": None,
               "confidence": 0.5, "excerpt": "AAA"}]}
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))

    def test_overlapping_entity_mentions_are_not_treated_as_unique(self):
        text = "AAA"
        raw = {"entities": [{"type": "Gene", "mention": "AA", "excerpt": "AAA", "existing_id": None,
                             "confidence": 0.5}], "relations": []}
        with self.assertRaises(ModelError) as caught:
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))
        self.assertEqual(caught.exception.code, "invalid_evidence")

    def test_unknown_existing_ids_invalid_predicates_types_and_indices_fail(self):
        text = "EPG5 is associated with BPAN in human cells."
        raw = proposal(text, existing_gene="gene:invented")
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))
        raw = proposal(text)
        raw["relations"][0].update({"subject_index": 1, "object_index": 0})
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))
        raw = proposal(text)
        raw["relations"][0]["subject_index"] = 20
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))

    def test_limits_and_snapshot_mismatch_fail_closed(self):
        text = "EPG5 is associated with BPAN in human cells."
        raw = {"entities": [{"type": "Gene", "mention": "EPG5", "excerpt": "EPG5", "existing_id": None,
                             "confidence": 0.5}] * 21, "relations": []}
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))
        bad_doc = doc(text)
        bad_doc["version"] = "wrong"
        with self.assertRaises(ValueError):
            extract_entities_and_relationships(bad_doc, [], FakeClient({"entities": [], "relations": []}))

    def test_schema_has_bounded_entities_relations_and_server_known_id_enum(self):
        schema = _schema([{"id": "gene:EPG5", "type": "Gene"}])
        self.assertEqual(schema["properties"]["entities"]["maxItems"], 20)
        self.assertEqual(schema["properties"]["relations"]["maxItems"], 30)
        self.assertIn("gene:EPG5", schema["properties"]["entities"]["items"]["properties"]["existing_id"]["enum"])
        self.assertNotIn("SAME_AS", schema["properties"]["relations"]["items"]["properties"]["predicate"]["enum"])

    def test_unknown_proposal_fields_and_uncalibrated_scores_outside_range_reject(self):
        text = "EPG5 is associated with BPAN in human cells."
        raw = proposal(text)
        raw["entities"][0]["global_id"] = "HGNC:123"
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))
        raw = proposal(text)
        raw["relations"][0]["confidence"] = 1.5
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))

    def test_assertion_type_is_part_of_claim_identity(self):
        raw = proposal()
        reported = extract_entities_and_relationships(doc(), [], FakeClient(raw))
        raw['relations'][0]['assertion_type'] = 'inferred'
        inferred = extract_entities_and_relationships(doc(), [], FakeClient(raw))
        self.assertNotEqual(reported['claims'][0]['id'], inferred['claims'][0]['id'])

    def test_malformed_model_enum_values_raise_model_errors(self):
        for collection, field in [('entities', 'type'), ('entities', 'existing_id'),
                                  ('relations', 'predicate'), ('relations', 'assertion_type')]:
            for value in [[], {}, ['Gene']]:
                raw = proposal()
                raw[collection][0][field] = value
                with self.subTest(collection=collection, field=field, value=value), self.assertRaises(ModelError):
                    extract_entities_and_relationships(doc(), [], FakeClient(raw))
        for value in [10**1000, float('nan'), float('inf'), True]:
            raw = proposal(); raw['entities'][0]['confidence'] = value
            with self.subTest(value=str(value)[:30]), self.assertRaises(ModelError):
                extract_entities_and_relationships(doc(), [], FakeClient(raw))

    def test_relationship_cannot_borrow_unrelated_authentic_quote(self):
        text = 'EPG5 appears in this source. BPAN is also mentioned. Other experiments failed.'
        raw = proposal()
        raw['entities'][0]['excerpt'] = 'EPG5 appears in this source.'
        raw['entities'][1]['excerpt'] = 'BPAN is also mentioned.'
        raw['relations'][0]['excerpt'] = 'Other experiments failed.'
        with self.assertRaisesRegex(ModelError, 'both selected entity mentions'):
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))

    def test_relationship_quote_must_cover_selected_occurrences(self):
        text = 'EPG5 was sequenced. EPG5 is associated with BPAN.'
        raw = proposal()
        raw['entities'][0]['excerpt'] = 'EPG5 was sequenced.'
        raw['entities'][1]['excerpt'] = 'EPG5 is associated with BPAN.'
        raw['relations'][0]['excerpt'] = 'EPG5 is associated with BPAN.'
        with self.assertRaisesRegex(ModelError, 'both selected entity mentions'):
            extract_entities_and_relationships(doc(text), [], FakeClient(raw))

    def test_invalid_inputs_fail_before_requesting_model_output(self):
        for changes in [{'kind': []}, {'kind': 'invented'}, {'url': 'https://user:secret@example.org'},
                        {'url': 'https://example.org/a\nb'}, {'version': 0}, {'text': 'Bad\ud800text'}]:
            client = FakeClient(proposal())
            with self.subTest(changes=repr(changes)), self.assertRaises(ValueError):
                extract_entities_and_relationships({**doc(), **changes}, [], client)
            self.assertIsNone(client.prompt)
        for node in [{'id': 'gene:x', 'type': []}, {'id': 'gene:x', 'type': 'Gene'},
                     {'id': 'gene:x', 'type': 'Gene', 'label': 'X', 'aliases': [123]}]:
            client = FakeClient(proposal())
            with self.assertRaises(ValueError):
                extract_entities_and_relationships(doc(), [node], client)
            self.assertIsNone(client.prompt)

    def test_invalid_metadata_and_unicode_context_reject_whole_result(self):
        client = FakeClient(proposal())
        client.generate_json = lambda *args: {'data': proposal(), 'metadata': ['not an object']}
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc(), [], client)
        raw = proposal(); raw['relations'][0]['context'] = 'bad\ud800context'
        with self.assertRaises(ModelError):
            extract_entities_and_relationships(doc(), [], FakeClient(raw))


if __name__ == "__main__":
    unittest.main()
