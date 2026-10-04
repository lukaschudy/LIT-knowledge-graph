import asyncio
import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

from atlas import cloud_voice as voice
from tests.test_worker import request, Chunk


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = SimpleNamespace(AI=SimpleNamespace(run=AsyncMock(return_value={'text': ' GRIN2B evidence? '})),
                                   VOICE_LIMITER=SimpleNamespace(limit=AsyncMock(return_value={'success': True})))
        self.convert = patch.object(voice, '_js', lambda value: value)
        self.convert.start()
        self.addCleanup(self.convert.stop)
        self.url = urlsplit('https://atlas.example/api/voice/transcribe')

    def recording(self, **changes):
        options = {'method': 'POST', 'body': b'recorded audio',
                   'headers': {'Origin': 'https://atlas.example', 'Content-Type': 'audio/webm;codecs=opus'}}
        options.update(changes)
        return request('/api/voice/transcribe', **options)

    async def test_hosted_audio_to_transcript_without_local_token(self):
        result = await voice.transcribe(self.recording(), self.url, self.env)
        self.assertEqual(result['text'], 'GRIN2B evidence?')
        model, options = self.env.AI.run.call_args.args
        self.assertEqual(model, voice.MODEL)
        self.assertEqual(base64.b64decode(options['audio']), b'recorded audio')
        self.assertTrue(options['vad_filter'])
        self.assertFalse(voice.voice_status(self.env)['requires_token'])

    async def test_cross_origin_and_wrong_format_never_call_model(self):
        for headers, status in [({'Origin': 'https://outside.example', 'Content-Type': 'audio/webm'}, 403),
                                ({'Origin': 'https://atlas.example', 'Content-Type': 'text/plain'}, 415)]:
            with self.assertRaises(voice.VoiceError) as caught:
                await voice.transcribe(self.recording(headers=headers), self.url, self.env)
            self.assertEqual(caught.exception.status, status)
        self.env.AI.run.assert_not_called()

    async def test_size_limited_before_copying_large_chunk(self):
        chunk = Chunk(b'1' * (voice.MAX_AUDIO_BYTES + 1))
        req = self.recording(chunks=[chunk])
        with self.assertRaises(voice.VoiceError) as caught:
            await voice.transcribe(req, self.url, self.env)
        self.assertEqual(caught.exception.status, 413)
        self.assertTrue(req.body.cancelled)
        self.assertTrue(req.body.released)
        self.assertFalse(chunk.converted)
        self.env.AI.run.assert_not_called()

    async def test_empty_malformed_length_and_incomplete_bodies(self):
        for body, length in [(b'', '0'), (b'abc', '5'), (b'abc', '-1'), (b'abc', str(voice.MAX_AUDIO_BYTES + 1))]:
            req = self.recording(body=body, headers={'Origin': 'https://atlas.example',
                'Content-Type': 'audio/wav', 'Content-Length': length})
            with self.assertRaises(voice.VoiceError):
                await voice.transcribe(req, self.url, self.env)
        self.env.AI.run.assert_not_called()

    async def test_rate_limit_and_missing_binding(self):
        self.env.VOICE_LIMITER.limit.return_value = {'success': False}
        with self.assertRaises(voice.VoiceError) as caught:
            await voice.transcribe(self.recording(), self.url, self.env)
        self.assertEqual(caught.exception.status, 429)
        self.env.AI.run.assert_not_called()
        self.assertFalse(voice.voice_status(SimpleNamespace())['available'])
        with self.assertRaises(voice.VoiceError) as caught:
            await voice.transcribe(self.recording(), self.url, SimpleNamespace())
        self.assertEqual(caught.exception.status, 503)

    async def test_silence_is_empty_not_a_generated_answer(self):
        self.env.AI.run.return_value = {'text': '   '}
        result = await voice.transcribe(self.recording(), self.url, self.env)
        self.assertEqual(result['text'], '')

    async def test_invalid_result_and_provider_errors_are_safe(self):
        self.env.AI.run.return_value = {'text': None}
        with self.assertRaises(voice.VoiceError) as caught:
            await voice.transcribe(self.recording(), self.url, self.env)
        self.assertEqual(caught.exception.status, 502)
        for exception, expected in [(RuntimeError('private provider internals'), 503), (asyncio.TimeoutError(), 504)]:
            self.env.AI.run.side_effect = exception
            with self.assertRaises(voice.VoiceError) as caught:
                await voice.transcribe(self.recording(), self.url, self.env)
            self.assertEqual(caught.exception.status, expected)
            self.assertNotIn('private', str(caught.exception))
