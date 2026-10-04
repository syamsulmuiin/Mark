from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'main.py').read_text(encoding='utf-8')
ANDROID=(ROOT/'android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt').read_text(encoding='utf-8')
GEMINI=(ROOT/'core/gemini.py').read_text(encoding='utf-8')
WORKFLOW=(ROOT/'.github/workflows/build-android.yml').read_text(encoding='utf-8')

def test_identical_tool_calls_are_idempotent_within_user_turn():
    assert 'self._tool_turn_cache = {}' in MAIN
    assert 'tool_duplicate_suppressed' in MAIN
    assert 'self._tool_turn_cache.clear()' in MAIN
    assert 'types.FunctionResponse(id=fc.id, name=fc.name, response=_cached)' in MAIN

def test_android_advertises_and_executes_native_volume():
    assert ANDROID.count('"audio.volume"') >= 2
    assert ANDROID.count('JSONArray(DEVICE_CAPABILITIES)') == 2
    assert 'AudioManager.ADJUST_RAISE' in ANDROID
    assert 'AudioManager.ADJUST_LOWER' in ANDROID
    assert 'AudioManager.ADJUST_MUTE' in ANDROID
    assert 'AudioManager.ADJUST_UNMUTE' in ANDROID
    assert 'setStreamVolume' in ANDROID

def test_tool_backed_one_shot_uses_chat_not_direct_afc():
    assert 'cl.chats.create(model=model, config=config)' in GEMINI
    assert 'return chat.send_message(contents)' in GEMINI

def test_android_ci_uses_current_stable_gradle():
    assert WORKFLOW.count("gradle-version: '9.8.0'") == 2
