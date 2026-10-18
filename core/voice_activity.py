"""Local WebRTC speech detection on complete 20 ms PCM16 frames, no LLM/API."""
from __future__ import annotations


class VoiceActivity:
    def __init__(self, sample_rate=16000, detector=None):
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError('Unsupported VAD sample rate')
        self.sample_rate = sample_rate
        self.frame_bytes = sample_rate * 2 // 50
        self._factory = None
        if detector is None:
            try:
                import webrtcvad
            except ImportError as exc:
                raise RuntimeError('Speech detector missing. Install server requirements: python -m pip install -r requirements.txt') from exc
            self._factory = lambda: webrtcvad.Vad(2)
            detector = self._factory()
        self.detector = detector
        self.buffer = bytearray()

    def reset(self):
        self.buffer.clear()
        if self._factory is not None:
            self.detector = self._factory()

    def feed(self, chunk):
        raw = chunk.get('data', b'')
        if not isinstance(raw, bytes) or len(raw) % 2:
            self.reset()
            raise ValueError('Expected complete PCM16 samples')
        self.buffer.extend(raw)
        frames = []
        while len(self.buffer) >= self.frame_bytes:
            pcm = bytes(self.buffer[:self.frame_bytes])
            del self.buffer[:self.frame_bytes]
            voiced = self.detector.is_speech(pcm, self.sample_rate)
            frame = dict(chunk, data=pcm, mime_type=f'audio/pcm;rate={self.sample_rate}')
            frames.append((frame, voiced))
        return frames
