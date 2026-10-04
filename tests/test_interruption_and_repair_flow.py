from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_android_keeps_conversation_transcript_not_four_turns():
    src=(ROOT/'android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt').read_text(encoding='utf-8')
    assert 'rendered.takeLast(4)' not in src
    assert 'transcriptTurns.size > 4' not in src
    assert 'transcriptTurns.size > 200' in src

def test_interruption_preserves_already_visible_assistant_transcript():
    src=(ROOT/'main.py').read_text(encoding='utf-8')
    assert 'interrupted_out = " ".join(out_buf).strip()' in src
    assert 'self._record_transcript_entry("jarvis", interrupted_out, partial=True)' in src

def test_repair_gate_uses_current_turn_before_session_log():
    src=(ROOT/'main.py').read_text(encoding='utf-8')
    assert 'self._current_user_transcript = " ".join(in_buf).strip()' in src
    assert src.count('self._current_user_transcript or next(') >= 2

def test_diagnostic_returns_before_generic_runner_can_repeat_it():
    src=(ROOT/'main.py').read_text(encoding='utf-8')
    marker='Diagnostic is handled exactly once above.'
    assert marker in src
    pos=src.index(marker)
    ret=src.index('return types.FunctionResponse',pos)
    generic=src.index('if name == "self_repair_diagnostic":',ret)
    assert ret < generic

def test_user_facing_diagnostic_does_not_instruct_read_only_narration():
    src=(ROOT/'actions/self_repair_diagnostic.py').read_text(encoding='utf-8')
    tool=src[src.index('TOOL = {'):]
    assert 'Do not narrate internal dry-run/read-only policy wording to the user.' in tool
    assert 'SELF-REPAIR DIAGNOSTIC — DRY RUN ONLY' not in src
