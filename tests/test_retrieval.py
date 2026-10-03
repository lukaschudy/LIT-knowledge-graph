import unittest
import sys
import types
from unittest.mock import patch

from atlas.retrieval import SourceRetriever, TopKError, TopKRetriever


class SourceRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.docs = [
            {"source_id": "paper:one", "title": "Transport", "text": "Background.\n\nAurora disease affects cellular transport.\nMore detail."},
            {"source_id": "paper:two", "title": "Other", "text": "A different phenotype is described."},
        ]

    def test_search_returns_ranked_passages_and_source_offsets(self):
        result = SourceRetriever(self.docs).search("Aurora cellular transport")
        self.assertEqual(result[0]["source_id"], "paper:one")
        self.assertEqual(result[0]["text"], "Aurora disease affects cellular transport.")
        doc = self.docs[0]["text"]
        self.assertEqual(doc[result[0]["start"]:result[0]["end"]], result[0]["text"])
        self.assertEqual(result[0]["score"], 1.06066)

    def test_no_match_and_top_k(self):
        retriever = SourceRetriever(self.docs)
        self.assertEqual(retriever.search("zebra"), [])
        self.assertEqual(len(retriever.search("disease", top_k=1)), 1)

    def test_rejects_missing_source_or_bad_limit(self):
        with self.assertRaises(ValueError): SourceRetriever([{"text": "x"}])
        with self.assertRaises(ValueError): SourceRetriever(self.docs).search("x", top_k=0)

    def test_long_paragraph_results_are_bounded_around_the_match(self):
        long_text = "background " * 1500 + "rare finding here " + "filler " * 1500
        result = SourceRetriever([{"source_id": "paper:long", "text": long_text}], passage_chars=250).search("rare finding")
        self.assertLessEqual(len(result[0]["text"]), 250)
        self.assertIn("rare finding", result[0]["text"])
        self.assertEqual(long_text[result[0]["start"]:result[0]["end"]], result[0]["text"])


class _Field:
    def __init__(self, name): self.name = name
    def __eq__(self, other): return ("eq", self.name, other)


class _Query:
    def filter(self, *args, **kwargs): self.filter_condition = args[0]; return self
    def sort(self, *args, **kwargs): return self
    def limit(self, *args, **kwargs): return self


class _TopKClient:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.created = []
        self.upserted = None
        self.query_kwargs = None
        self.query_obj = None
    def collections(self): return self
    def list(self): return []
    def create(self, name, schema): self.created.append((name, schema))
    def collection(self, name): return self
    def upsert(self, rows): self.upserted = rows; return "lsn-1"
    def query(self, query, **kwargs): self.query_obj = query; self.query_kwargs = kwargs; return self.rows


def topk_sdk_modules():
    package = types.ModuleType("topk_sdk")
    package.__path__ = []
    schema = types.ModuleType("topk_sdk.schema")
    class Text:
        def required(self): return self
        def index(self, value): self.indexed = value; return self
    schema.text = Text
    schema.int = Text
    schema.semantic_index = lambda: object()
    query = types.ModuleType("topk_sdk.query")
    query.select = lambda *args, **kwargs: _Query()
    query.field = _Field
    query.fn = types.SimpleNamespace(semantic_similarity=lambda *args: object())
    return {"topk_sdk": package, "topk_sdk.schema": schema, "topk_sdk.query": query}


class TopKRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.documents = [{"source_id": "paper:one", "title": "Transport paper",
                           "text": "Aurora disease affects cellular transport."}]
        self.client = _TopKClient()
        self.retriever = TopKRetriever(self.documents, collection="atlas-test", client=self.client)

    def test_index_is_explicit_and_creates_managed_semantic_schema(self):
        self.assertIsNone(self.client.upserted)
        with patch.dict(sys.modules, topk_sdk_modules()):
            meta = self.retriever.index_documents()
        self.assertEqual(meta["mode"], "live")
        self.assertEqual(meta["submitted_chunk_count"], 1)
        self.assertTrue(meta["write_acknowledged"])
        self.assertIsNone(self.retriever.status()["indexed_documents"])
        self.assertEqual(self.client.created[0][0], "atlas-test")
        self.assertTrue(hasattr(self.client.created[0][1]["passage"], "indexed"))
        chunk = self.client.upserted[0]
        self.assertEqual(chunk["passage"], self.documents[0]["text"])
        self.assertEqual(chunk["source_version"], self.retriever._docs["paper:one"]["version"])

    def test_search_returns_verified_source_bound_result_and_mode(self):
        with patch.dict(sys.modules, topk_sdk_modules()):
            self.retriever.index_documents()
            chunk = self.client.upserted[0]
            self.client.rows = [chunk | {"score": 0.91}]
            hits = self.retriever.search("cellular transport")
        self.assertEqual(hits, [{"source_id": "paper:one", "title": "Transport paper",
            "text": self.documents[0]["text"], "score": 0.91, "start": 0,
            "end": len(self.documents[0]["text"]), "source_version": chunk["source_version"]}])
        self.assertEqual(self.retriever.last_metadata["mode"], "live")
        self.assertEqual(self.client.query_kwargs, {"lsn": "lsn-1", "consistency": "indexed"})
        self.assertEqual(self.client.query_obj.filter_condition, ("eq", "corpus_id", self.retriever._corpus_id))

    def test_fresh_retriever_queries_existing_snapshot_without_upserting(self):
        with patch.dict(sys.modules, topk_sdk_modules()):
            self.retriever.index_documents()
            chunk = self.client.upserted[0]
            self.client.rows = [chunk | {"score": 0.82}]
            fresh = TopKRetriever(self.documents, collection="atlas-test", client=self.client)
            self.assertIsNone(fresh._lsn)
            hits = fresh.search("Aurora")
        self.assertEqual(hits[0]["source_id"], "paper:one")
        self.assertTrue(fresh.status()["query_verified"])
        self.assertIsNone(fresh.status()["indexed_documents"])
        self.assertIsNone(fresh.status()["searched_documents"])
        self.assertEqual(fresh.status()["verified_hit_count"], 1)
        self.assertIsNone(self.client.query_kwargs.get("lsn"))

    def test_chunk_ids_are_isolated_across_corpus_snapshots(self):
        shared = self.documents[0]
        corpus_a = TopKRetriever([shared, {"source_id": "paper:a", "text": "A content."}], collection="atlas-test", client=self.client)
        corpus_b = TopKRetriever([shared, {"source_id": "paper:b", "text": "B content."}], collection="atlas-test", client=self.client)
        shared_a = next(chunk for chunk in corpus_a._chunks if chunk["source_id"] == "paper:one")
        shared_b = next(chunk for chunk in corpus_b._chunks if chunk["source_id"] == "paper:one")
        self.assertNotEqual(corpus_a._corpus_id, corpus_b._corpus_id)
        self.assertNotEqual(shared_a["_id"], shared_b["_id"])
        self.assertNotEqual(shared_a["corpus_id"], shared_b["corpus_id"])

    def test_foreign_or_stale_hit_rejected(self):
        with patch.dict(sys.modules, topk_sdk_modules()):
            self.retriever.index_documents()
            self.client.rows = [{"_id": "old-index-id", "score": 1}]
            with self.assertRaises(TopKError): self.retriever.search("Aurora")
            chunk = self.client.upserted[0]
            self.client.rows = [chunk | {"passage": "altered quote", "score": 1}]
            with self.assertRaises(TopKError): self.retriever.search("Aurora")

    def test_needs_explicit_index_and_valid_snapshot_version(self):
        with self.assertRaises(TopKError): self.retriever.search("Aurora")
        with self.assertRaises(ValueError):
            TopKRetriever([self.documents[0] | {"version": "sha256:wrong"}], collection="atlas-test", client=self.client)

    def test_status_reports_configuration_without_claiming_index_exists(self):
        status = TopKRetriever(self.documents).status()
        self.assertFalse(status["available"])
        self.assertIsNone(status["submitted_chunk_count"])
        self.assertEqual(status["loaded_document_count"], 1)
        self.assertIsNone(status["indexed_documents"])
