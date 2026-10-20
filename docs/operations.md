# Operations and troubleshooting

## Lifecycle

Use `python main.py --start`, `--stop`, or `--restart` from the server environment. `--enable` installs per-user autostart; `--disable` removes it without implicitly stopping a running server. `--server-worker` is internal.

Startup succeeds only when the local health endpoint reports the expected server PID. A running process without a healthy API is not ready. Restart does not launch a replacement until the existing server stops. Stop and restart first terminate the tracked autonomy worker and refuse to proceed if termination cannot be confirmed.

Ending a conversation does not stop the service. Server shutdown requires an explicit server/service request.

## Emergency execution stop

Use `python main.py --break` to force-stop the tracked autonomy worker while
keeping the server/companions running. Use `--stop` only to stop the server.
Interrupted goals are preserved as `INTERRUPTED`; runtime returns to `idle` only after worker termination is confirmed. They are not automatically replayed. This currently covers `autonomous_goal`, not every inline Live or legacy tool call.
The optional global chord is Ctrl+Alt+Shift+F12 where OS input access is available.
See [Emergency stop](emergency-stop.md) for PID identity checks, interrupted-goal
handling, service-session limitations and the scope of the worker integration.

## Script updates

Voice examples:

- “Check Mark for updates.”
- “Update Mark scripts from GitHub.”
- “Restart the Mark server.”
- “Update Mark and restart.”
- “Check maintenance status.”

`server_maintenance` exposes `status`, `check`, `update`, `restart`, and `update_restart`. Status/check require no approval; mutations use one host approval. The tool must be loaded in the server action registry.

Checks report upstream availability separately from local blockers. Applying an update requires the official GitHub origin, the `main` branch, a clean checkout, fast-forward history, and passing server-source syntax checks. It never resets or deletes local changes. Blocked application reports up to 50 path/status entries and a total count.

Root runtime state and local credentials are ignored by Git. Already-tracked source modifications remain blockers. Do not use a hard reset or clean command merely to clear an update message.

Dependency-file changes retain a manual-install requirement and prevent automatic restart, including repeated update-and-restart requests. Use the server environment to install required dependencies before explicitly restarting. Maintenance does not update companion APKs.

A detached helper schedules restart after ten seconds. Scheduled/restarting means `WAITING`; completion requires replacement-worker health/PID verification. After reconnecting, check maintenance status. A stuck job requires inspection of `runtime/maintenance.json` and `runtime/maintenance.log`.

## Logs

| Location | Purpose |
| --- | --- |
| `runtime/error.log` | Rotating server warnings, errors, and tracebacks, including early worker import failures |
| `runtime/interaction.log` | Conversation-entry metadata, loaded tools, model calls, approvals, connections, and action outcomes |
| `runtime/maintenance.json` | Last maintenance/restart state |
| `runtime/maintenance.log` | Detached restart-helper output |
| `~/.mark-companion/logs/error.log` | Desktop companion failures; separate from server logs |

Interaction logs do not contain transcript text or audio. A quiet error log is normal during successful operation and does not prove that no failures occurred.

Ask voice Mark to inspect runtime logs. `runtime_diagnostics` reads fixed server paths, redacts credentials, distinguishes missing/empty/unreadable files, and scans at most 2 MiB of interaction history while filtering audio noise. Older events can fall outside that window. Typed chat does not execute this tool.

Interaction writers report storage failures to stderr, rate-limited per path. If both logging destinations are unwritable, persistence cannot be guaranteed. Check permissions and disk space.

## Connection recovery

Transport connectivity and conversational progress are separate. Repeated completed voice inputs without provider progress can trigger a same-model session recycle. Session expiry discards stale resumption state while local task context is retained. Provider quota failures back off without selecting another model.

Android retains pairing through ordinary transport loss. Authentication failures preserve keys and pause retries for inspection; a changed server identity is not silently trusted. Preserve server identity/trust files and companion app data.

Repeated/background speech needs device-level investigation. Local VAD, onset gating, and Android AEC/NS reduce noise; they do not prove acoustic echo is absent.

## Task outcomes and self-repair

`FAILED`, `WAITING`, and `UNVERIFIED` do not complete a task. `VERIFIED` applies to a reported step, not the entire user goal. Approval is authorization, not execution evidence; attachment handoff is not device saving.

