"""Bounded hosted dictation. Audio is processed transiently, never persisted by Atlas."""
import asyncio
import base64
import json

MODEL = '@cf/openai/whisper-large-v3-turbo'
MAX_AUDIO_BYTES = 4 * 1024 * 1024
CONTENT_TYPES = {'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/x-wav'}


class VoiceError(ValueError):
    def __init__(self, message, status=400, code='voice_rejected'):
        super().__init__(message)
        self.status, self.code = status, code


def _js(value):
    from js import JSON
    return JSON.parse(json.dumps(value))


def _python(value):
    return value.to_py() if hasattr(value, 'to_py') else value


def voice_status(env):
    available = bool(getattr(env, 'AI', None) and getattr(env, 'VOICE_LIMITER', None))
    return {'available': available, 'provider': 'cloudflare_workers_ai', 'model': MODEL,
            'requires_token': False, 'max_seconds': 60, 'max_bytes': MAX_AUDIO_BYTES,
            'message': 'Dictation via Cloudflare' if available else 'Dictation is temporarily unavailable.',
            'privacy': 'Audio is sent to Cloudflare for transcription. Atlas does not save recordings.'}


async def audio_body(request):
    length = request.headers.get('Content-Length')
    if length is not None:
        if not length or len(length) > 10 or not length.isascii() or not length.isdigit():
            raise VoiceError('Invalid recording length.')
        if int(length) > MAX_AUDIO_BYTES:
            raise VoiceError('Recording too large. Try a shorter question.', 413)
    data = bytearray()
    if request.body:
        reader = request.body.getReader()
        try:
            while True:
                chunk = await reader.read()
                if chunk.done:
                    break
                if len(data) + chunk.value.byteLength > MAX_AUDIO_BYTES:
                    await reader.cancel()
                    raise VoiceError('Recording too large. Try a shorter question.', 413)
                data.extend(chunk.value.to_bytes())
        finally:
            reader.releaseLock()
    if length is not None and len(data) != int(length):
        raise VoiceError('The recording was incomplete. Please try again.')
    if not data:
        raise VoiceError('No audio was recorded. Please try again.')
    return bytes(data)


async def transcribe(request, url, env):
    if request.headers.get('Origin') != f'{url.scheme}://{url.netloc}':
        raise VoiceError('Record from this Atlas site.', 403)
    content_type = (request.headers.get('Content-Type') or '').split(';')[0].strip().lower()
    if content_type not in CONTENT_TYPES:
        raise VoiceError('Use a supported microphone recording format.', 415)
    if not voice_status(env)['available']:
        raise VoiceError('Dictation is temporarily unavailable. You can still type your question.', 503, 'voice_unavailable')
    # Public demo has no user accounts. IP throttling bounds repeated anonymous
    # calls per Cloudflare location; this is not a global spending/accounting cap.
    allowed = _python(await env.VOICE_LIMITER.limit(_js({'key': 'atlas-voice:' + (request.headers.get('CF-Connecting-IP') or 'local')})))
    if not allowed.get('success'):
        raise VoiceError('Too many recordings. Wait a minute and try again.', 429, 'voice_busy')
    payload = await audio_body(request)
    try:
        result = _python(await asyncio.wait_for(env.AI.run(MODEL, _js({
            'audio': base64.b64encode(payload).decode('ascii'), 'task': 'transcribe',
            'language': 'en', 'vad_filter': True, 'condition_on_previous_text': False,
        })), timeout=90))
    except (asyncio.TimeoutError, TimeoutError):
        raise VoiceError('Transcription timed out. Please try a shorter recording.', 504, 'voice_timeout') from None
    except Exception:
        # Never return provider internals or audio content to the caller/logs.
        raise VoiceError('Transcription is temporarily unavailable. Please try again.', 503, 'voice_unavailable') from None
    if not isinstance(result, dict) or not isinstance(result.get('text'), str):
        raise VoiceError('Transcription returned no usable result. Please try again.', 502, 'voice_invalid_result')
    return {'text': result['text'].strip(), 'provider': 'cloudflare_workers_ai', 'model': MODEL}
