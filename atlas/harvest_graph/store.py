"""Read-only, bounded graph projection over the harvested-record SQLite index.

Harvest rows are represented as source relationships and record pointers. They are
not imported into the curated claim/evidence model and do not acquire review status.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from functools import lru_cache
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import struct
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  expected_rows INTEGER NOT NULL,
  processed_rows INTEGER NOT NULL,
  status TEXT NOT NULL,
  metadata TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
  nid INTEGER PRIMARY KEY,
  id TEXT UNIQUE NOT NULL,
  type TEXT NOT NULL,
  label TEXT NOT NULL,
  dataset INTEGER NOT NULL,
  record INTEGER NOT NULL,
  offset INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS predicates (
  pid INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
  eid INTEGER PRIMARY KEY,
  subject INTEGER NOT NULL,
  predicate INTEGER NOT NULL,
  object INTEGER NOT NULL,
  dataset INTEGER NOT NULL,
  record INTEGER NOT NULL,
  offset INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def _offset_stamp(stat):
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_dev


@lru_cache(maxsize=128)
def _file_digest(path, stamp):
    """Hash source/sidecar bytes once per filesystem version, not once per row."""
    digest = sha256()
    with open(path, 'rb') as handle:
        if _offset_stamp(os.fstat(handle.fileno())) != stamp:
            raise ValueError('Source file or index changed while checking its receipt.')
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
        if _offset_stamp(os.fstat(handle.fileno())) != stamp:
            raise ValueError('Source file or index changed while checking its receipt.')
    return digest.hexdigest()


# Preserve the existing helper name for callers inspecting offset-cache stats.
_offset_digest = _file_digest


@contextmanager
def _connection(path: Path, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    if readonly:
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=10)
        connection.execute("PRAGMA query_only=ON")
    else:
        connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize(conn: sqlite3.Connection) -> None:
    """Create the shared harvest schema; bulk-import indexes are added by the builder."""
    conn.executescript(SCHEMA)


_TABLES = ('datasets', 'nodes', 'predicates', 'edges', 'metadata')


def _schema_contract(conn):
    """Columns and uniqueness are both required for resumable INSERT OR IGNORE."""
    contract = {}
    for table in _TABLES:
        columns = tuple(tuple(row)[1:] for row in conn.execute(f'PRAGMA table_info({table})'))
        unique = set()
        for index in conn.execute(f'PRAGMA index_list({table})'):
            if index[2]:
                name = index[1].replace('"', '""')
                unique.add((tuple(row[2] for row in conn.execute(f'PRAGMA index_info("{name}")')), index[4]))
        contract[table] = (columns, frozenset(unique))
    return contract


@lru_cache(maxsize=1)
def _expected_schema_contract():
    conn = sqlite3.connect(':memory:')
    try:
        initialize(conn)
        return _schema_contract(conn)
    finally:
        conn.close()


def validate_schema(conn: sqlite3.Connection, *, allow_empty=False) -> bool:
    """Check compatibility before any journal-mode, schema, or content write."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not tables and allow_empty:
        # A views-only database is not an unused output database either.
        if not conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
            return False
    if not set(_TABLES) <= tables or _schema_contract(conn) != _expected_schema_contract():
        raise ValueError('Output database is not a harvest index with the required schema; choose a new output database.')
    return True


