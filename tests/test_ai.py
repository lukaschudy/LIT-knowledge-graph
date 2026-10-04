import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas.ai import MAX_RESPONSE_BYTES, ModelClient, ModelError, _extraction_schema, _validate_output, extract_source


class ModelClientTests(unittest.TestCase):
    def test_malformed_provider_envelopes_are_safe_model_errors(self):
        for body in ({'output': None}, {'output': [None]},
                     {'output': [{'type': 'message', 'content': None}]},
                     {'output': [{'type': 'message', 'content': [None]}]},
                     {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': None}]}]}):
            with self.subTest(body=body), patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key'}), patch('atlas.ai._openai_http') as call:
                call.return_value = json.dumps(body).encode()
                with self.assertRaises(ModelError) as caught:
                    ModelClient('openai').generate_json('prompt', {}, 'test')
                self.assertEqual(caught.exception.code, 'invalid_response')
                self.assertEqual(caught.exception.metadata['provider'], 'openai')

    def test_provider_output_size_is_bounded(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key'}), patch('atlas.ai.subprocess.run') as call:
            call.return_value = subprocess.CompletedProcess([], 0, b'x' * (MAX_RESPONSE_BYTES + 1), b'')
            with self.assertRaises(ModelError) as caught:
                ModelClient('openai').generate_json('prompt', {}, 'test')
            self.assertEqual(caught.exception.code, 'invalid_response')

    def test_direct_socket_timeout_is_reported_as_timeout(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key'}), patch('atlas.ai.subprocess.run', side_effect=subprocess.TimeoutExpired('transport', 1)):
            with self.assertRaises(ModelError) as caught:
                ModelClient('openai').generate_json('prompt', {}, 'test')
            self.assertEqual(caught.exception.code, 'timeout')

    def test_slow_trickling_response_cannot_keep_a_model_job_alive(self):
        stopped = threading.Event()
        class SlowHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', '100000')
                self.end_headers()
                while not stopped.wait(.05):
                    try:
                        self.wfile.write(b' ')
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
        server = HTTPServer(('127.0.0.1', 0), SlowHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started = time.monotonic()
        try:
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key'}), patch(
                    'atlas.ai.RESPONSES_URL', f'http://127.0.0.1:{server.server_port}/responses'):
                with self.assertRaises(ModelError) as caught:
                    ModelClient('openai', timeout=1).generate_json('prompt', {}, 'test')
            self.assertEqual(caught.exception.code, 'timeout')
            self.assertLess(time.monotonic() - started, 2.5)
        finally:
            stopped.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_transport_deadline_covers_partial_status_headers_and_chunk_metadata(self):
        # HTTPResponse parses these before exposing a response/body chunk to us.
        for prefix in (b'HTTP/1.1 200 ', b'HTTP/1.1 200 OK\r\nX-Slow: ',
                       b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1;slow='):
            with self.subTest(prefix=prefix):
                stopped = threading.Event()
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *args): pass
                    def do_POST(self):
                        self.rfile.read(int(self.headers['Content-Length']))
                        try:
                            self.wfile.write(prefix)
                            self.wfile.flush()
                            while not stopped.wait(.05):
                                self.wfile.write(b'x')
                                self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                server = HTTPServer(('127.0.0.1', 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                processes = []
                original_popen = subprocess.Popen
                def record_process(*args, **kwargs):
                    process = original_popen(*args, **kwargs)
                    processes.append(process)
                    return process
                try:
                    started = time.monotonic()
                    with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key'}), patch(
                            'atlas.ai.RESPONSES_URL', f'http://127.0.0.1:{server.server_port}/responses'), patch(
                            'atlas.ai.subprocess.Popen', side_effect=record_process):
                        with self.assertRaises(ModelError) as caught:
                            ModelClient('openai', timeout=1).generate_json('prompt', {}, 'test')
                    self.assertEqual(caught.exception.code, 'timeout')
                    self.assertLess(time.monotonic() - started, 1.8)
                    self.assertEqual(len(processes), 1)
                    self.assertIsNotNone(processes[0].poll())
                    self.assertTrue(processes[0].stdout.closed)
                    self.assertTrue(processes[0].stderr.closed)
                finally:
                    stopped.set()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_real_transport_preserves_success_and_safe_provider_failures(self):
        response = {'model': 'fixture', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': '{"ok":true}'}]}]}
        for status, content, expected in ((200, json.dumps(response).encode(), None),
                                          (401, b'private provider details', 'authentication'),
                                          (429, b'private provider details', 'provider_error'),
                                          (200, b'not json', 'invalid_response'),
                                          (200, b'x' * 2048, 'invalid_response')):
            with self.subTest(status=status, expected=expected):
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *args): pass
                    def do_POST(self):
                        self.rfile.read(int(self.headers['Content-Length']))
                        self.send_response(status)
                        self.send_header('Content-Length', str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                server = HTTPServer(('127.0.0.1', 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key'}), patch(
                            'atlas.ai.RESPONSES_URL', f'http://127.0.0.1:{server.server_port}/responses'), patch(
                            'atlas.ai.MAX_RESPONSE_BYTES', 1024):
                        if expected:
                            with self.assertRaises(ModelError) as caught:
                                ModelClient('openai', timeout=2).generate_json('prompt', {}, 'test')
                            self.assertEqual(caught.exception.code, expected)
                            self.assertNotIn('private provider details', str(caught.exception))
                        else:
                            self.assertEqual(ModelClient('openai', timeout=2).generate_json('prompt', {}, 'test')['data'], {'ok': True})
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_transport_keeps_credentials_out_of_command_environment_and_diagnostics(self):
        def run(command, **kwargs):
            self.assertIn('-I', command)
            self.assertNotIn('fixture-secret', ' '.join(command))
            self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
            self.assertNotIn('UNRELATED_SECRET', kwargs['env'])
            self.assertEqual(kwargs['env']['SSL_CERT_FILE'], '/tmp/fixture-ca.pem')
            payload = json.loads(kwargs['input'])
            self.assertIn('Bearer fixture-secret', str(payload['headers']))
            self.assertEqual(payload['max_response_bytes'], MAX_RESPONSE_BYTES)
            self.assertEqual(kwargs['timeout'], 2)
            return subprocess.CompletedProcess(command, 2, b'', b'private diagnostic fixture-secret')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-secret', 'UNRELATED_SECRET': 'other',
                                     'SSL_CERT_FILE': '/tmp/fixture-ca.pem'}), patch('atlas.ai.subprocess.run', side_effect=run):
            with self.assertRaises(ModelError) as caught:
                ModelClient('openai', timeout=2).generate_json('prompt', {}, 'test')
        self.assertEqual(str(caught.exception), 'OpenAI request failed.')

    def test_nonfinite_numbers_cannot_pass_structured_output_validation(self):
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value), self.assertRaises(ModelError):
                _validate_output({'nested': [value]}, {'type': 'object'})

    def test_openai_responses_structured_output(self):
        body = {"model": "gpt-6-astra", "usage": {"input_tokens": 3}, "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch("atlas.ai._openai_http", return_value=json.dumps(body).encode()) as call:
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
                with self.subTest(expected_code=expected_code), patch("atlas.ai._openai_http") as call:
                    call.return_value = json.dumps(response_body).encode()
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

    def test_prefixed_source_hash_binding_survives_model_adapter(self):
        source = next(s for s in self.bundle['sources'] if s['id'] == 'demo:source-mechanisms')
        source['version'] = 'sha256:' + __import__('hashlib').sha256(self.text.encode()).hexdigest()
        proposal = self.proposal
        class Client:
            def generate_json(self, *args):
                return {'data': {'proposals': [proposal]}, 'metadata': {'provider': 'mock'}}
        output = extract_source(self.bundle, source['id'], self.text, Client())
        self.assertEqual(output['bundle']['evidence'][-1]['source_version'], source['version'])

    def test_ambiguous_quote_rejected(self):
        proposal = dict(self.proposal, excerpt="Aurora")
        class Client:
            def generate_json(self, *args): return {"data": {"proposals": [proposal]}, "metadata": {}}
        with self.assertRaises(ModelError) as caught:
            extract_source(self.bundle, "demo:source-mechanisms", "Aurora and Aurora", Client())
        self.assertEqual(caught.exception.code, "ambiguous_evidence")

    def test_schema_is_closed(self):
        self.assertFalse(_extraction_schema()["additionalProperties"])