Diagnosis is read-only. Apply requires explicit repair authorization and a validated plan; high-risk changes need separate approval. Repair Guard restricts paths, protected areas, risk, and change budgets. Candidates are checked in isolation, then in the working tree; failures restore transaction snapshots. Historical repair knowledge must be checked against current source.

Repair does not install dependencies, change privileges, bypass its own guard, commit/push, or restart itself. A validated Python edit still needs activation and reproduction of the original task. Android changes require rebuilding and installing the APK.

Live reconnect delays reset after at least 60 seconds of connected service; immediate failures retain bounded backoff. Reconnects preserve the configured model/provider. If a resumed handshake fails with `1008 Requested entity was not found`, Mark discards that handle and retries a fresh session with bounded delay; this does not establish that the model itself is missing. A rejection after an established connection does not discard the handle on this evidence alone. Local rollover transcripts are injected only when no resumption handle is used, avoiding duplicate context during successful resumption. A provider deadline alone does not prove quota exhaustion or a need for a VPN. Document failures include a fixed validation reason code in the interaction log without generated content; older logs containing only `ValueError` cannot identify the rejected structure.

Text-proposal approval replay is scoped to the host voice turn and session: repeated calls in the same turn reuse the terminal decision, while a new user turn can request a fresh approval after rejection, expiry, or completion. An identical action still running remains blocked across turns. A new approval never reuses an old request ID or decision.

Approval speech is scoped to the approval request: duplicate status events are suppressed, and a completed action replaces a permission acknowledgement that has not yet been spoken. Slow actions can still acknowledge permission before reporting their later result. Tool exceptions reach speech through the tool response rather than an additional injected user turn. Long-running tool progress updates status without appending repeated chat entries. The silent-session watchdog pauses while Live tool calls are in flight and clears stale deadlines when the batch finishes.

Code/project runners use process exit status rather than error-like words in successful stdout. A timeout is an unverified `WAITING` result, not proof of a working GUI/server, and stops the automatic build/fix retry loop pending inspection. Build tools return their final result through the tool response rather than injecting a second speech turn.

Operator health/pairing endpoints require `devices/local_api.token` in addition to loopback access; the CLI supplies it automatically. Keep that credential private. Candidate repair copies exclude live device/provider state and credential/key files. The validation checkout is not an OS sandbox and still runs validators as the server account.

Repair validators receive an allowlisted runtime environment, temporary HOME/config/cache directories, no inherited provider credentials, no user-site Python packages and no automatically loaded pytest plugins. Validation copies omit symlinks; repair targets with symlink components are rejected and protected names are compared case-insensitively. Local operator authentication and server export policy are immutable to automatic repair. These controls are not OS isolation; validators still run with the server account's filesystem and network privileges.

The validation copy excludes root server `runtime/` state while retaining `desktop-companion/runtime/` source. A global runtime-directory exclusion would remove desktop modules and make the full validation suite fail.

Repair validation failures report their stage (copy preparation, source copy, candidate write, or validator launch) without exposing environment values. A copy/launch failure rejects the prepared transaction before production edits. Snapshot preparation or rejection-status persistence failures return explicit `FAILED` results with `source_modified=false`; inspect the reported transaction if its status could not be saved.

Rollback verifies transaction identifiers, manifest identity, non-symlink snapshot paths, unique allowed targets and every stored snapshot hash before restoring any source. Protected authority files cannot be restored through a modified transaction manifest. If an incomplete transaction cannot be recovered, new repair is blocked for manual inspection. I/O failure during restoration can still require manual recovery; multi-file replacement is not one filesystem-atomic operation.
 Repair source replacement preserves existing file permission bits, including executable permissions.

Device revocation, capability manifests, health counters and last-seen updates
publish their in-memory state only after the trusted-device file is successfully
replaced. Failed writes leave the previous committed state intact and report an
error; a failed revocation must be retried before treating access as revoked.
Device-state temporary files are flushed and synced before replacement. These
updates preserve existing identities, capability grants and pairing rules.

Interrupted autonomous steps retain their step identifier, execution target and
available result before recovery. Advancing such a goal does not replay its
executor. Supply a fresh observation of the step's verification section, then
advance again to reconcile it. Unchanged historical observations or unrelated
observations cannot confirm the interrupted step. If its outcome remains
uncertain, the goal stays blocked for inspection. Legacy interrupted goals with
no recorded active step also stop for inspection. Recovery does not recreate an
approval or grant authority to execute a replacement action.

