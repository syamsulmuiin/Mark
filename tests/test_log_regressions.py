import ast
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from core.runtime_log import RotatingTextStream, SeverityFilteredStream

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('message', [
    'ERR: Configured Text LLM failed: RuntimeError',
    'ERR: API key invalid',
    'SYS: Live session failed — reconnecting with a clean session.',
    'LIVE: Configured provider rejected quota/rate limit.',
    'NET: Connection failed — retrying in 3s.',
])
def test_real_server_error_messages_reach_disk(tmp_path, message):
    path = tmp_path / 'error.log'
    stream = SeverityFilteredStream(RotatingTextStream(path))
    stream.write(message + '\n')
    stream.flush()
    assert message in path.read_text()


def test_successful_chat_status_remains_outside_error_log(tmp_path):
    path = tmp_path / 'error.log'
    stream = SeverityFilteredStream(RotatingTextStream(path))
    stream.write('You: this error occurs sometimes\nJARVIS: error explained\nSYS: JARVIS online.\n')
    stream.flush()
    assert path.read_text() == ''


def test_worker_import_exception_is_logged_before_optional_dependencies(tmp_path):
    source = (ROOT / 'main.py').read_text()
    prefix = source.split('\nimport asyncio\n', 1)[0]
    script = "import sys\nsys.argv=['main.py','--server-worker']\n__file__=" + repr(str(tmp_path / 'main.py')) + '\n' + prefix
    script += "\nraise ModuleNotFoundError('simulated missing optional dependency')\n"
    result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'simulated missing optional dependency' in (tmp_path / 'runtime/error.log').read_text()


@pytest.mark.parametrize('interrupted', [False, True])
def test_completed_and_interrupted_voice_turns_emit_metadata(interrupted):
    tree = ast.parse((ROOT / 'main.py').read_text())
    receive = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_receive_audio')
    branch = next(n for n in ast.walk(receive) if isinstance(n, ast.If)
                  and isinstance(n.test, ast.Attribute) and n.test.attr == 'turn_complete')
    # Execute the actual whole turn-completion branch with session buffers, including
    # the interruption continue and repeat suppression, without a provider connection.
    loop = ast.For(target=ast.Name(id='_once', ctx=ast.Store()),
                   iter=ast.Tuple(elts=[ast.Constant(1)], ctx=ast.Load()), body=[branch], orelse=[])
    events, entries = [], []
    runtime = SimpleNamespace(_turn_done_event=None, _interrupted=interrupted,
        ui=SimpleNamespace(write_log=entries.append), _session_log=[], _dashboard=None,
        _asst_name='Jarvis', _last_out_logged='', _vision_close_pending=False,
        _visemes=SimpleNamespace(reset=lambda: None))
    def record(speaker, text, partial=False):
        events.append(('conversation_entry', {'speaker': speaker, 'chars': len(text), 'partial': partial}))
    runtime._record_transcript_entry = record
    namespace = {'self': runtime, 'sc': SimpleNamespace(turn_complete=True),
                 'in_buf': ['private user'], 'out_buf': ['private assistant'], '_REPEAT_MIN': 5,
                 '_trace_event': lambda event, **fields: events.append((event, fields)),
                 'journal_activity': lambda *args, **kwargs: None}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[loop], type_ignores=[])), '<voice turn>', 'exec'), namespace)
    assert len(events) == 2
    values = {fields['speaker']: fields for event, fields in events if event == 'conversation_entry'}
    assert values == {'user': {'speaker': 'user', 'chars': 12, 'partial': interrupted},
                      'jarvis': {'speaker': 'jarvis', 'chars': 17, 'partial': interrupted}}
    assert 'private' not in str(events)
