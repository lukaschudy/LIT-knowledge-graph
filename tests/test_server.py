"""HTTP surface tests against the validated synthetic acceptance fixture."""

import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from atlas.server import create_server
from atlas.store import GraphStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "fixtures" / "atlas-demo.json"


class AtlasServerTests(unittest.TestCase):
    def setUp(self):
        self.store = GraphStore()
        self.store.load_bundle(json.loads(FIXTURE.read_text(encoding="utf-8")))
        self.server = create_server(self.store, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.store.close()

    def get_json(self, path):
        with urlopen(self.base + path, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_and_stats_report_the_fixture_as_synthetic(self):
        status, health = self.get_json("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["synthetic"])
        self.assertEqual(health["dataset"]["id"], "demo:atlas-v1")

        _, stats = self.get_json("/api/stats")
        self.assertEqual(stats["stats"]["nodes"], len(self.store.bundle()["nodes"]))

    def test_search_prioritizes_exact_alias_over_substring(self):
        _, result = self.get_json("/api/search?q=Aurora")
        self.assertEqual(result["results"][0]["id"], "demo:disease-a")
        self.assertEqual(result["total"], 2)

    def test_claim_returns_support_counterevidence_and_source_rows(self):
        _, result = self.get_json("/api/claim?id=demo:claim-f-effect")
        self.assertEqual(result["claim"]["context"]["effect"], "loss_of_function")
        self.assertEqual(len(result["support"]), 1)
        self.assertEqual(result["support"][0]["stance"], "supports")
        self.assertEqual(len(result["contradictions"]), 1)
        self.assertEqual(result["contradictions"][0]["stance"], "contradicts")
        self.assertEqual({row["id"] for row in result["sources"]}, {"demo:source-mechanisms", "demo:source-conflict"})

    def test_explore_surfaces_the_no_route_case(self):
        _, result = self.get_json("/api/explore?disease=demo%3Adisease-d")
        self.assertEqual(result["status"], "no_supported_route")
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["disease"]["label"], "Delta syndrome")
        self.assertTrue(result["next_questions"])

    def test_only_explicit_web_assets_are_served(self):
        with urlopen(self.base + "/") as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertIn(b"connected-biology.png", response.read())
        with urlopen(self.base + "/explore") as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"/graph-renderer.js", response.read())
        for asset in ("/app.js", "/graph-renderer.js"):
            with urlopen(self.base + asset) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("javascript", response.headers["Content-Type"])
        for name in ("instrument-sans-latin-wght-normal.woff2", "ibm-plex-sans-latin-wght-normal.woff2", "ibm-plex-mono-latin-400-normal.woff2"):
            with urlopen(self.base + "/fonts/" + name) as response:
                self.assertEqual(response.headers["Content-Type"], "font/woff2")
                self.assertEqual(response.read(4), b"wOF2")
        with urlopen(self.base + "/images/connected-biology.png") as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.read(8), b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/../README.md", timeout=2)
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

    def test_invalid_disease_has_a_safe_json_error(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/api/explore?disease=missing", timeout=2)
        self.assertEqual(caught.exception.code, 404)
        with caught.exception as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "disease_not_found")
        self.assertNotIn("traceback", json.dumps(payload).lower())


if __name__ == "__main__":
    unittest.main()
