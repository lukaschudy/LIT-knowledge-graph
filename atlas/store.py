"""SQLite-backed atlas store.

``load_bundle`` validates the entire input before changing the database, then
atomically replaces the current dataset. A failed load leaves the old bundle
intact. Bundles are data only; no input content is executed.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .model import require_valid_bundle


class GraphStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        # Opening an unrelated SQLite file must not add Atlas tables or make
        # its existing nodes eligible for destructive dataset replacement.
        expected = {
            'metadata': {'key', 'value'},
            'nodes': {'id', 'type', 'label', 'aliases', 'payload'},
            'sources': {'id', 'payload'},
            'claims': {'id', 'subject', 'object', 'predicate', 'assertion_type', 'payload'},
            'evidence': {'id', 'claim_id', 'source_id', 'payload'},
            'coverage': {'id', 'source_id', 'entity_id', 'payload'},
        }
        try:
            tables = {row[0] for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                schemas = {name: list(self._conn.execute(f'PRAGMA table_info({name})')) for name in expected}
                if not expected.keys() <= tables or any(
                    not columns <= {row[1] for row in schemas[name]}
                    or [row[1] for row in schemas[name] if row[5]] != ['key' if name == 'metadata' else 'id']
                    for name, columns in expected.items()
                ):
                    raise ValueError('This file is not a curated Atlas database. Choose a separate output path.')
        except Exception:
            self._conn.close()
            raise
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT NOT NULL, aliases TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY, subject TEXT NOT NULL REFERENCES nodes(id), object TEXT NOT NULL REFERENCES nodes(id),
                predicate TEXT NOT NULL, assertion_type TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(id), source_id TEXT NOT NULL REFERENCES sources(id), payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS coverage (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), entity_id TEXT NOT NULL REFERENCES nodes(id), payload TEXT NOT NULL
            );
        """)
        self._conn.commit()

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    @staticmethod
    def _load(value: str) -> Any:
        return json.loads(value)

    def load_bundle(self, bundle: dict[str, Any]) -> dict[str, int]:
        """Validate then atomically replace all stored bundle rows."""
        require_valid_bundle(bundle)
        # Validate that properties/qualifiers are JSON data before beginning a write.
        serialized = {name: self._dump(bundle[name]) for name in ("dataset", "nodes", "sources", "claims", "evidence", "coverage")}
        with self._conn:
            self._conn.execute("DELETE FROM evidence")
            self._conn.execute("DELETE FROM coverage")
            self._conn.execute("DELETE FROM claims")
            self._conn.execute("DELETE FROM nodes")
            self._conn.execute("DELETE FROM sources")
            self._conn.execute("DELETE FROM metadata")
            self._conn.execute("INSERT INTO metadata(key, value) VALUES (?, ?)", ("schema_version", bundle["schema_version"]))
            self._conn.execute("INSERT INTO metadata(key, value) VALUES (?, ?)", ("dataset", serialized["dataset"]))
            self._conn.executemany(
                "INSERT INTO nodes(id, type, label, aliases, payload) VALUES (?, ?, ?, ?, ?)",
                [(n["id"], n["type"], n["label"], self._dump(n["aliases"]), self._dump(n)) for n in bundle["nodes"]],
            )
            self._conn.executemany("INSERT INTO sources(id, payload) VALUES (?, ?)", [(x["id"], self._dump(x)) for x in bundle["sources"]])
            self._conn.executemany(
                "INSERT INTO claims(id, subject, object, predicate, assertion_type, payload) VALUES (?, ?, ?, ?, ?, ?)",
                [(x["id"], x["subject"], x["object"], x["predicate"], x["assertion_type"], self._dump(x)) for x in bundle["claims"]],
            )
            self._conn.executemany(
                "INSERT INTO evidence(id, claim_id, source_id, payload) VALUES (?, ?, ?, ?)",
                [(x["id"], x["claim_id"], x["source_id"], self._dump(x)) for x in bundle["evidence"]],
            )
            self._conn.executemany(
                "INSERT INTO coverage(id, source_id, entity_id, payload) VALUES (?, ?, ?, ?)",
                [(x["id"], x["source_id"], x["entity_id"], self._dump(x)) for x in bundle["coverage"]],
            )
        return self.stats()

    def bundle(self) -> dict[str, Any]:
        row = self._conn.execute("SELECT value FROM metadata WHERE key='dataset'").fetchone()
        if row is None:
            return {}
        version = self._conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
        out: dict[str, Any] = {"schema_version": version, "dataset": self._load(row[0])}
        for name in ("nodes", "sources", "claims", "evidence", "coverage"):
            out[name] = [self._load(row[0]) for row in self._conn.execute(f"SELECT payload FROM {name} ORDER BY rowid")]
        return out

    def stats(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for name in ("nodes", "sources", "claims", "evidence", "coverage"):
            result[name] = self._conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        return result

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT payload FROM nodes WHERE id=?", (node_id,)).fetchone()
        return self._load(row[0]) if row else None

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search IDs, labels, and aliases; exact matches precede substring hits."""
        needle = query.strip().casefold()
        if not needle:
            return []
        found: list[tuple[int, int, dict[str, Any]]] = []
        rows = self._conn.execute("SELECT rowid, payload FROM nodes ORDER BY rowid").fetchall()
        for row in rows:
            node = self._load(row["payload"])
            terms = [node["id"], node["label"], *node["aliases"]]
            normalized = [term.casefold() for term in terms]
            if needle in normalized:
                rank = 0
            elif any(needle in term for term in normalized):
                rank = 1
            else:
                continue
            found.append((rank, row["rowid"], node))
        found.sort(key=lambda item: (item[0], item[1]))
        return [entry[2] for entry in found]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
