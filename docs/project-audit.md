# Project audit

This audit reviews source contracts and automated checks across the server and native companions. It is not a penetration-test certificate, hardware qualification, or proof that arbitrary model output will be correct.

## Scope and evidence

| Area | Review and validation | Runtime limit |
| --- | --- | --- |
| Text/Live routing and prompts | Primary-model policy, proposal handoff, host capabilities, language and document contracts; routing tests | No paid provider/account calls |
| Tool execution and document workflows | Creation/revision, unchanged detection, process outcomes, approval feedback and attachment delivery regression tests | No visual layout or citation verification |
| Pairing and authorization | Actual desktop request/claim method against the server mesh, operator-code signature, owner credential, trust persistence and negative tests | No live public-tunnel penetration test |
| Desktop state and UI | Atomic state writes, identity validation, new pairing controls; compile and protocol tests | No interactive Qt, microphone or OS-control test |
| Android | Pending versus active trust separation, identity comparison before promotion, existing approval/audio/attachment regression checks and CI compilation | No physical Android test |
| Storage and file transfer | Trusted export roots, traversal/symlink restrictions, durable Inbox, device-scoped deletion and transfer tests | No production storage migration or disk stress test |
| Self-repair | Existing risk gates, isolated validation, interrupted-transaction recovery and rollback tests | Production credential files and symlinks are excluded from the validation copy; validators use a minimal environment and temporary configuration home. Critical authority files remain protected even through case aliases |
| Setup and CI | Server/desktop dependency separation, lifecycle checks, Python compilation, workflow review and CI | Optional native AEC3 builds and hardware audio require separate validation |

## Confirmed findings addressed

| Severity | Finding | Change |
| --- | --- | --- |
| High | A loopback proxy and fixed header were insufficient proof of local operator authority | Health and code-issuance endpoints require a private local token, supplied automatically by the CLI |
| High | Desktop used blocked legacy pairing endpoints | Desktop now requests pairing and claims its operator-issued eight-character code using its existing Ed25519 identity |
| High | Desktop silently treated unreadable state as a fresh installation | Corrupt or partial identities fail closed; state writes are atomic and owner-readable |
| High | Validation repository copies could include live identities and provider credentials | Exclude device state, provider authentication and credential/key files from candidate copies |
| Medium | Pairing and permission changes could apply in memory before persistence succeeded | Persist candidate trust before authorizing it or consuming a pairing request |
| Medium | Unauthenticated pending pairing requests were unbounded | Expired requests are pruned, the queue is capped, and peer public keys are validated |
| Medium | Android overwrote active server trust when merely requesting new pairing | Pending server identity remains separate until a matching successful claim |

Validation copies retain `desktop-companion/runtime` application source; only root server runtime state is excluded. An actual filtered-copy validation run is required in addition to ordinary repository tests.

Earlier document/execution fixes remain covered: consistent heading levels, structure-only revisions, single-path build feedback, timeout honesty, binary-format source-write rejection and verified source/document distinction.

## Deployment and remaining validation

Update the server and desktop checkout, restart the server, and install the updated Android APK over the existing app with the same signing identity. Preserve device identities and state. Do not reset working pairings as an upgrade step. Older uncompleted Android pairing requests must be requested again.

Required real-device checks: new desktop pairing through the operator CLI; existing desktop/Android reconnect after restart; failed or cancelled re-pairing preserves active trust; voice interruption and single result feedback; document revision followed by opening the received artifact; explicit direct save; Android Accessibility execution and background reconnection. Windows/macOS desktop and optional native AEC3 targets remain platform-specific validation work.

The repair validation copy is not an operating-system sandbox: validators still run under the server account. Credential/environment exclusion and symlink restrictions reduce accidental exposure, but do not provide process-level filesystem/network isolation. Validators can still access paths available to the server account; full OS isolation remains a separate deployment requirement.

## Task recovery, verification and memory

