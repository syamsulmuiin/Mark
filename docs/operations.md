# Operations and troubleshooting

## Lifecycle

Use `python main.py --start`, `--stop`, or `--restart` from the server environment. `--enable` installs per-user autostart; `--disable` removes it without implicitly stopping a running worker. `--server-worker` is internal.

Startup succeeds only when the local health endpoint reports the expected worker PID. A running process without a healthy API is not ready. Restart does not launch a replacement until the existing worker stops.

Ending a conversation does not stop the service. Server shutdown requires an explicit server/service request.

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

Live reconnect delays reset after at least 60 seconds of connected service; immediate failures retain bounded backoff. Reconnects preserve the configured model/provider. A provider deadline alone does not prove quota exhaustion or a need for a VPN. Document failures include a fixed validation reason code in the interaction log without generated content; older logs containing only `ValueError` cannot identify the rejected structure.

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
