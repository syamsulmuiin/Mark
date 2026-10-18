"""Debounce PCM activity without invoking another model or losing speech onset."""


class SpeechOnset:
    def __init__(self, threshold=250.0, minimum_ms=160, sample_rate=16000):
        self.threshold = threshold
        self.minimum_bytes = int(sample_rate * 2 * minimum_ms / 1000)
        self.reset()

    def reset(self):
        self.frames = []
        self.size = 0

    def feed(self, chunk, rms):
        if rms < self.threshold:
            self.reset()
            return []
        self.frames.append(chunk)
        self.size += len(chunk.get("data", b""))
        if self.size < self.minimum_bytes:
            return []
        frames = self.frames
        self.reset()
        return frames
