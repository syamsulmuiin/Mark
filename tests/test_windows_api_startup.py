from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/"main.py").read_text(encoding="utf-8")
DASH=(ROOT/"dashboard/server.py").read_text(encoding="utf-8")
LOG=(ROOT/"core/runtime_log.py").read_text(encoding="utf-8")

def test_http_api_is_required_not_optional():
    assert "HTTP API is a required server boundary" in MAIN
    assert "[Dashboard] Disabled:" not in MAIN

def test_dashboard_dependency_failure_is_fatal():
    assert "_DEPS_ERROR" in DASH
    assert "HTTP API cannot start because FastAPI/Uvicorn dependencies" in DASH
    serve=DASH.split("async def serve",1)[1]
    assert "dashboard disabled" not in serve

def test_worker_waits_for_actual_port_bind():
    assert 'asyncio.open_connection("127.0.0.1", DASHBOARD_PORT)' in MAIN
    assert "self._dashboard_task.done()" in MAIN
    assert "await self._dashboard_task" in MAIN

def test_startup_failure_goes_to_stderr_error_log():
    assert 'print(f"[ERROR] MARK LIV HTTP API startup failed: {e}", file=sys.stderr)' in MAIN
    assert "sys.stderr = sink" in LOG
