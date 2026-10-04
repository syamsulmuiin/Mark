from pathlib import Path
SRC=(Path(__file__).resolve().parents[1]/"core/server_lifecycle.py").read_text(encoding="utf-8")

def test_process_and_api_readiness_are_distinct():
    assert "def _server_state()" in SRC
    assert '"running": True' in SRC
    assert '"ready": service_pid == pid' in SRC

def test_start_does_not_call_unready_worker_fully_running():
    block=SRC.split("def _spawn_server()",1)[1].split("def _pair_device",1)[0]
    assert "worker is running" in block
    assert "local API is not ready" in block
    assert "_local_server_identity(timeout=2.0) == pid" in block

def test_new_worker_waits_for_api_readiness():
    block=SRC.split("def _spawn_server()",1)[1].split("def _pair_device",1)[0]
    assert "_local_server_identity(timeout=0.8) == p.pid" in block
    assert "local API did not become ready" in block

def test_pair_reports_degraded_worker_not_not_running():
    block=SRC.split("def _pair_device",1)[1].split("def _stop_server",1)[0]
    assert 'if not state["running"]' in block
    assert 'if not state["ready"]' in block
    assert "Pairing is unavailable until the API is healthy" in block
