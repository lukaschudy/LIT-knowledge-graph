"""Bounded local dictation. Audio exists in memory only and never goes to a cloud API."""
from __future__ import annotations

import importlib.util
import io
import os
import threading

MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_AUDIO_SECONDS = 61  # one second of container/recorder rounding tolerance
AUDIO_TYPES = {'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/x-wav'}


class VoiceError(Exception):
    def __init__(self, message, status=400, code='invalid_audio'):
        super().__init__(message)
        self.status, self.code = status, code


def decode_bounded_audio(payload):
    """Decode incrementally so compressed inputs cannot expand into hours of PCM."""
    import av
    import numpy as np
    chunks, samples = [], 0
    try:
        with av.open(io.BytesIO(payload)) as container:
            if not container.streams.audio:
                raise VoiceError('No audio track was found. Record your question again.')
            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
            for frame in container.decode(audio=0):
                for part in resampler.resample(frame):
                    samples += part.samples
                    if samples > MAX_AUDIO_SECONDS * 16000:
                        raise VoiceError('Recordings must be no longer than 60 seconds.', 413)
                    chunks.append(part.to_ndarray().reshape(-1))
            for part in resampler.resample(None):
                samples += part.samples
                if samples > MAX_AUDIO_SECONDS * 16000:
                    raise VoiceError('Recordings must be no longer than 60 seconds.', 413)
                chunks.append(part.to_ndarray().reshape(-1))
    except VoiceError:
        raise
    except Exception as exc:
        raise VoiceError('The recording could not be decoded. Try recording again.') from exc
    if samples < 1600:
        raise VoiceError('The recording was too short. Try speaking for a little longer.')
    return np.concatenate(chunks).astype(np.float32) / 32768.0


class LocalTranscriber:
    def __init__(self):
        self.model_name = os.environ.get('ATLAS_VOICE_MODEL', 'small.en')
        self._model = None
        self._lock = threading.Lock()

    def status(self):
        available = importlib.util.find_spec('faster_whisper') is not None
        return {'available': available, 'provider': 'local_whisper', 'model': self.model_name,
                'ready': self._model is not None, 'max_seconds': 60,
                'message': 'Audio is transcribed on this computer and is not saved.' if available
                else 'Local voice is not installed. Install the voice extra to enable dictation.'}

    def transcribe(self, payload, content_type):
        if content_type not in AUDIO_TYPES:
            raise VoiceError('Unsupported recording format.', 415)
        if not 0 < len(payload) <= MAX_AUDIO_BYTES:
            raise VoiceError('The recording is empty or exceeds 4 MB.', 413)
        if not self.status()['available']:
            raise VoiceError(self.status()['message'], 503, 'voice_unavailable')
        if not self._lock.acquire(blocking=False):
            raise VoiceError('Another recording is being transcribed. Try again shortly.', 429, 'voice_busy')
        try:
            audio = decode_bounded_audio(payload)
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                    self._model = WhisperModel(self.model_name, device='cpu', compute_type='int8', cpu_threads=4)
                except Exception as exc:
                    raise VoiceError('The local speech model could not load. Check the model installation and retry.', 503, 'voice_unavailable') from exc
            try:
                segments, _ = self._model.transcribe(audio, language='en', beam_size=3,
                    vad_filter=True, condition_on_previous_text=False)
                text = ' '.join(segment.text.strip() for segment in segments).strip()
            except Exception as exc:
                raise VoiceError('Transcription failed. Try recording again.', 502, 'transcription_failed') from exc
            return {'text': text, 'provider': 'local_whisper', 'model': self.model_name,
                    'duration_seconds': round(len(audio) / 16000, 2)}
        finally:
            self._lock.release()
