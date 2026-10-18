"""Debounce PCM activity without invoking another model or losing speech onset."""


class SpeechOnset:
    def __init__(self, threshold=250.0, minimum_ms=160, sample_rate=16000):
        self.threshold = threshold
        self.minimum_bytes = int(sample_rate * 2 * minimum_ms / 1000)
        self.playback_minimum_bytes = int(sample_rate * 2 * 320 / 1000)
        self.reset()

    def reset(self):
        self.frames = []
        self.size = 0

    def feed(self, chunk, rms, *, playback=False):
        # Platform AEC may be enabled yet leave low-level speaker residuals.
        threshold = max(self.threshold, 1000.0) if playback else self.threshold
        required = max(self.minimum_bytes, self.playback_minimum_bytes) if playback else self.minimum_bytes
        if getattr(self, '_playback', playback) != playback:
            self.reset()
        self._playback = playback
        if rms < threshold:
            self.reset()
            return []
        self.frames.append(chunk)
        self.size += len(chunk.get("data", b""))
        if self.size < required:
            return []
        frames = self.frames
        self.reset()
        return frames