Recovery checks cover interruption after a side effect, interruption during
verification, persisted executor results, fresh versus stale observations,
legacy interrupted state, late tool results, duplicate checkpoints and delayed
reconnect turns. Coordinator advances are serialized within one server process.
Task/goal state with invalid JSON is preserved and reported rather than silently
replaced. Goal and knowledge identifiers reject path traversal and symlinks.

Verification remains step-specific: a delivery record proves server handoff,
not device saving or document quality. Recovery requires a fresh observation of
the relevant verification section before accepting an interrupted step. An LLM
claim or unrelated observation is insufficient. This is not an exactly-once
protocol with external devices/services; unknown outcomes require inspection,
and separate server processes are not coordinated by the in-process lock.

Task checkpoints retain observed action identifiers and evidence. Procedural
knowledge retains validation status, environment, repository commit, validation
time and contradiction history. Automatic capability-evolution retrieval filters
these records by the current scope and age. Remaining evaluation includes the
semantic completeness of goal criteria, broader host/device readback coverage,
and real-device disconnect/restart tests during approval and file delivery.

The model-facing `observe` operation records an unverified claim in expected
state. The verifier requires host provenance and rejects legacy model
observations; supported readback adapters are described below. Absent supported
readback, completion remains unverified.

## Host evidence and scoped-memory validation

Supported readback now connects actual approved server-file reads and existing
paired-device inspections to step and final-condition verification. Tests cover
missing files despite successful tool claims, file hashes, a previous output
removed by a later step, temporary intermediate states, changed-state baselines,
exact device permissions, and wrong-device/socket/capability replies. Final goal
verification evaluates declared end-state conditions, not just completed-step
counts. Procedural-memory tests cover environment, commit, age, future timestamps
and contradiction exclusions while preserving historical records.

Coverage remains bounded: companion transport is tested with protocol fixtures,
not physical Android/desktop devices. Only the listed readback adapters are
implemented. Semantic completeness of model-authored goal criteria and document
quality still need workflow-specific evaluation. Scoped procedural retrieval is
not a replacement for personal-memory privacy/retention controls, and these
checks do not provide external exactly-once execution or multi-process locking.


## Document content and goal-contract coverage

DOCX/TXT/Markdown readback evaluates declared content and structural conditions;
DOCX inspection surfaces defects without rewriting the source. Regression tests
cover merged subheadings, escaped newline text, empty conclusions, required text
in the wrong section, inherited heading styles, dynamic artifact paths and
requirement-to-final-check coverage. Invalid or ambiguous rules fail before
execution. Coverage and content results do not certify semantic completeness,
source authenticity or academic quality.

A previously supplied DOCX was reviewed read-only as an eight-page render and
through extracted structure. It showed duplicated/merged headings, visible
escaped newlines, placeholder identity text and a conclusion with no separate
body before the bibliography. Equivalent synthetic cases are in the regression
suite; the private source file is not included in the repository. That review is
not a claim that current generation reproduces those historical defects.

Physical Android/desktop acceptance remains pending: the audit environment has
no connected device transport. The operations guide lists concrete acceptance
cases and evidence to retain. No hardware, voice playback, accessibility or
real-device download result is marked passed by unit/protocol tests.


## Emergency process control

The autonomy coordinator path now runs in a dedicated child controlled by the
service. `python main.py --break` reads owner-only PID metadata and verifies
creation time, command and run identity before forceful termination. Runtime
state returns to idle only after confirmed death; interrupted goal evidence is
retained. Emergency files are protected from autonomous repair. Pynput supplies
a separate global listener where the OS grants input-session access; unavailable
hooks are reported explicitly and the CLI remains usable.

Coverage is the autonomous_goal worker path, not every legacy inline Live/tool
handler. Local hosted PID-namespace restrictions explicitly skip affected real
process tests. Native Linux CI must execute those cases without skipping;
physical keyboard and Windows/macOS service behavior remain platform tests.
