"""Read-only HTTP server for the local synthetic research atlas."""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .reasoning import AtlasReasoner
from .recommendations import RecommendationEngine, ResearchRequest


WEB_DIR = Path(__file__).with_name("web")
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/explore": ("explore.html", "text/html; charset=utf-8"),
    "/cover.css": ("cover.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/fonts/instrument-sans-latin-wght-normal.woff2": ("fonts/instrument-sans-latin-wght-normal.woff2", "font/woff2"),
    "/images/connected-biology.png": ("images/connected-biology.png", "image/png"),
    "/fonts/ibm-plex-sans-latin-wght-normal.woff2": ("fonts/ibm-plex-sans-latin-wght-normal.woff2", "font/woff2"),
    "/fonts/ibm-plex-mono-latin-400-normal.woff2": ("fonts/ibm-plex-mono-latin-400-normal.woff2", "font/woff2"),
}


def _index_by_id(bundle: dict[str, Any], collection: str) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in bundle.get(collection, []) if isinstance(item, dict) and item.get("id")}


def _node_terms(node: dict[str, Any]) -> list[str]:
    properties = node.get("properties", {})
    return [str(value) for value in [node["id"], node["label"], *node["aliases"]]
            if isinstance(value, (str, int, float))]


def _node_label(node: dict[str, Any]) -> str:
    return str(node.get("name") or node.get("label") or node.get("symbol") or node.get("id") or "Untitled node")


def _references(row: dict[str, Any], *keys: str) -> list[str]:
    result: list[str] = []
    for key in keys:
        value = row.get(key, [])
        if isinstance(value, str):
            result.append(value)
        elif isinstance(value, list):
            result.extend(str(item) for item in value if isinstance(item, (str, int)))
    return list(dict.fromkeys(result))


def create_server(store: Any, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    """Create a testable threaded server around a startup snapshot of ``store``.

    The store and reasoner are only touched on this calling thread. Requests are
    served from the immutable bundle snapshot, which also keeps SQLite-backed
    stores safe from cross-thread connection use.
    """
    bundle = store.bundle()
    stats = store.stats()
    reasoner = AtlasReasoner(bundle)
    recommendations = RecommendationEngine(bundle)
    nodes = _index_by_id(bundle, "nodes")
    claims = _index_by_id(bundle, "claims")
    evidence = _index_by_id(bundle, "evidence")
    sources = _index_by_id(bundle, "sources")
    node_terms = {node_id: [term.casefold() for term in _node_terms(node)] for node_id, node in nodes.items()}
    evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
    for row in bundle["evidence"]:
        evidence_by_claim.setdefault(row["claim_id"], []).append(row)

    class AtlasHandler(BaseHTTPRequestHandler):
        server_version = "ResearchAtlas/1.0"
        sys_version = ""

        def log_message(self, fmt: str, *args: Any) -> None:
            # Keep the terminal focused on the application, not polling noise.
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _error(self, status: int, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            try:
                parsed = urlsplit(self.path)
                path = parsed.path
                query = parse_qs(parsed.query, keep_blank_values=True)
                if path in _ASSETS:
                    self._asset(path)
                elif path.startswith("/api/"):
                    self._api(path, query)
                else:
                    self._error(404, "not_found", "That atlas page does not exist.")
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                self._error(500, "internal_error", "The atlas could not complete that request.")

        def _asset(self, path: str) -> None:
            filename, content_type = _ASSETS[path]
            asset = WEB_DIR / filename
            try:
                body = asset.read_bytes()
            except OSError:
                self._error(500, "asset_unavailable", "An atlas interface file could not be loaded.")
                return
            self._send(200, body, content_type)

        def _one(self, query: dict[str, list[str]], key: str) -> str | None:
            values = query.get(key, [])
            if len(values) != 1:
                return None
            value = values[0].strip()
            return value or None

        def _api(self, path: str, query: dict[str, list[str]]) -> None:
            if path == "/api/recommend":
                fields = ("disease_id", "mechanism_id", "mechanism_step", "readout", "species", "tissue")
                if set(query) - {*fields, "stage"} or not set(fields) <= set(query) or any(self._one(query, field) is None for field in query):
                    self._error(400, "invalid_request", "Supply exactly one value for each field: " + ", ".join(fields))
                    return
                try:
                    result = recommendations.run(ResearchRequest(**{field: self._one(query, field) for field in query}))
                except ValueError as exc:
                    self._error(400, "invalid_request", str(exc))
                    return
                self._json(200, result)
                return
            if path == "/api/health":
                self._json(200, {"status": "ok", "synthetic": bool(bundle["dataset"]["synthetic"]), "dataset": bundle["dataset"]})
                return
            if path == "/api/stats":
                self._json(200, {"dataset": bundle["dataset"], "stats": stats})
                return
            if path == "/api/graph":
                self._json(200, bundle)
                return
            if path == "/api/search":
                term = self._one(query, "q")
                if term is None:
                    self._error(400, "missing_query", "Enter a name, synonym, or identifier to search the atlas.")
                    return
                folded = term.casefold()
                matches: list[tuple[int, dict[str, Any]]] = []
                for node_id, terms in node_terms.items():
                    node = nodes[node_id]
                    if folded in terms:
                        score = 0
                    elif any(folded in value for value in terms):
                        score = 1
                    else:
                        continue
                    matches.append((score, node))
                matches.sort(key=lambda item: (item[0], _node_label(item[1]).casefold(), str(item[1].get("id"))))
                self._json(200, {"query": term, "total": len(matches), "results": [node for _, node in matches[:40]]})
                return
            if path == "/api/explore":
                disease_id = self._one(query, "disease")
                if disease_id is None:
                    self._error(400, "missing_disease", "Choose a disease to explore.")
                    return
                node = nodes.get(disease_id)
                if node is None:
                    self._error(404, "disease_not_found", "That disease is not in this atlas dataset.")
                    return
                if str(node.get("type", node.get("kind", ""))).casefold() != "disease":
                    self._error(400, "not_a_disease", "Choose a disease node to explore connections.")
                    return
                result = reasoner.explore(disease_id)
                self._json(200, result)
                return
            if path == "/api/claim":
                claim_id = self._one(query, "id")
                if claim_id is None:
                    self._error(400, "missing_claim", "Choose an evidence claim to inspect.")
                    return
                claim = claims.get(claim_id)
                if claim is None:
                    self._error(404, "claim_not_found", "That claim is not in this atlas dataset.")
                    return
                claim_evidence = evidence_by_claim.get(claim_id, [])
                support_rows = [row for row in claim_evidence if row["stance"] == "supports"]
                contradiction_rows = [row for row in claim_evidence if row["stance"] == "contradicts"]
                source_ids = list(dict.fromkeys(row["source_id"] for row in claim_evidence))
                self._json(200, {
                    "claim": claim,
                    "support": support_rows,
                    "contradictions": contradiction_rows,
                    "sources": [sources[item] for item in dict.fromkeys(source_ids) if item in sources],
                })
                return
            self._error(404, "api_not_found", "That atlas endpoint does not exist.")

        def do_POST(self) -> None:  # noqa: N802
            self._error(405, "method_not_allowed", "This atlas is read-only.")

        def do_PUT(self) -> None:  # noqa: N802
            self._error(405, "method_not_allowed", "This atlas is read-only.")

        def do_DELETE(self) -> None:  # noqa: N802
            self._error(405, "method_not_allowed", "This atlas is read-only.")

    return ThreadingHTTPServer((host, port), AtlasHandler)


def serve(store: Any, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the atlas server until interrupted."""
    server = create_server(store, host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
