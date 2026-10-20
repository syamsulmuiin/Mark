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
| Self-repair | Existing risk gates, isolated validation, interrupted-transaction recovery and rollback tests | Production credential files are excluded from the validation copy; authority boundaries are preserved |
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

Earlier document/execution fixes remain covered: consistent heading levels, structure-only revisions, single-path build feedback, timeout honesty, binary-format source-write rejection and verified source/document distinction.

## Deployment and remaining validation

Update the server and desktop checkout, restart the server, and install the updated Android APK over the existing app with the same signing identity. Preserve device identities and state. Do not reset working pairings as an upgrade step. Older uncompleted Android pairing requests must be requested again.

Required real-device checks: new desktop pairing through the operator CLI; existing desktop/Android reconnect after restart; failed or cancelled re-pairing preserves active trust; voice interruption and single result feedback; document revision followed by opening the received artifact; explicit direct save; Android Accessibility execution and background reconnection. Windows/macOS desktop and optional native AEC3 targets remain platform-specific validation work.

The repair validation copy is not an operating-system sandbox: validators still run under the server account. Credential exclusion reduces accidental copying, but does not provide process-level filesystem/network isolation.
