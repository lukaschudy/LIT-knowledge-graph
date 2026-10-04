"""Local-only search inspection UI. API keys stay in the Python process."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .topk import checked_bundle, client_from_settings, graph_connections, search, settings, DEFAULT_REGION


def serve(config, state, bundle, port):
    client = client_from_settings(config)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Research queries are not written to access logs.

        def respond(self, status, payload, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            # Restrict browser access to this loopback origin, including DNS rebinding.
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                self.respond(403, b'Forbidden host', 'text/plain')
                return
            path = urlsplit(self.path)
            if path.path == "/":
                self.respond(200, Path(__file__).with_name("web.html").read_bytes(), "text/html; charset=utf-8")
                return
            if path.path == "/api/status":
                result = {"collection": state["collection"], "snapshot_id": state["snapshot_id"],
                          "documents": state.get("verified_documents", state["acknowledged_documents"]),
                          "status": state["status"]}
            elif path.path == "/api/search":
                params = parse_qs(path.query)
                def param(k, default=None): return params.get(k, [default])[0]
                query = param("q", "")
                if len(query) > 2000:
                    self.respond(400, b'{"error":"Query too long"}', "application/json")
                    return
                try:
                    result = search(client, state["collection"], query, state["snapshot_id"],
                                    mode=param("mode", "hybrid"), kind=param("kind"), k=10,
                                    lsn=state.get("last_lsn"))
                    result["connections"] = graph_connections(result["hits"], bundle)
                except ValueError:
                    self.respond(400, b'{"error":"Invalid search query or filters"}', "application/json")
                    return
                except Exception:
                    self.respond(502, b'{"error":"TopK query failed; retry or check server configuration"}', "application/json")
                    return
            else:
                self.respond(404, b'Not found', 'text/plain')
                return
            self.respond(200, json.dumps(result).encode(), "application/json; charset=utf-8")
    print(f"GRIN search: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=Path("data/curated/grin_atlas_bundle.json"))
    parser.add_argument("--port", type=int, default=18767)
    args = parser.parse_args()
    state = json.loads(args.checkpoint.read_text())
    if state["status"] != "verified":
        raise ValueError("Search demo requires a verified ingestion checkpoint")
    config = settings(args.env_file)
    if (config.get("TOPK_REGION") or DEFAULT_REGION) != state["region"]:
        raise ValueError("Configured region does not match checkpoint")
    serve(config, state, checked_bundle(args.bundle, state), args.port)


if __name__ == "__main__":
    main()
