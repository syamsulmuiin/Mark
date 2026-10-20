# Emergency stop

## Commands

```bash
python main.py --break
```

`--break` force-stops the tracked autonomy execution worker and its ordinary
child processes. The Mark server, companion connections and autostart service
remain alive. `python main.py --stop` stops the server; `--restart` restarts it.
The emergency CLI runs before importing model, audio or UI dependencies.

Run the command under the server account with access to the checkout and process
state. This works without a terminal attached to the running service, including
from a separate administrative shell or SSH session.

## Process architecture

The service dispatches `autonomous_goal advance` into a dedicated Python process
through `AgentProcessManager` in `core/autonomy_engine.py`. Planning/evolution
within that coordinator and server tool execution occur in the child. A small
JSON control pipe returns results and forwards paired-device transport requests
to the service's existing authenticated device boundary. The child does not
start another server or companion. Calls should run off the service event loop,
as existing action dispatch does.

`core/agent_worker.py` is the process entry point. Tool stdout/stderr go to
`runtime/agent_worker.log`; non-inheritable protocol descriptors keep generated
subprocesses from reading or corrupting control messages. The parent never
unpickles worker messages. Entrypoints are chosen by trusted host code, not LLM
parameters.

`runtime/agent_process.json` records `status`, PID, process creation time,
`run_id`, owner PID and goal ID. Owner-only atomic writes and an OS file lock
serialize starts/stops across CLI and service processes. Stop verifies the
process command, creation time and run ID. It refuses the service/current PID,
reused PIDs and identity mismatches. A late cleanup cannot clear a newer run.

POSIX workers start a separate session/process group and receive `SIGKILL`.
Windows uses forceful process termination with descendant cleanup through
`psutil`. No graceful-cancellation request is required before killing the worker.
An uncertain kill is reported as failure; it must not be reported as `idle`.

Once death is confirmed, runtime status becomes `idle` and PID becomes null.
The durable goal becomes `INTERRUPTED`; its STARTED step, outputs and evidence
remain available for inspection. An interrupted goal does not auto-resume.
Stopping a local process cannot undo completed filesystem changes or retract an
already-dispatched remote device action. This is process control, not an OS
sandbox or a real-time scheduling guarantee.

The integration isolates the `autonomous_goal` coordinator path. Existing inline
Live/session handlers and direct legacy tool paths in `main.py` are not all
migrated into this worker; `--break` must not be represented as stopping every
possible operation in those paths. The server and Live transport intentionally
stay alive.

## Global keyboard hook

`core/hotkey.py` adds `EmergencyHotkey` using `pynput.keyboard.GlobalHotKeys`.
The listener runs in the service process, independently of the execution child.
The keyboard callback dispatches stop on a separate thread, so process waiting
and state I/O do not block the OS input callback. Existing push-to-talk remains
separate.

Default: **Ctrl+Alt+Shift+F12**. Override before starting the service:

```bash
export MARK_EMERGENCY_HOTKEY='<ctrl>+<shift>+<esc>'
```

Ctrl+Shift+Esc is commonly reserved for Windows Task Manager, so the default
avoids that chord. The listener requires access to the interactive input session:
Windows service Session 0, Linux without suitable input/display access, Wayland
restrictions and macOS input permissions can prevent a global hook. Failure is
reported explicitly; there is no window-only shortcut fallback. Use `--break`
for headless operation. A remote companion keyboard does not automatically
control a server on another machine.

Install dependencies and restart the server:

```bash
python -m pip install 'pynput>=1.7.6,<2' 'psutil>=5.9,<8'
python main.py --restart
```

## Reusable process interface

For another trusted reasoning/execution entry point, use the same supervisor:

```python
from core.autonomy_engine import AgentProcessManager
from core.hotkey import EmergencyHotkey

manager = AgentProcessManager()  # current Mark repository state
monitor = EmergencyHotkey(manager.stop)
monitor.start()  # False means OS input access is unavailable; inspect last_error.

# Invoke in the service's executor thread, not its asyncio event loop.
# my_agent.tasks.run must be an importable trusted function(payload, rpc).
result = manager.run("my_agent.tasks:run", {"goal": "Requested task"})
```

Stop the monitor and call `manager.stop()` during service shutdown. Do not call
`AutonomousCoordinator.advance` directly in the parent when process isolation is
required. Supervisor state is not an authorization token for new tool actions;
pairing, capability grants, confirmation and repair authority still apply.
Emergency-control files are immutable to automated self-repair.

## Validation

Tests exercise worker results, JSON RPC, CPU-loop termination through the actual
`--break` CLI path, descendant termination, PID identity refusal, idle reset,
interrupted-goal preservation and hook dispatch. Hosted environments whose
`/proc` view does not expose subprocess PIDs skip those process cases explicitly;
GitHub Actions requires them to execute and fails rather than skipping. Physical
keyboard hooks and Windows/macOS service behavior need platform testing.
