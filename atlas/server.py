"""Local atlas explorer and opt-in writable research workspace HTTP server."""

from __future__ import annotations

import json
import mimetypes
import threading
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .http_api import AtlasAPI
from .reasoning import AtlasReasoner
from .recommendations import RecommendationEngine, ResearchRequest


WEB_DIR = Path(__file__).with_name("web")
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/explore": ("explore.html", "text/html; charset=utf-8"),
    "/records": ("records.html", "text/html; charset=utf-8"),
    "/graph.css": ("graph.css", "text/css; charset=utf-8"),
    "/voice.js": ("voice.js", "text/javascript; charset=utf-8"),
    "/graph-renderer.js": ("graph-renderer.js", "text/javascript; charset=utf-8"),
    "/graph.js": ("graph.js", "text/javascript; charset=utf-8"),
    "/transition.css": ("transition.css", "text/css; charset=utf-8"),
    "/transition.js": ("transition.js", "text/javascript; charset=utf-8"),
    "/workspace.css": ("workspace.css", "text/css; charset=utf-8"),
    "/workspace.js": ("workspace.js", "text/javascript; charset=utf-8"),
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


def create_server(store: Any, host: str = "127.0.0.1", port: int = 8765, *, workspace=None, harvest=None, resolved=None, transcriber=None) -> ThreadingHTTPServer:
    """Create a testable threaded server around a startup snapshot of ``store``.

    The store and reasoner are only touched on this calling thread. Requests are
    served from the immutable bundle snapshot, which also keeps SQLite-backed
    stores safe from cross-thread connection use.
    """
    if workspace is not None and host not in ("127.0.0.1", "localhost"):
        raise ValueError("The writable research workspace binds to loopback only; multi-user hosting requires authentication.")
    if workspace is not None and transcriber is None:
        from .voice import LocalTranscriber
        transcriber = LocalTranscriber()
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
                if workspace is not None and not self._local_request():
                    return
                parsed = urlsplit(self.path)
                path = parsed.path
                query = parse_qs(parsed.query, keep_blank_values=True)
                if path in _ASSETS:
                    self._asset(path)
                elif workspace is not None and path == "/research":
                    self.send_response(302)
                    self.send_header("Location", "/explore")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
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
            if path == "/api/voice/status":
                self._json(200, transcriber.status() if transcriber is not None else {"available": False, "message": "Voice requires the local research workspace."})
                return
            if path.startswith("/api/resolved/"):
                self._resolved_api(path, query)
                return
            if path.startswith("/api/harvest/"):
                self._harvest_api(path, query)
                return
            if workspace is None and path == "/api/ask":
                status, payload = AtlasAPI(bundle, stats).request(path, query)
                self._json(status, payload)
                return
            if path.startswith("/api/research/"):
                if workspace is None:
                    self._error(404, "workspace_unavailable", "Start `python -m atlas research` to open a research workspace.")
                    return
                from .workflow import WorkflowError
                try:
                    if path == "/api/research/state":
                        self._json(200, workspace.state())
                    elif path.startswith("/api/research/jobs/"):
                        self._json(200, workspace.job(path.removeprefix("/api/research/jobs/")))
                    else:
                        self._error(404, "api_not_found", "Unknown research endpoint.")
                except WorkflowError as exc:
                    self._error(exc.status, exc.code, str(exc))
                return
            if path == "/api/ask" and workspace is not None:
                self._error(405, "method_not_allowed", "Use POST /api/atlas/ask to start a cited atlas answer job.")
                return
            if workspace is not None and path == "/api/recommend":
                fields = ("disease_id", "mechanism_id", "mechanism_step", "readout", "species", "tissue")
                if set(query) - {*fields, "stage"} or not set(fields) <= set(query) or any(self._one(query, field) is None for field in query):
                    self._error(400, "invalid_request", "Supply exactly one value for each field: " + ", ".join(fields))
                    return
                try:
                    with workspace.lock:
                        active = workspace._active_bundle()
                    engine = RecommendationEngine(active)
                    request = ResearchRequest(**{field: self._one(query, field) for field in query})
                    self._json(200, engine.run(request))
                except ValueError as exc:
                    self._error(400, "invalid_request", str(exc))
                return
            if workspace is not None and path in ("/api/graph", "/api/stats", "/api/claim", "/api/search", "/api/explore", "/api/health"):
                with workspace.lock:
                    active = workspace._active_bundle()
                live_stats = {name: len(active.get(name, [])) for name in ("nodes", "sources", "claims", "evidence", "coverage")}
                api = AtlasAPI(active, live_stats)
                status, payload = api.request(path, query)
                self._json(status, payload)
                return
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

        def _local_request(self) -> bool:
            port = self.server.server_address[1]
            authorities = {f"127.0.0.1:{port}", f"localhost:{port}"}
            authority = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if authority not in authorities or (origin is not None and origin != "http://" + authority):
                self._error(403, "invalid_origin", "Research requests must originate from this local workspace.")
                return False
            return True

        def do_POST(self) -> None:  # noqa: N802
            if workspace is None:
                self._error(405, "method_not_allowed", "This atlas is read-only.")
                return
            if not self._local_request():
                return
            if not secrets.compare_digest(self.headers.get("X-Atlas-Token", ""), workspace.token):
                self._error(403, "invalid_token", "Reload the research workspace before applying changes.")
                return
            if urlsplit(self.path).path == "/api/voice/transcribe":
                self._transcribe_audio()
                return
            from .workflow import WorkflowError
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise WorkflowError("Use application/json for research requests.", status=415)
                if self.headers.get("Transfer-Encoding"):
                    raise WorkflowError("Chunked request bodies are not supported.")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 100000:
                    raise WorkflowError("Request body must contain 1–100,000 bytes.", status=413)
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise WorkflowError("Request body must be a JSON object.")
                path = urlsplit(self.path).path
                if path == "/api/research/extract":
                    self._json(202, workspace.start_job("extract", **body))
                elif path == "/api/research/explain":
                    self._json(202, workspace.start_job("explain", **body))
                elif path == "/api/research/investigate":
                    self._json(202, workspace.start_job("investigate", **body))
                elif path == "/api/research/review":
                    self._json(200, workspace.review(**body))
                elif path == "/api/research/analyze":
                    self._json(200, workspace.analyze(**body))
                elif path == "/api/research/brief":
                    self._json(200, workspace.save_brief(**body))
                elif path == "/api/research/brief/reset":
                    self._json(200, workspace.reset_brief(**body))
                elif path == "/api/atlas/ask":
                    self._json(202, workspace.start_job("ask", **body))
                elif path == "/api/atlas/source":
                    # The browser contributes only a catalog key; text/URL/title are
                    # resolved server-side from the verified local catalog.
                    self._json(200, workspace.import_source(revision=body.get('revision'), hit_id=body.get('hit_id')))
                elif path == "/api/atlas/search":
                    self._atlas_search(workspace, body)
                else:
                    self._error(404, "api_not_found", "Unknown research endpoint.")
            except WorkflowError as exc:
                self._error(exc.status, exc.code, str(exc))
            except (ValueError, TypeError, KeyError):
                self._error(400, "invalid_request", "Malformed or incomplete research request.")
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                self._error(500, "workspace_error", "The action could not be saved. Reload the workspace to check its current state.")

        def _transcribe_audio(self):
            from .voice import AUDIO_TYPES, MAX_AUDIO_BYTES, VoiceError
            try:
                content_type = self.headers.get('Content-Type', '').split(';')[0].lower()
                if content_type not in AUDIO_TYPES:
                    raise VoiceError('Use a supported audio recording format.', 415)
                if self.headers.get('Transfer-Encoding'):
                    raise VoiceError('Chunked uploads are not supported.')
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    raise VoiceError('Invalid audio size.')
                if not 0 < size <= MAX_AUDIO_BYTES:
                    raise VoiceError('The recording must contain 1 byte to 4 MB.', 413)
                self.connection.settimeout(20)
                payload = self.rfile.read(size)
                if len(payload) != size:
                    raise VoiceError('The recording upload was incomplete.')
                self._json(200, transcriber.transcribe(payload, content_type))
            except VoiceError as exc:
                self._error(exc.status, exc.code, str(exc))
            except (BrokenPipeError, ConnectionResetError):
                return
            except TimeoutError:
                self._error(408, 'upload_timeout', 'The recording upload timed out. Try again.')
            except Exception:
                self._error(500, 'transcription_failed', 'The recording could not be transcribed. Try again.')

        def _resolved_api(self, path, query):
            if resolved is None:
                self._error(404, 'resolved_unavailable', 'Build the neuro identity layer with atlas resolve-neuro.')
                return
            def integer(name, default, low, high):
                value = self._one(query, name)
                value = int(value) if value is not None else default
                if not low <= value <= high: raise ValueError(f'{name} is outside the supported range.')
                return value
            try:
                if any(len(values) != 1 for values in query.values()):
                    raise ValueError('Query parameters must occur once.')
                route = path.removeprefix('/api/resolved/')
                if route == 'status': result = resolved.status()
                elif route == 'graph': result = resolved.graph(limit=integer('limit',120,2,1000), offset=integer('offset',0,0,10**10), focus=self._one(query,'focus'))
                elif route == 'search': result = resolved.search(self._one(query,'q') or '', limit=integer('limit',40,1,100))
                elif route in ('node','claim'):
                    identifier = self._one(query,'id')
                    if not identifier: raise ValueError('Supply one identifier.')
                    result = resolved.node(identifier) if route == 'node' else resolved.claim(identifier)
                    if result is None: raise KeyError(identifier)
                else:
                    self._error(404,'api_not_found','Unknown resolved graph endpoint.'); return
                self._json(200,result)
            except KeyError:
                self._error(404,'entity_not_found','That entity or claim is outside the resolved neuro layer.')
            except (ValueError,TypeError) as exc:
                self._error(400,'invalid_graph_request',str(exc)[:300])

        def _harvest_api(self, path, query):
            if harvest is None:
                self._error(404, "harvest_unavailable", "Build the harvested graph with atlas build-graph before opening the full source graph.")
                return
            def integer(name, default, low, high):
                value = self._one(query, name)
                value = int(value) if value is not None else default
                if not low <= value <= high: raise ValueError(f"{name} is outside the supported range.")
                return value
            try:
                route = path.removeprefix('/api/harvest/')
                if route == 'status': result = harvest.status()
                elif route == 'graph': result = harvest.graph(limit=integer('limit',3000,100,10000), offset=integer('offset',0,0,10**10), focus=self._one(query,'focus'))
                elif route == 'search': result = harvest.search(self._one(query,'q') or '', limit=integer('limit',40,1,100))
                elif route == 'datasets': result = harvest.datasets()
                elif route == 'records': result = harvest.records(integer('dataset',0,1,100000), page=integer('page',0,0,10**10), limit=integer('limit',50,1,200))
                elif route in ('node','claim','record'):
                    identifier = self._one(query,'id')
                    if not identifier: raise ValueError('Supply one record identifier.')
                    if route == 'node': result = harvest.node(identifier)
                    elif route == 'claim': result = harvest.claim(identifier)
                    else:
                        prefix, did, row = identifier.split(':')
                        if prefix != 'record': raise ValueError('Invalid record identifier.')
                        result = harvest.record(int(did),int(row))
                    if result is None: raise KeyError(identifier)
                    # Store methods expose immutable source pointers; resolve raw
                    # metadata only on inspection, never into a giant graph response.
                    pointer = result.get('provenance', result.get('record'))
                    if route == 'record': pointer = result
                    if isinstance(pointer,dict) and pointer.get('path'):
                        from .harvest_graph.source_reader import read_record
                        result = {**result,'record':read_record(harvest.path,harvest.source_root,pointer)}
                else:
                    self._error(404,'api_not_found','Unknown harvested graph endpoint.'); return
                self._json(200,result)
            except KeyError:
                self._error(404,'record_not_found','That entity or source record is not present in the imported graph.')
            except (ValueError,TypeError) as exc:
                self._error(400,'invalid_graph_request',str(exc)[:300])

        def _atlas_search(self, target_workspace, body: dict) -> None:
            query = body.get("q")
            top_k = body.get("top_k", 8)
            if not isinstance(query, str) or not query.strip() or len(query) > 1000:
                self._error(400, "invalid_query", "Search text must contain 1–1000 characters.")
                return
            if type(top_k) is not int or not 1 <= top_k <= 20:
                self._error(400, "invalid_limit", "top_k must be an integer from 1 to 20.")
                return
            catalog = getattr(target_workspace, "catalog", None)
            if catalog is None:
                self._error(503, "catalog_unavailable", "The live literature catalog is not configured.")
                return
            try:
                result = catalog.search(query.strip(), top_k=top_k)
            except ValueError as exc:
                self._error(400, "catalog_search_failed", str(exc)[:300] or "The literature search could not be completed.")
                return
            except Exception:
                self._error(502, "catalog_search_failed", "The literature search could not be completed.")
                return
            if isinstance(result, dict):
                payload = {"query": query.strip(), "hits": result.get("hits", []),
                           "provider": result.get("provider", getattr(catalog, "provider", "catalog")),
                           "scopes": result.get("scopes", [])}
            elif isinstance(result, list):
                payload = {"query": query.strip(), "hits": result,
                           "provider": getattr(catalog, "provider", "catalog"), "scopes": []}
            else:
                self._error(502, "catalog_search_failed", "The literature catalog returned an invalid result.")
                return
            self._json(200, payload)

        def do_PUT(self) -> None:  # noqa: N802
            self._error(405, "method_not_allowed", "This atlas is read-only.")

        def do_DELETE(self) -> None:  # noqa: N802
            self._error(405, "method_not_allowed", "This atlas is read-only.")

    return ThreadingHTTPServer((host, port), AtlasHandler)


def serve(store: Any, host: str = "127.0.0.1", port: int = 8765, *, workspace=None, harvest=None, resolved=None) -> None:
    """Run the atlas server until interrupted."""
    server = create_server(store, host, port, workspace=workspace, harvest=harvest, resolved=resolved)
    try:
        server.serve_forever()
    finally:
        server.server_close()
