import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas.ai import ModelClient, ModelError, _extraction_schema, _validate_output, extract_source


class ModelClientTests(unittest.TestCase):
    def test_openai_responses_structured_output(self):
        body = {"model": "gpt-6-astra", "usage": {"input_tokens": 3}, "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}]}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps(body).encode()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch("atlas.ai.urllib.request.urlopen", return_value=Response()) as call:
            result = ModelClient("openai").generate_json("hello", {"type": "object"}, "test")
        self.assertEqual(result["data"], {"ok": True})
        self.assertEqual(result["metadata"]["mode"], "live")
        self.assertIn("Bearer test-key", str(call.call_args.args[0].headers))
        request_body = json.loads(call.call_args.args[0].data)
        self.assertFalse(request_body["store"])
        self.assertEqual(request_body["max_output_tokens"], 8192)

    def test_refusal_incomplete_and_failed_responses_are_errors(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "x"}):
            scenarios = [
                ({"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}, "refusal"),
                ({"status": "incomplete", "output": []}, "truncated"),
                ({"status": "failed", "output": []}, "provider_error"),
            ]
            for response_body, expected_code in scenarios:
                with self.subTest(expected_code=expected_code), patch("atlas.ai.urllib.request.urlopen") as call:
                    class R:
                        def __enter__(self): return self
                        def __exit__(self, *args): pass
                        def read(self): return json.dumps(response_body).encode()
                    call.return_value = R()
                    with self.assertRaises(ModelError) as caught:
                        ModelClient("openai").generate_json("p", {}, "n")
                    self.assertEqual(caught.exception.code, expected_code)
                    self.assertEqual(caught.exception.metadata["mode"], "live")

    def test_codex_exec_isolated_read_only_stdin_with_tools_disabled(self):
        client = ModelClient("codex", model="gpt-6-astra", timeout=11)
        prompt = "Untrusted source text supplied as JSON."
        schema = {"type": "object", "required": ["ok"], "additionalProperties": False,
                  "properties": {"ok": {"type": "boolean"}}}
        def fake_run(command, **kwargs):
            self.assertEqual(command[0:2], ["/usr/bin/codex", "exec"])
            self.assertIn("--ephemeral", command)
            self.assertIn("--ignore-user-config", command)
            self.assertIn("--ignore-rules", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertIn("features.shell_tool=false", command)
            self.assertIn('web_search="disabled"', command)
            self.assertIn("features.apps=false", command)
            self.assertIn("features.multi_agent=false", command)
            self.assertIn('approval_policy="never"', command)
            self.assertEqual(command[-1], "-")
            schema_path = Path(command[command.index("--output-schema") + 1])
            self.assertEqual(json.loads(schema_path.read_text()), schema)
            temp_cwd = kwargs["cwd"]
            self.assertEqual(command[command.index("--cd") + 1], temp_cwd)
            self.assertTrue(temp_cwd.startswith(os.path.abspath(os.getenv("TMPDIR", "/tmp"))))
            self.assertEqual(kwargs["timeout"], 11)
            self.assertFalse(kwargs["shell"])
            self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
            self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
            self.assertIn(prompt.encode("utf-8"), kwargs["input"])
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text('{"ok":true}')
            return subprocess.CompletedProcess(command, 0)

        with patch("atlas.ai.shutil.which", return_value="/usr/bin/codex"), patch("atlas.ai.subprocess.run", side_effect=fake_run):
            with patch.object(client, "_provider", return_value="codex"):
                result = client.generate_json(prompt, schema, "test")
        self.assertEqual(result["data"], {"ok": True})
        self.assertEqual(result["metadata"]["provider"], "codex")

    def test_codex_timeout_fails_closed(self):
        client = ModelClient("codex", timeout=1)
        with patch("atlas.ai.shutil.which", return_value="/usr/bin/codex"), patch(
            "atlas.ai.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 1)
        ), patch.object(client, "_provider", return_value="codex"):
            with self.assertRaises(ModelError) as caught:
                client.generate_json("prompt", {"type": "object"}, "test")
        self.assertEqual(caught.exception.code, "timeout")
        self.assertEqual(caught.exception.metadata["provider"], "codex")
        self.assertEqual(caught.exception.metadata["mode"], "live")

    def test_codex_output_schema_mismatch_is_rejected(self):
        client = ModelClient("codex")
        schema = {"type": "object", "required": ["ok"], "additionalProperties": False,
                  "properties": {"ok": {"type": "boolean"}}}
        def fake_run(command, **kwargs):
            Path(command[command.index("--output-last-message") + 1]).write_text('{"wrong":true}')
            return subprocess.CompletedProcess(command, 0)
        with patch("atlas.ai.shutil.which", return_value="/usr/bin/codex"), patch("atlas.ai.subprocess.run", side_effect=fake_run), patch.object(client, "_provider", return_value="codex"):
            with self.assertRaises(ModelError) as caught:
                client.generate_json("prompt", schema, "test")
        self.assertEqual(caught.exception.code, "invalid_response")

    def test_missing_backend_does_not_fake_live_output(self):
        with patch.dict(os.environ, {}, clear=True), patch("atlas.ai.shutil.which", return_value=None):
            with self.assertRaises(ModelError) as caught: ModelClient().generate_json("p", {}, "n")
            self.assertEqual(caught.exception.code, "not_configured")
            self.assertFalse(ModelClient("openai").status()["available"])

    def test_codex_status_requires_documented_login_command(self):
        with patch("atlas.ai.shutil.which", return_value="/usr/bin/codex"), patch("atlas.ai.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b""
            run.return_value.stderr = b"Logged in using ChatGPT\n"
            self.assertTrue(ModelClient("codex").status()["available"])
            run.return_value.stderr = b"Not logged in\n"
            self.assertFalse(ModelClient("codex").status()["available"])

    def test_structured_output_is_checked_against_schema(self):
        with self.assertRaises(ModelError):
            _validate_output({"unexpected": True}, {"type": "object", "additionalProperties": False, "properties": {}})


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.loads((Path(__file__).parents[1] / "data/fixtures/atlas-demo.json").read_text())
        self.text = "Fictional Aurora involves transport."
        self.proposal = {"subject": "demo:disease-a", "predicate": "INVOLVES", "object": "demo:mechanism-transport",
            "assertion_type": "reported", "effect": None, "negated": False, "qualifiers": {"species": None,
            "tissue": None, "stage": None, "onset": None, "frequency": None, "evidence_code": None,
            "mechanism_step": None, "readout": None}, "excerpt": self.text}

    def test_grounded_claim_is_unreviewed_and_versioned(self):
        class Client:
            def generate_json(self, *args): return {"data": {"proposals": [self_outer.proposal]}, "metadata": {"provider": "mock", "mode": "mock"}}
        self_outer = self
        output = extract_source(self.bundle, "demo:source-mechanisms", self.text, Client())
        self.assertEqual(output["bundle"]["evidence"][-1]["review_status"], "unreviewed")
        self.assertEqual(output["bundle"]["evidence"][-1]["source_version"], __import__("hashlib").sha256(self.text.encode()).hexdigest())

    def test_ambiguous_quote_rejected(self):
        proposal = dict(self.proposal, excerpt="Aurora")
        class Client:
            def generate_json(self, *args): return {"data": {"proposals": [proposal]}, "metadata": {}}
        with self.assertRaises(ModelError) as caught:
            extract_source(self.bundle, "demo:source-mechanisms", "Aurora and Aurora", Client())
        self.assertEqual(caught.exception.code, "ambiguous_evidence")

    def test_schema_is_closed(self):
        self.assertFalse(_extraction_schema()["additionalProperties"])
