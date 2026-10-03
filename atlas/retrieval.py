"""Deterministic lexical retrieval over explicitly supplied source documents."""
from __future__ import annotations

import math
import hashlib
import os
import re
from collections import Counter
from typing import Any, Iterable

_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)


class SourceRetriever:
    """Rank supplied documents locally and return source-bound text passages.

    Documents must contain ``source_id`` and ``text``; ``title`` is optional.
    No fetching, embedding, or external service is used.
    """

    def __init__(self, documents: Iterable[dict[str, Any]], passage_chars: int = 1200):
        if type(passage_chars) is not int or passage_chars < 100:
            raise ValueError("passage_chars must be an integer of at least 100")
        self.passage_chars = passage_chars
        self.documents = []
        for doc in documents:
            if not isinstance(doc, dict) or not isinstance(doc.get("source_id"), str) or not doc["source_id"].strip():
                raise ValueError("Each document requires a nonempty source_id.")
            if not isinstance(doc.get("text"), str) or not doc["text"].strip():
                raise ValueError("Each document requires nonempty source text.")
            self.documents.append({"source_id": doc["source_id"], "title": str(doc.get("title") or doc["source_id"]),
                                   "text": doc["text"]})

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [token.casefold() for token in _TOKEN.findall(text)]

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be nonempty text")
        if type(top_k) is not int or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        query_terms = set(self._tokens(query))
        if not query_terms:
            return []
        ranked = []
        for order, doc in enumerate(self.documents):
            terms = self._tokens(doc["text"])
            counts = Counter(terms)
            matched = query_terms.intersection(counts)
            if not matched:
                continue
            score = sum(1 + math.log(counts[t]) for t in matched) / math.sqrt(max(1, len(terms)))
            # Return a bounded paragraph around the strongest query match.
            positions = [m for m in _TOKEN.finditer(doc["text"]) if m.group().casefold() in query_terms]
            first = positions[0].start()
            left = doc["text"].rfind("\n", 0, first)
            right = doc["text"].find("\n", first)
            start = left + 1 if left >= 0 else 0
            end = right if right >= 0 else len(doc["text"])
            if end <= start:
                start, end = max(0, first - self.passage_chars // 3), min(len(doc["text"]), first + self.passage_chars)
            elif end - start > self.passage_chars:
                # Center a match from a very long paragraph in a bounded passage.
                start = max(start, first - self.passage_chars // 3)
                end = min(end, start + self.passage_chars)
            ranked.append((score, order, {"source_id": doc["source_id"], "title": doc["title"],
                           "text": doc["text"][start:end], "score": round(score, 6), "start": start, "end": end}))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return [row[2] for row in ranked[:top_k]]


class TopKError(RuntimeError):
    """Safe failure from the optional managed TopK adapter."""


class TopKRetriever:
    """Optional managed semantic search with locally verified source passages.

    Input documents have ``source_id``, ``text``, and optional ``title`` and
    ``version``. Index writes happen only when ``index_documents`` is called.
    """

    def __init__(self, documents: Iterable[dict[str, Any]], api_key: str | None = None,
                 region: str | None = None, collection: str | None = None, client: Any = None,
                 *, chunk_size: int = 1200, overlap: int = 120, timeout: int = 30):
        if type(chunk_size) is not int or chunk_size < 200:
            raise ValueError("chunk_size must be an integer of at least 200")
        if type(overlap) is not int or overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be a nonnegative integer smaller than chunk_size")
        if type(timeout) is not int or timeout < 1:
            raise ValueError("timeout must be a positive number of seconds")
        self.api_key = api_key or os.environ.get("TOPK_API_KEY")
        self.region = region or os.environ.get("TOPK_REGION")
        self.collection_name = collection or os.environ.get("TOPK_COLLECTION")
        self._client = client
        self._is_injected = client is not None
        self._chunk_size, self._overlap = chunk_size, overlap
        self.timeout = timeout
        self._docs: dict[str, dict[str, str]] = {}
        self._manifest: dict[str, dict[str, Any]] = {}
        self._write_acknowledged = False
        self._verified = None
        self._lsn: str | None = None
        self._submitted_chunk_count = None
        self._last_verified_hit_count = None
        self.last_metadata: dict[str, Any] = {"provider": "topk", "mode": "not_configured"}
        for doc in documents:
            if not isinstance(doc, dict) or not isinstance(doc.get("source_id"), str) or not doc["source_id"].strip():
                raise ValueError("Each document requires a nonempty source_id.")
            source_id = doc["source_id"]
            text = doc.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Each document requires nonempty source text.")
            if source_id in self._docs:
                raise ValueError(f"Duplicate source_id {source_id!r}.")
            version = hashlib.sha256(text.encode("utf-8")).hexdigest()
            declared_version = doc.get("version")
            if declared_version is not None and str(declared_version).removeprefix("sha256:") != version:
                raise ValueError(f"Source {source_id!r} version does not match its text snapshot.")
            self._docs[source_id] = {"title": str(doc.get("title") or source_id), "text": text, "version": version}
        corpus_identity = "\n".join(
            f"{sid}\0{doc['version']}\0{doc['title']}" for sid, doc in sorted(self._docs.items())
        ) + f"\0chunk_size={self._chunk_size}\0overlap={self._overlap}"
        self._corpus_id = hashlib.sha256(corpus_identity.encode("utf-8")).hexdigest()
        self._chunks = self._build_chunks()

    def _build_chunks(self) -> list[dict[str, Any]]:
        chunks = []
        for source_id, doc in self._docs.items():
            source_text = doc["text"]
            start = 0
            while start < len(source_text):
                target = min(len(source_text), start + self._chunk_size)
                end = target
                if target < len(source_text):
                    # Prefer paragraph or word boundaries while keeping chunks bounded.
                    boundary = max(source_text.rfind("\n\n", start + self._chunk_size // 2, target),
                                   source_text.rfind("\n", start + self._chunk_size // 2, target),
                                   source_text.rfind(" ", start + self._chunk_size // 2, target))
                    if boundary > start:
                        end = boundary
                if end <= start:
                    end = target
                passage = source_text[start:end]
                identity = (f"{self._corpus_id}\0{source_id}\0{doc['version']}\0{doc['title']}\0"
                            f"{self._chunk_size}\0{self._overlap}\0{start}\0{end}")
                chunk_id = "chunk-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
                row = {"_id": chunk_id, "source_id": source_id, "source_version": doc["version"],
                       "title": doc["title"], "passage": passage, "start": start, "end": end,
                       "corpus_id": self._corpus_id}
                chunks.append(row)
                self._manifest[chunk_id] = row
                if end == len(source_text):
                    break
                next_start = max(start + 1, end - self._overlap)
                # Avoid starting in the middle of a UTF-8-independent Python character/token.
                start = next_start
        return chunks

    def status(self) -> dict[str, Any]:
        configured = bool(self.collection_name and (self._is_injected or (self.api_key and self.region)))
        return {"available": configured, "provider": "topk" if configured else None,
                "mode": "configured" if configured else None, "collection": self.collection_name,
                "configured": configured, "corpus_id": self._corpus_id,
                "index_verified": None, "query_verified": self._verified,
                "write_acknowledged": self._write_acknowledged,
                "loaded_document_count": len(self._docs),
                "submitted_chunk_count": self._submitted_chunk_count,
                "verified_hit_count": self._last_verified_hit_count,
                "indexed_documents": None, "searched_documents": None,
                "reason": None if configured else "Set TOPK_API_KEY, TOPK_REGION, and TOPK_COLLECTION."}

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key or not self.region or not self.collection_name:
            raise TopKError("TopK requires TOPK_API_KEY, TOPK_REGION, and TOPK_COLLECTION.")
        try:
            from topk_sdk import Client
        except ImportError as exc:
            raise TopKError("TopK search needs the optional SDK; install it with `pip install topk-sdk`.") from exc
        # The current SDK documents retry_config.timeout in milliseconds.
        self._client = Client(api_key=self.api_key, region=self.region,
                              retry_config={"timeout": self.timeout * 1000, "max_retries": 0})
        return self._client

    def index_documents(self) -> dict[str, Any]:
        """Create/reuse the declared semantic collection and upsert this corpus."""
        if not self.collection_name:
            raise TopKError("Set TOPK_COLLECTION before indexing the research corpus.")
        try:
            from topk_sdk.schema import int as int_field, text, semantic_index
        except ImportError as exc:
            if not self._is_injected:
                raise TopKError("TopK indexing needs the optional SDK; install it with `pip install topk-sdk`.") from exc
            # Test doubles may provide a collections API without installing the optional package.
            text = semantic_index = int_field = None
        client = self._get_client()
        try:
            collections = client.collections()
            existing = collections.list()
            exists = any(getattr(item, "name", None) == self.collection_name for item in existing)
            if not exists:
                if text is None:
                    raise TopKError("TopK SDK schema helpers are required to create the semantic index.")
                collections.create(self.collection_name, schema={
                    "passage": text().required().index(semantic_index()),
                    "source_id": text().required(), "source_version": text().required(),
                    "title": text().required(), "start": int_field().required(), "end": int_field().required(),
                    "corpus_id": text().required(),
                })
            else:
                existing_collection = next((item for item in existing if getattr(item, "name", None) == self.collection_name), None)
                existing_schema = getattr(existing_collection, "schema", None)
                if existing_schema is not None and not {"passage", "source_id", "source_version", "title", "start", "end", "corpus_id"}.issubset(existing_schema):
                    raise TopKError("Configured TopK collection is missing required source fields; choose the atlas semantic collection.")
            collection = client.collection(self.collection_name)
            self._lsn = collection.upsert(self._chunks) if self._chunks else None
        except TopKError:
            raise
        except Exception as exc:
            raise TopKError("TopK corpus indexing failed; no index status was recorded.") from None
        self._write_acknowledged = True
        self._submitted_chunk_count = len(self._chunks)
        self._verified = None
        self.last_metadata = {"provider": "topk", "mode": "live", "collection": self.collection_name,
                              "corpus_id": self._corpus_id, "write_acknowledged": True,
                              "submitted_chunk_count": len(self._chunks), "lsn": self._lsn}
        return dict(self.last_metadata)

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be nonempty text")
        if type(top_k) is not int or not 1 <= top_k <= 10000:
            raise ValueError("top_k must be an integer in [1, 10000]")
        if not self._chunks:
            return []
        try:
            from topk_sdk.query import select, field, fn
        except ImportError as exc:
            if not self._is_injected:
                raise TopKError("TopK search needs the optional SDK; install it with `pip install topk-sdk`.") from exc
            raise TopKError("TopK query helpers are required for search.") from exc
        client = self._get_client()
        try:
            rows = client.collection(self.collection_name).query(
                select("_id", "source_id", "source_version", "title", "passage", "start", "end", "corpus_id",
                       score=fn.semantic_similarity("passage", query))
                .filter(field("corpus_id") == self._corpus_id)
                .sort(field("score"), asc=False).limit(top_k),
                **({"lsn": self._lsn} if self._lsn else {}), consistency="indexed")
        except Exception as exc:
            raise TopKError("TopK semantic search failed.") from None
        if not isinstance(rows, list):
            raise TopKError("TopK returned a malformed result list.")
        hits = []
        for row in rows:
            if not isinstance(row, dict):
                raise TopKError("TopK returned a malformed result.")
            chunk_id = row.get("_id")
            expected = self._manifest.get(chunk_id)
            if expected is None:
                raise TopKError("TopK returned a result outside the supplied corpus snapshot.")
            # Compare every grounding field against our just-indexed manifest, then
            # independently verify the excerpt slice against the original source.
            if any(row.get(key) != expected[key] for key in
                   ("source_id", "source_version", "title", "passage", "start", "end", "corpus_id")):
                raise TopKError("TopK returned a stale or altered source passage.")
            source = self._docs[expected["source_id"]]
            if source["version"] != expected["source_version"] or source["text"][expected["start"]:expected["end"]] != expected["passage"]:
                raise TopKError("TopK passage does not match its source snapshot.")
            score = row.get("score")
            if type(score) not in (int, float) or not math.isfinite(score):
                raise TopKError("TopK returned an invalid relevance score.")
            hits.append({"source_id": expected["source_id"], "title": expected["title"],
                         "text": expected["passage"], "score": float(score),
                         "start": expected["start"], "end": expected["end"],
                         "source_version": expected["source_version"]})
        self._verified = bool(hits)
        self._last_verified_hit_count = len(hits)
        self.last_metadata = {"provider": "topk", "mode": "live", "collection": self.collection_name,
                              "corpus_id": self._corpus_id, "query_verified": bool(hits),
                              "verified_hit_count": len(hits), "indexed_documents": None, "searched_documents": None}
        return hits
