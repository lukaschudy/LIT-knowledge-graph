"""Read-only HTTP server for the local synthetic research atlas."""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .http_api import AtlasAPI


WEB_DIR = Path(__file__).with_name("web")
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/explore": ("explore.html", "text/html; charset=utf-8"),
    "/records": ("records.html", "text/html; charset=utf-8"),
    "/graph.css": ("graph.css", "text/css; charset=utf-8"),
    "/graph.js": ("graph.js", "text/javascript; charset=utf-8"),
    "/cover.css": ("cover.css", "text/css; charset=utf-8"),
    "/transition.css": ("transition.css", "text/css; charset=utf-8"),
    "/transition.js": ("transition.js", "text/javascript; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/fonts/instrument-sans-latin-wght-normal.woff2": ("fonts/instrument-sans-latin-wght-normal.woff2", "font/woff2"),
    "/images/connected-biology.png": ("images/connected-biology.png", "image/png"),
    "/fonts/ibm-plex-sans-latin-wght-normal.woff2": ("fonts/ibm-plex-sans-latin-wght-normal.woff2", "font/woff2"),
    "/fonts/ibm-plex-mono-latin-400-normal.woff2": ("fonts/ibm-plex-mono-latin-400-normal.woff2", "font/woff2"),
}


def create_server(store: Any, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    """Create a testable threaded server around a startup snapshot of ``store``.

    The store and reasoner are only touched on this calling thread. Requests are
    served from the immutable bundle snapshot, which also keeps SQLite-backed
    stores safe from cross-thread connection use.
    """
    api = AtlasAPI(store.bundle(), store.stats())

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

        def _api(self, path: str, query: dict[str, list[str]]) -> None:
            status, payload = api.request(path, query)
            self._json(status, payload)

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
