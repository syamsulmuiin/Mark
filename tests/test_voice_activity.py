"""Speech classification uses legal PCM frames independently of packet boundaries."""
import struct
import pytest
from core.voice_activity import VoiceActivity
from core.speech_onset import SpeechOnset


class Detector:
    def __init__(self, speech=True):
        self.calls = []
        self.speech = speech

    def is_speech(self, pcm, sample_rate):
        assert len(pcm) == sample_rate * 2 // 50
        self.calls.append(pcm)
        return self.speech


def test_packet_boundaries_do_not_lose_or_duplicate_pcm():
    detector = Detector()
    activity = VoiceActivity(detector=detector)
    data = bytes(range(256)) * 10
    frames = []
    for start in range(0, len(data), 128):
        frames += activity.feed({'data': data[start:start + 128], '_source_device_id': 'phone'})
    assert b''.join(frame['data'] for frame, _ in frames) == data
    assert all(voiced and frame['_source_device_id'] == 'phone' for frame, voiced in frames)
    assert len(frames) == 4
    assert activity.buffer == b''


def test_reset_cannot_mix_partial_samples_from_two_sources():
    activity = VoiceActivity(detector=Detector())
    assert activity.feed({'data': b'\1\0' * 100}) == []
    activity.reset()
    frames = activity.feed({'data': b'\2\0' * 320})
    assert frames[0][0]['data'] == b'\2\0' * 320


def test_malformed_pcm_is_rejected_and_partial_buffer_cleared():
    activity = VoiceActivity(detector=Detector())
    activity.feed({'data': b'\0\0'})
    with pytest.raises(ValueError):
        activity.feed({'data': b'\1'})
    assert activity.buffer == b''


def test_above_threshold_non_speech_cannot_open_activity():
    activity = VoiceActivity(detector=Detector(speech=False))
    onset = SpeechOnset()
    for _ in range(30):
        for frame, voiced in activity.feed({'data': struct.pack('<h', 1223) * 320}):
            assert onset.feed(frame, 1223 if voiced else 0) == []


def test_real_vad_rejects_silence_and_stationary_dc_before_onset():
    activity = VoiceActivity()
    onset = SpeechOnset()
    for value in [0, 405, 1223]:
        activity.reset()
        onset.reset()
        for _ in range(30):
            for frame, voiced in activity.feed({'data': struct.pack('<h', value) * 320}):
                assert onset.feed(frame, value if voiced else 0) == []


def test_missing_detector_dependency_fails_clearly_without_energy_fallback(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'webrtcvad', None)
    with pytest.raises(RuntimeError, match='pip install -r requirements.txt'):
        VoiceActivity()
