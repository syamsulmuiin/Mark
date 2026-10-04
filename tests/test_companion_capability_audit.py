from pathlib import Path
import ast, re
ROOT=Path(__file__).resolve().parents[1]
ANDROID=(ROOT/'android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt').read_text(encoding='utf-8')
ACCESS=(ROOT/'android-companion/app/src/main/java/com/jarvis/companion/JarvisAccessibilityService.kt').read_text(encoding='utf-8')
DESKTOP=(ROOT/'desktop-companion/companion.py').read_text(encoding='utf-8')
LOCAL=(ROOT/'desktop-companion/local_runtime.py').read_text(encoding='utf-8')
TOOLS=ast.literal_eval(re.search(r'^TOOLS\s*=\s*({.*?^})', LOCAL, re.M|re.S).group(1))

def test_android_has_one_capability_source_of_truth():
    assert 'private val DEVICE_CAPABILITIES = listOf(' in ANDROID
    assert ANDROID.count('JSONArray(DEVICE_CAPABILITIES)') == 2
    assert ANDROID.count('listOf("jarvis.command"') == 0

def test_android_advertised_control_capabilities_have_handlers():
    block=re.search(r'DEVICE_CAPABILITIES = listOf\((.*?)\n\s*\)', ANDROID, re.S).group(1)
    caps=set(re.findall(r'"([a-z0-9_.]+)"', block))
    transport_only={'jarvis.command','attachment.inbox'}
    for cap in caps-transport_only:
        assert f'"{cap}"->' in ANDROID, f'advertised Android capability has no handler: {cap}'
    assert 'isCredentialField(node)' in ACCESS
    assert 'AUTHENTICATION_REQUIRED' in ACCESS

def test_generic_volume_parity_android_and_desktop():
    assert '"audio.volume"' in ANDROID
    assert "'audio.volume'" in DESKTOP
    assert "elif cap=='audio.volume'" in DESKTOP
    for action in ('up','down','set','mute','unmute'):
        assert action in ANDROID
        assert action in DESKTOP

def test_desktop_legacy_runtime_tools_exist_and_are_gated():
    expected={'open_app','computer_control','computer_settings','desktop_control','file_controller','browser_control','screen_processor','send_message','system_monitor','youtube_video','video_player'}
    assert expected <= set(TOOLS)
    assert '_credential_target(parameters)' in LOCAL
    assert 'AUTHENTICATION_REQUIRED' in LOCAL

def test_desktop_advertised_direct_capabilities_have_dispatch():
    caps=ast.literal_eval(re.search(r'^NATIVE_CAPABILITIES=(\[.*\])$', DESKTOP, re.M).group(1))
    transport_only={'jarvis.command','notifications.receive','attachment.inbox'}
    for cap in set(caps)-transport_only:
        assert f"cap=='{cap}'" in DESKTOP, f'advertised desktop capability has no dispatcher: {cap}'


def test_all_desktop_local_tools_are_routed_as_device_local():
    main=(ROOT/'main.py').read_text(encoding='utf-8')
    live=(ROOT/'core/live_tools.py').read_text(encoding='utf-8')
    for tool in TOOLS:
        assert f'"{tool}"' in main, f'desktop local tool missing from origin-first routing: {tool}'
        assert tool in live, f'desktop local tool missing from device tool contract: {tool}'
