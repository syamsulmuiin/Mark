from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
ANDROID = (ROOT / "android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt").read_text(encoding="utf-8")


def test_android_does_not_interrupt_from_audio_level_only():
    assert 'interruptLevelThreshold' not in ANDROID
    assert 'interruptFrameCount' not in ANDROID
    assert 'put("type","jarvis.interrupt")' not in ANDROID
    assert 'ws?.send(ByteString.of(*buf.copyOf(n)))' in ANDROID


def test_semantic_classifier_is_multilingual_and_fail_closed():
    block = MAIN.split('async def _classify_barge_in', 1)[1].split('async def _relay_phone_audio', 1)[0]
    assert 'ANY human language' in block
    assert 'When uncertain return IGNORE' in block
    assert 'verdict == "INTERRUPT"' in block
    assert 'barge_semantic_decision' in block


def test_accepted_barge_replays_original_audio_to_live():
    block = MAIN.split('async def _classify_barge_in', 1)[1].split('async def _relay_phone_audio', 1)[0]
    assert 'self.interrupt()' in block
    assert 'await self.out_queue.put({"activity_start": True})' in block
    assert 'pcm[i:i + CHUNK_SIZE]' in block
    assert 'await self.out_queue.put({"activity_end": True})' in block


def test_speaking_path_does_not_send_empty_activity_boundaries():
    block = MAIN.split('async def _relay_phone_audio', 1)[1].split('\n    async def ', 1)[0]
    speaking = block.split('if speaking:', 1)[1].split('# Normal listening path.', 1)[0]
    assert 'activity_start' not in speaking
    assert 'activity_end' not in speaking
    assert '_barge_audio.extend' in speaking


def test_semantic_barge_audio_is_bounded_and_not_logged():
    assert 'self._barge_max_bytes = SEND_SAMPLE_RATE * 2 * 8' in MAIN
    block = MAIN.split('async def _classify_barge_in', 1)[1].split('async def _relay_phone_audio', 1)[0]
    assert '_trace_event("barge_semantic_decision", accepted=accepted)' in block
    assert '_trace_event("barge_semantic_unavailable", error=type(exc).__name__)' in block
    assert 'pcm=' not in block