class HarvestGraph:
    """Thread-safe read API for a potentially multi-million-edge local index.

    Each public operation opens a read-only SQLite connection. Graph/search outputs
    are capped and contain pointers into the original harvested sources, not copies
    of their raw rows.
    """

    def __init__(self, path: str | Path, source_root: str | Path | None = None):
        self.path = Path(path).resolve()
        self.source_root = Path(source_root).resolve() if source_root is not None else self.path.parent
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        # Fail early on an unrelated or incomplete SQLite file without keeping a
        # connection alive across request threads.
        with _connection(self.path, readonly=True) as conn:
            validate_schema(conn)

    @staticmethod
    def _decode(value: Any, fallback=None):
        if value is None:
            return fallback
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    @staticmethod
    def _limit(value: int, *, default: int, maximum: int) -> int:
        if type(value) is not int:
            return default
        return max(1, min(maximum, value))

    @staticmethod
    def _meta(conn: sqlite3.Connection) -> dict[str, Any]:
        return {row["key"]: HarvestGraph._decode(row["value"])
                for row in conn.execute("SELECT key,value FROM metadata")}

    def _stats(self, conn: sqlite3.Connection) -> dict[str, int]:
        meta = self._meta(conn)
        nested = meta.get("stats") or meta.get("harvest_stats") or {}
        if not isinstance(nested, dict):
            nested = {}
        def value(name: str, query: str) -> int:
            raw = nested.get(name, meta.get(name))
            try:
                if raw is not None:
                    return int(raw)
            except (TypeError, ValueError):
                pass
            row = conn.execute(query).fetchone()
            return int(row[0] or 0)
        return {
            "total_nodes": value("total_nodes", "SELECT COUNT(*) FROM nodes"),
            "total_edges": value("total_edges", "SELECT COUNT(*) FROM edges"),
            "total_records": int(nested.get("total_records", nested.get("processed_records",
                                      meta.get("total_records", meta.get("processed_records", 0)))) or
                                  value("total_records", "SELECT COALESCE(SUM(processed_rows),0) FROM datasets")),
            "total_datasets": value("total_datasets", "SELECT COUNT(*) FROM datasets"),
        }

    @staticmethod
    def _dataset_row(conn: sqlite3.Connection, dataset: str | int) -> sqlite3.Row | None:
        if isinstance(dataset, int) or (isinstance(dataset, str) and dataset.startswith("dataset:") and dataset[8:].isdigit()):
            raw = dataset if isinstance(dataset, int) else dataset[8:]
            if isinstance(raw, str) and (not raw.isascii() or len(raw) > 19):
                return None
            ident = int(raw)
            if not 0 < ident <= 2**63 - 1:
                return None
            return conn.execute("SELECT * FROM datasets WHERE id=?", (ident,)).fetchone()
        return conn.execute("SELECT * FROM datasets WHERE key=?", (str(dataset),)).fetchone()

    def _dataset_summary(self, row: sqlite3.Row) -> dict[str, Any]:
        metadata = self._decode(row["metadata"], {})
        if not isinstance(metadata, dict):
            metadata = {"description": metadata}
        return {
            "id": f"dataset:{row['id']}", "dataset_id": row["id"], "key": row["key"],
            "label": metadata.get("title") or metadata.get("label") or row["key"],
            "path": row["path"], "sha256": row["sha256"],
            "expected_rows": row["expected_rows"], "processed_rows": row["processed_rows"],
            "status": row["status"], "metadata": metadata,
        }

    def _pointer(self, conn: sqlite3.Connection, dataset_id: int, row_number: int,
                 offset: int | None = None, *, compact: bool = False,
                 dataset_cache: dict[int, dict[str, Any]] | None = None) -> dict[str, Any] | None:
        ds_data = dataset_cache.get(dataset_id) if dataset_cache is not None else None
        if ds_data is None:
            ds = conn.execute("SELECT id,key,path,sha256,processed_rows,metadata FROM datasets WHERE id=?", (dataset_id,)).fetchone()
            if ds is None:
                return None
            metadata = self._decode(ds["metadata"], {})
            if not isinstance(metadata, dict):
                metadata = {}
            ds_data = {"id": ds["id"], "key": ds["key"], "path": ds["path"],
                       "sha256": ds["sha256"], "processed_rows": ds["processed_rows"],
                       "metadata": metadata}
            if dataset_cache is not None:
                dataset_cache[dataset_id] = ds_data
        if type(row_number) is not int or not 1 <= row_number <= ds_data["processed_rows"]:
            return None
        if offset is None:
            offsets_path = Path(str(self.path) + ".sources") / f"{dataset_id}.offsets"
            try:
                receipt = ds_data['metadata'].get('offsets_sha256')
                if receipt is not None:
                    stamp = _offset_stamp(offsets_path.stat())
                    if _offset_digest(str(offsets_path), stamp) != receipt:
                        raise ValueError('Source offset index checksum differs from its ingestion receipt.')
                with offsets_path.open("rb") as handle:
                    if receipt is not None and _offset_stamp(os.fstat(handle.fileno())) != stamp:
                        raise ValueError('Source offset index changed after checking its receipt.')
                    preceding = int(row_number > 1)
                    following = int(row_number < ds_data["processed_rows"])
                    count = preceding + 1 + following
                    handle.seek((row_number - 1 - preceding) * 8)
                    raw = handle.read(count * 8)
                if len(raw) != count * 8:
                    raise ValueError("The committed source offset index is truncated; rebuild it before reading records.")
                nearby = struct.unpack('<' + 'Q' * count, raw)
                offset = nearby[preceding]
                if (row_number == 1 and offset != 0) or any(a >= b for a, b in zip(nearby, nearby[1:])):
                    raise ValueError("The source offset index is inconsistent; rebuild it before reading records.")
            except FileNotFoundError:
                if receipt is not None:
                    raise ValueError('The receipted source offset index is missing; rebuild it before reading records.') from None
        # Older tiny indexes may not have a row-offset sidecar yet. Keep a
        # compatibility fallback, but never scan millions of mapped rows when
        # the canonical sidecar is present.
        if offset is None:
            found = conn.execute(
                "SELECT offset FROM nodes WHERE dataset=? AND record=? "
                "UNION ALL SELECT offset FROM edges WHERE dataset=? AND record=? LIMIT 1",
                (dataset_id, row_number, dataset_id, row_number)).fetchone()
            if found:
                offset = int(found[0])
        pointer = {"id": f"record:{dataset_id}:{row_number}", "dataset": f"dataset:{dataset_id}",
                   "dataset_id": dataset_id, "row": row_number, "offset": offset}
        if compact:
            return pointer
        metadata = ds_data["metadata"]
        return {**pointer, "dataset_key": ds_data["key"], "path": ds_data["path"],
                "sha256": ds_data["sha256"], "metadata": metadata,
                "source_urls": metadata.get("source_urls", []), "licenses": metadata.get("licenses", [])}

    def _node(self, conn: sqlite3.Connection, row: sqlite3.Row, *, compact: bool = False,
              dataset_cache: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
        pointer = self._pointer(conn, row["dataset"], row["record"], row["offset"],
                                compact=compact, dataset_cache=dataset_cache)
        return {"id": row["id"], "type": row["type"], "label": row["label"], "aliases": [],
                "provenance": pointer,
                "properties": {"harvest": True, "source_dataset": pointer["dataset"] if pointer else None,
                               "record": pointer, "review_status": "unreviewed_source_relationship"}}

    def _edge(self, conn: sqlite3.Connection, row: sqlite3.Row, *, compact: bool = False,
              dataset_cache: dict[int, dict[str, Any]] | None = None,
              predicate_cache: dict[int, str] | None = None) -> dict[str, Any]:
        pointer = self._pointer(conn, row["dataset"], row["record"], row["offset"],
                                compact=compact, dataset_cache=dataset_cache)
        predicate_value = row["predicate"]
        if isinstance(predicate_value, int):
            predicate_name = predicate_cache.get(predicate_value) if predicate_cache is not None else None
            if predicate_name is None:
                predicate_row = conn.execute("SELECT name FROM predicates WHERE pid=?", (predicate_value,)).fetchone()
                predicate_name = predicate_row["name"] if predicate_row else f"unresolved_predicate:{predicate_value}"
                if predicate_cache is not None:
                    predicate_cache[predicate_value] = predicate_name
            predicate_value = predicate_name
        return {"id": f"harvest:edge:{row['eid']}", "subject": row["subject_id"],
                "predicate": predicate_value, "object": row["object_id"],
                "assertion_type": "reported", "extraction_confidence": None,
                "provenance": pointer,
                "context": {"scope": "unreviewed source relationship", "harvest": True,
                            "negated": str(predicate_value).startswith("NOT_"),
                            "record": pointer}}

    @staticmethod
    def _edges_between(conn: sqlite3.Connection, nids: list[int], limit: int) -> list[sqlite3.Row]:
        if not nids:
            return []
        # IDs originate in the local integer primary key, so inline them in a
        # bounded CTE instead of writing a temp table on a read-only connection.
        # IN materializes a membership lookup; joining a second VALUES alias
        # makes SQLite scan the entire selection for each matching edge.
        selected = ",".join(f"({int(nid)})" for nid in nids)
        return conn.execute(
            f"WITH selected_nids(nid) AS (VALUES {selected}) "
            "SELECT e.*,s.id AS subject_id,o.id AS object_id "
            "FROM selected_nids a CROSS JOIN edges e "
                        "JOIN nodes s ON s.nid=e.subject JOIN nodes o ON o.nid=e.object "
            "WHERE e.subject=a.nid AND e.object IN (SELECT nid FROM selected_nids) LIMIT ?", (limit,)).fetchall()

    @staticmethod
    def _focused_edges(conn: sqlite3.Connection, nid: int, after_eid: int, limit: int) -> list[sqlite3.Row]:
        """Fetch one bounded edge page via the subject/object indexes.

        Each branch is ordered by the INTEGER PRIMARY KEY (rowid) within its
        indexed adjacency range; the union and deduplication happen over at
        most 2*(limit+1) rows, never a million-edge sort.
        """
        rows = []
        for column in ("subject", "object"):
            # Do not force an index name so small legacy fixtures with equivalent
            # indexes remain usable; production builder creates these indexes.
            rows.extend(conn.execute(
                f"SELECT e.*,s.id AS subject_id,o.id AS object_id FROM edges e "
                "JOIN nodes s ON s.nid=e.subject JOIN nodes o ON o.nid=e.object "
                f"WHERE e.{column}=? AND e.eid>? ORDER BY e.eid LIMIT ?",
                (nid, after_eid, limit)).fetchall())
        unique = {row["eid"]: row for row in rows}
        return [unique[eid] for eid in sorted(unique)[:limit]]

    def graph(self, limit: int = 3000, offset: int = 0, focus: str | None = None) -> dict[str, Any]:
        limit = self._limit(limit, default=3000, maximum=10000)
        offset = min(2**63 - 1, max(0, offset)) if type(offset) is int else 0
        if focus and limit < 2:
            raise ValueError('A focused graph page needs room for the selected node and a neighbor (limit at least 2).')
        with _connection(self.path, readonly=True) as conn:
            stats = self._stats(conn)
            selected: list[sqlite3.Row]
            if focus:
                center = conn.execute("SELECT * FROM nodes WHERE id=?", (focus,)).fetchone()
                if center is None:
                    selected = []
                    edges = []
                    has_more_nodes = False
                    has_more_edges = False
                else:
                    cursor = max(0, offset)
                    edge_page_size = max(1, limit - 1)
                    edge_rows = self._focused_edges(conn, center["nid"], cursor, edge_page_size + 1)
                    has_more_edges = len(edge_rows) > edge_page_size
                    edge_rows = edge_rows[:edge_page_size]
                    ids = {center["nid"]}
                    for edge in edge_rows:
                        ids.add(edge["subject"]); ids.add(edge["object"])
                    selected = [center]
                    other_ids = sorted(ids - {center["nid"]})[:max(0, limit - 1)]
                    has_more_nodes = len(ids) > len(other_ids) + 1
                    if other_ids:
                        selected_ids = ",".join(f"({int(nid)})" for nid in other_ids)
                        selected.extend(conn.execute(
                            f"WITH focus_nids(nid) AS (VALUES {selected_ids}) "
                            "SELECT * FROM nodes WHERE nid IN (SELECT nid FROM focus_nids) ORDER BY nid").fetchall())
                    kept = {r["nid"] for r in selected}
                    edges = [row for row in edge_rows if row["subject"] in kept and row["object"] in kept]
            else:
                selected = conn.execute("SELECT * FROM nodes WHERE nid>? ORDER BY nid LIMIT ?", (offset, limit)).fetchall()
                ids = [row["nid"] for row in selected]
                edge_rows = self._edges_between(conn, ids, limit + 1)
                has_more_edges = len(edge_rows) > limit
                edges = edge_rows[:limit]
                if selected:
                    has_more_nodes = conn.execute("SELECT 1 FROM nodes WHERE nid>? LIMIT 1",
                                                   (selected[-1]["nid"],)).fetchone() is not None
                else:
                    has_more_nodes = False
            dataset_cache: dict[int, dict[str, Any]] = {}
            predicate_cache: dict[int, str] = {}
            nodes = [self._node(conn, row, compact=True, dataset_cache=dataset_cache) for row in selected]
            claims = [self._edge(conn, row, compact=True, dataset_cache=dataset_cache,
                                 predicate_cache=predicate_cache) for row in edges]
            return {
                "schema_version": "1.0",
                "dataset": {"id": "harvest:projection", "title": "Harvested source relationships",
                            "description": "A bounded view of source-derived records. Relationships are unreviewed and have no curated evidence rows.",
                            "synthetic": False},
                "nodes": nodes, "claims": claims, "evidence": [], "sources": [], "coverage": [],
                "harvest": {**stats, "shown_nodes": len(nodes), "shown_edges": len(claims),
                            "offset": offset,
                            "next_offset": (edges[-1]["eid"] if focus and edges and has_more_edges else
                                            selected[-1]["nid"] if selected and not focus and has_more_nodes else None),
                            "truncated": has_more_nodes or has_more_edges, "limit": limit, "focus": focus,
                            "cursor_kind": "edge_id" if focus else "node_id",
                            "note": "Harvested source rows are not human-reviewed Atlas evidence."},
            }

    def search(self, q: str, limit: int = 40) -> dict[str, Any]:
        if not isinstance(q, str) or not q.strip() or len(q.strip()) > 500:
            raise ValueError("Search query must contain 1–500 characters.")
        limit = self._limit(limit, default=40, maximum=200)
        query = q.strip()
        try:
            query.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueError('Search query must contain valid Unicode text.') from None
        with _connection(self.path, readonly=True) as conn:
            exact = conn.execute("SELECT * FROM nodes WHERE id=? LIMIT ?", (query, limit)).fetchall()
            remaining = limit - len(exact)
            prefix_rows = []
            if remaining:
                # Match SQLite NOCASE's ASCII fold before computing the upper
                # bound: uppercase Z + 1 is '[', which sorts *before* folded z.
                folded = query.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))
                prefix = folded.rstrip(chr(0x10FFFF))
                upper = prefix[:-1] + chr(ord(prefix[-1]) + 1) if prefix else None
                upper_clause = "AND label<? COLLATE NOCASE " if upper is not None else ""
                parameters = (folded, upper, query, remaining) if upper is not None else (folded, query, remaining)
                prefix_rows = conn.execute(
                    "SELECT * FROM nodes WHERE label>=? COLLATE NOCASE " + upper_clause +
                    "AND id<>? ORDER BY label COLLATE NOCASE,nid LIMIT ?", parameters).fetchall()
            rows = exact + prefix_rows
            return {"query": query, "total": len(rows), "results": [self._node(conn, row) for row in rows]}

    def datasets(self) -> list[dict[str, Any]]:
        with _connection(self.path, readonly=True) as conn:
            return [self._dataset_summary(row) for row in conn.execute("SELECT * FROM datasets ORDER BY id")]

    def dataset(self, dataset_id: str | int) -> dict[str, Any] | None:
        with _connection(self.path, readonly=True) as conn:
            row = self._dataset_row(conn, dataset_id)
            if row is None:
                return None
            summary = self._dataset_summary(row)
            return {"id": summary["id"], "type": "Dataset", "label": summary["label"],
                    "aliases": [], "properties": {k: v for k, v in summary.items() if k not in ("id", "label")}}

    def records(self, dataset_id: str | int, page: int = 0, limit: int = 50) -> dict[str, Any] | None:
        if type(page) is not int or page < 0:
            raise ValueError("Page must be a nonnegative integer.")
        limit = self._limit(limit, default=50, maximum=200)
        with _connection(self.path, readonly=True) as conn:
            ds = self._dataset_row(conn, dataset_id)
            if ds is None:
                return None
            first = page * limit + 1
            last = min(ds["processed_rows"], first + limit - 1)
            rows = [self._pointer(conn, ds["id"], number) for number in range(first, last + 1)] if first <= last else []
            return {"dataset": self._dataset_summary(ds), "page": page, "limit": limit,
                    "total": ds["processed_rows"], "records": rows}

    def record_pointer(self, dataset_id: str | int, row_number: int) -> dict[str, Any] | None:
        with _connection(self.path, readonly=True) as conn:
            ds = self._dataset_row(conn, dataset_id)
            if ds is None:
                return None
            return self._pointer(conn, ds["id"], row_number)

    def record(self, dataset_id: str | int, row_number: int) -> dict[str, Any] | None:
        """Return a virtual source-row identity and its indexed provenance pointer."""
        return self.record_pointer(dataset_id, row_number)

    def node(self, node_id: str) -> dict[str, Any] | None:
        with _connection(self.path, readonly=True) as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
            return self._node(conn, row) if row is not None else None

    def claim(self, claim_id: str) -> dict[str, Any] | None:
        prefix = "harvest:edge:"
        if not isinstance(claim_id, str) or not claim_id.startswith(prefix) or not claim_id[len(prefix):].isdigit():
            return None
        token = claim_id[len(prefix):]
        if not token.isascii() or len(token) > 19:
            return None
        eid = int(token)
        if not 0 < eid <= 2**63 - 1:
            return None
        with _connection(self.path, readonly=True) as conn:
            row = conn.execute(
                "SELECT e.*,s.id AS subject_id,o.id AS object_id FROM edges e "
                "JOIN nodes s ON s.nid=e.subject JOIN nodes o ON o.nid=e.object WHERE e.eid=?", (eid,)).fetchone()
            return self._edge(conn, row) if row is not None else None

    def status(self) -> dict[str, Any]:
        with _connection(self.path, readonly=True) as conn:
            stats = self._stats(conn)
            meta = self._meta(conn)
            build_stats = meta.get("stats") or meta.get("harvest_stats") or {}
            if not isinstance(build_stats, dict):
                build_stats = {}
            rows = conn.execute("SELECT * FROM datasets ORDER BY id").fetchall()
            return {**stats, "datasets": [self._dataset_summary(row) for row in rows],
                    "processed_records": int(build_stats.get("processed_records", stats["total_records"])),
                    "completed_datasets": int(build_stats.get("completed_datasets", 0)),
                    "build_status": build_stats.get("status", "unknown"),
                    "status": build_stats.get("status", "unknown"), "stats": build_stats,
                    "source_rows_materialized_as_nodes": False,
                    "claim_semantics": "Unreviewed source relationship projection; not curated evidence."}
