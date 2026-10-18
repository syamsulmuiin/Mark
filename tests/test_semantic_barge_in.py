"""Audio interruptions use the configured Live session, never a third model."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def test_speaking_time_pcm_reaches_the_existing_live_transport():
    tree = ast.parse((ROOT / 'main.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'JarvisLive')
    method = next(n for n in cls.body if getattr(n, 'name', '') == '_relay_phone_audio')
    namespace = {'asyncio': asyncio, 'np': np, 'time': time}
    module = ast.Module(body=[ast.ClassDef(name='Runtime', bases=[], keywords=[], body=[method], decorator_list=[])], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), 'relay', 'exec'), namespace)
    async def scenario():
        runtime = namespace['Runtime']()
        runtime._is_speaking = True
        runtime.ui = NS(muted=False)
        runtime._phone_activity_active = False
        runtime._phone_last_voice = 0
        runtime._dashboard = NS(_phone_audio_queue=asyncio.Queue())
        runtime.out_queue = asyncio.Queue(maxsize=10)
        pcm = np.full(1024, 1000, dtype='<i2').tobytes()
        await runtime._dashboard._phone_audio_queue.put({'data': pcm, 'mime_type': 'audio/pcm;rate=16000'})
        task = asyncio.create_task(runtime._relay_phone_audio())
        assert await asyncio.wait_for(runtime.out_queue.get(), 1) == {'activity_start': True}
        assert (await asyncio.wait_for(runtime.out_queue.get(), 1))['data'] == pcm
        assert await asyncio.wait_for(runtime.out_queue.get(), 2) == {'activity_end': True}
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    asyncio.run(scenario())


def test_no_auxiliary_classifier_or_live_session_in_server_or_companion():
    main = (ROOT / 'main.py').read_text()
    assert '_classify_barge_in' not in main
    assert 'auxiliary_model_request' not in main
    assert '_barge_audio' not in main
    gemini = (ROOT / 'core/gemini.py').read_text()
    assert 'aio.live.connect' not in gemini
    companion = (ROOT / 'desktop-companion/runtime/core/gemini.py').read_text()
    assert 'genai' not in companion and 'aio.live.connect' not in companion


def test_clients_handle_playback_clear_without_losing_microphone_input():
    android = (ROOT / 'android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt').read_text()
    desktop = (ROOT / 'desktop-companion/companion.py').read_text()
    assert '"audio.clear"->{ stopPlayback(); setVoiceState("LISTENING") }' in android
    assert "elif typ=='audio.clear':" in desktop
    assert 'self.out.abort()' in desktop