Live reconnect configuration carries unfinished work as reference context. The
host sends a recovery turn only while its captured session, user input and active
action still match. Late tool results cannot overwrite a newer task/action, and
replayed checkpoints for the same observed action do not duplicate task memory.
Approval replay protection remains active while an approved text action is still
running, even beyond the usual completed-proposal replay window.

A failed or unverified coordinator result does not authorize an automatic repeat.
Only steps already explicitly marked `fallback_safe` as safe to repeat retain
bounded retry behavior. Otherwise retain the active step and inspect its outcome.

The model-facing `autonomous_goal observe` operation records an unverified claim
under expected state; it cannot write independent observed state. Verification
requires a fresh host observation, including for historical records without host
provenance. A goal without a host/device readback must remain unverified rather
than accepting model-supplied values as proof. Host observation adapters still
need coverage for each supported workflow.

## Host readback and whole-goal completion

Autonomous steps can attach a read-only `probe` to their `verify` rule. A
`server_file` probe uses the existing runtime/storage export policy and reads
actual bytes, size and SHA-256. A `companion` probe permits only `app.inspect` or
`android.ui.inspect`, on the exact execution device with its existing capability
grant. Companion results must report successful verified readback with evidence;
no mutating action is accepted as a verification probe. Capability replies are
bound to their original device, socket, capability and call identifier.

Example file verification:

```json
{"section":"report","equals":true,"probe":{"type":"server_file","path":"storage/artifacts/report.docx","field":"exists"}}
```

Example Android foreground verification:

```json
{"section":"foreground","equals":"com.example.app","probe":{"type":"companion","capability":"app.inspect","field":"evidence.active_package"}}
```

A successful step count is insufficient for `GOAL_ACHIEVED`. The coordinator
checks final post-conditions again. Supply `completion_checks` for the complete
requested end state; otherwise it conservatively rechecks each step condition.
Explicit final conditions allow temporary intermediate states, such as opening
an app before closing it. A final condition can name `step_id` to reuse that
step's execution device. Changed-state rules use the host's recorded per-step
baseline. A failed final check preserves completed steps and can be inspected
again without re-executing them.

File existence/hash verification does not validate document content, references,
layout or delivery. These need separate matching final conditions and supported
readback. Unsupported probes remain unverified. The implemented companion probes
use existing native capabilities; no APK protocol change is required.

## Scoped procedural memory

Automatic capability-evolution context includes only VERIFIED knowledge matching
the current OS, machine architecture, Python version and exact Git commit, with
validation no older than 30 days. Unknown scope, unavailable commit, expired or
future timestamps and contradicted knowledge are excluded. New automatic records
capture this scope; promotion records validation time. Old records are retained
and remain inspectable, but require revalidation in the current scope before
automatic reuse. This policy applies to procedural knowledge used in capability
evolution, not the user's language preferences or general conversation history.

## Declared requirement coverage

Goals may declare `requirements` as objects with an `id` and `description`.
Every declared requirement must have at least one final `completion_checks`
entry naming its `requirement_id`; unknown or uncovered identifiers are rejected
before execution. Rule validation rejects multiple operators, unsupported fields
and invalid boolean operators instead of silently ignoring part of a condition.
Coverage is checked again at finalization. It verifies the declared contract,
not whether model-authored requirements exhaust the user's natural-language
request; `semantic_completeness_verified` remains false.

## Physical-device acceptance checks

These checks require a connected operator-owned Android/desktop device. Automated
protocol tests do not substitute for them.

| Scenario | Expected result | Evidence to retain |
| --- | --- | --- |
| Disconnect during approval | Reconnect does not execute from a stale approval reply | Request ID, approval decision and execution events |
| Restart after an action starts | Inspect/reconcile before any repeat; uncertain outcomes stay blocked | One execution event and subsequent readback |
| Create, revise and receive a document | Original stays intact; only selected content changes; returned revision reaches the origin Inbox | Source/revision SHA-256, attachment ID and device-open result |
| Repeat a final-result/status event | No duplicate action, approval popup or unchanged final speech | Interaction log and observed companion behavior |
| Inspect foreground/UI | Readback comes from the exact paired device with its existing grant | Call ID, capability result and device identity |

Retain the actual new logs and record the device/OS and server commit when
reporting results. A test without device access is pending, never passed.
