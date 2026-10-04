"""Local transcription boundaries; no downloads, microphones or model calls."""
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import wave

from atlas.server import create_server
from atlas.store import GraphStore
from atlas.voice import LocalTranscriber, VoiceError, MAX_AUDIO_BYTES, decode_bounded_audio

ROOT = Path(__file__).resolve().parents[1]


class VoiceAPITests(unittest.TestCase):
    def setUp(self):
        self.store = GraphStore()
        self.store.load_bundle(json.loads((ROOT/'data/fixtures/atlas-demo.json').read_text()))
        self.calls = []
        self.workspace = SimpleNamespace(token='test-voice-token')
        self.transcriber = SimpleNamespace(status=lambda:{'available':True}, transcribe=self.transcribe)
        self.server = create_server(self.store, port=0, workspace=self.workspace, transcriber=self.transcriber)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.store.close()

    def transcribe(self, body, kind):
        self.calls.append((body,kind))
        if body == b'invalid': raise VoiceError('Invalid recording.')
        return {'text':'What evidence supports this gene?'}

    def post(self, data=b'audio', **headers):
        return urlopen(Request(self.base+'/api/voice/transcribe', data=data, headers={
            'Content-Type':'audio/webm;codecs=opus','X-Atlas-Token':self.workspace.token,**headers}),timeout=3)

    def test_audio_routes_to_transcriber_and_returns_draft(self):
        self.assertTrue(json.load(urlopen(self.base+'/api/voice/status'))['available'])
        self.assertIn(b'MediaRecorder',urlopen(self.base+'/voice.js').read())
        self.assertEqual(json.load(self.post())['text'],'What evidence supports this gene?')
        self.assertEqual(self.calls,[(b'audio','audio/webm')])

    def test_rejects_untrusted_origin_missing_token_type_and_size(self):
        for headers,expected in [({'Origin':'https://untrusted.example'},403),({'X-Atlas-Token':''},403),
                                 ({'Content-Type':'application/json'},415),({'Content-Length':str(MAX_AUDIO_BYTES+1)},413),
                                 ({'Content-Length':'invalid'},400),({'Transfer-Encoding':'chunked'},400)]:
            with self.subTest(headers=headers),self.assertRaises(HTTPError) as error:self.post(**headers)
            self.assertEqual(error.exception.code,expected)
            error.exception.close()
        self.assertEqual(self.calls,[])

    def test_provider_error_is_structured(self):
        with self.assertRaises(HTTPError) as error:self.post(b'invalid')
        self.assertEqual(error.exception.code,400)
        self.assertEqual(json.load(error.exception)['error']['code'],'invalid_audio')


class LocalTranscriberTests(unittest.TestCase):
    def test_busy_rejected_without_decoding(self):
        voice=LocalTranscriber();voice._lock.acquire()
        with patch.object(voice,'status',return_value={'available':True}),self.assertRaises(VoiceError) as error:
            voice.transcribe(b'audio','audio/webm')
        self.assertEqual(error.exception.status,429)
        voice._lock.release()

    def test_unavailable_and_invalid_inputs(self):
        voice=LocalTranscriber()
        with patch.object(voice,'status',return_value={'available':False,'message':'Install voice'}):
            with self.assertRaises(VoiceError) as error:voice.transcribe(b'audio','audio/webm')
            self.assertEqual(error.exception.status,503)
        for payload,kind in [(b'', 'audio/wav'),(b'x'*(MAX_AUDIO_BYTES+1),'audio/wav'),(b'audio','text/plain')]:
            with self.assertRaises(VoiceError):voice.transcribe(payload,kind)

    def test_silence_and_failure_release_lock(self):
        voice=LocalTranscriber();voice._model=SimpleNamespace(transcribe=lambda *a,**k:(iter([]),None))
        with patch.object(voice,'status',return_value={'available':True}),patch('atlas.voice.decode_bounded_audio',return_value=[0]*16000):
            self.assertEqual(voice.transcribe(b'audio','audio/wav')['text'],'')
            def fail(*a,**k):raise RuntimeError('private internal detail')
            voice._model.transcribe=fail
            with self.assertRaises(VoiceError) as error:voice.transcribe(b'audio','audio/wav')
            self.assertNotIn('private',str(error.exception))
            self.assertFalse(voice._lock.locked())

    @unittest.skipUnless(__import__('importlib.util').util.find_spec('av'), 'optional voice extra not installed')
    def test_decoder_bounds_and_corrupt_audio(self):
        def wav(seconds):
            buf=io.BytesIO()
            with wave.open(buf,'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*(seconds*16000))
            return buf.getvalue()
        self.assertEqual(len(decode_bounded_audio(wav(1))),16000)
        for payload in [wav(62),b'invalid audio']:
            with self.assertRaises(VoiceError):decode_bounded_audio(payload)
