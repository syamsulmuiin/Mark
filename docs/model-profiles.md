# Unified model profiles

Model profiles are an opt-in pool of explicitly configured models. Existing setup remains unchanged until profiles are saved. A profile has an ID, provider, model ID, capabilities, private credential and short description. The same profile can serve multiple tasks when its model supports them.

```bash
python setup.py --configure-models
python main.py --restart
```

The same menu is offered by normal `python setup.py`; the configuration-only flag skips package and browser installation. First-time setup retains the required Text-then-Live sequence before offering optional tasks. The module command `python -m core.model_profiles --configure` remains a compatible shortcut.

The menu summarizes Text, Live, image reading and image generation assignments. Add models using numbered provider/capability choices and a catalog number or manual model ID. Assign models with numbers in priority order; internal IDs remain private configuration details. Unconfigured optional tasks are clearly labeled. Required Text/Live assignments must remain present before saving. Invalid choices keep the menu open, and failed edits do not change the draft. API keys are hidden; saved credentials are reused only when explicitly accepted. Native Codex/Google account setup shares the existing login flow. Authentication can persist account credentials independently of saving model assignments.

The wizard imports current primary selections without authorizing historical fallback lists. Add profiles, assign ordered profile IDs to tasks, and explicitly enable safe failover where wanted. Saving is atomic; cancelling preserves the existing file. The menu can restore legacy selections without deleting profiles. Credentials remain private in the server configuration; do not share that file.

| Capability | Purpose | Implemented adapters |
| --- | --- | --- |
| text | Typed chat, reasoning, authoring, repair | Gemini, OpenAI API, Codex account, Claude API, DeepSeek, Google OAuth, OpenRouter, local/cloud Ollama |
| vision | Read and review image previews | Text adapters above except DeepSeek |
| image | Generate new images | Gemini native image models, OpenAI Images, NVIDIA hosted FLUX |
| live | Voice conversation | Gemini Live, OpenAI Realtime |

Adapter support does not prove that every model supports every capability or that an account has access. Choose only capabilities supported by the actual model. Catalog discovery is available for Gemini, OpenAI, Codex account and supported image adapters; manual IDs remain available. NVIDIA lists implemented FLUX adapters rather than an account-specific catalog. Catalog visibility is not proof of entitlement. Google OAuth and Codex use their existing Mark account credentials; they do not grant image API access. No external CLI is required for those existing native account adapters.

Video and music generation are not implemented and are not offered as usable routes. Live has one selected profile; automatic cross-provider session failover is not implemented.

## Approved alternatives

Each task accepts at most four ordered profiles. Failover is off unless explicitly enabled for that task. Only assigned profiles can receive the request; adding a profile to the pool alone does not authorize its use for every task. Assigning alternatives authorizes sending the prompt and relevant image previews to those providers.

Text and vision can advance after HTTP 401/404/429/500/502/503/504, timeout or connection failures. Refusals, incomplete or malformed output and unsupported options stop the route. Providers may have processed a timed-out inference; this mechanism covers inference only and never replays a host tool execution.

Image generation advances only after explicit HTTP 401/404/429 rejection. Timeouts, pending/HTTP 202 responses, server errors, safety refusals and malformed results stop for inspection. These can represent already processed or charged requests. There is no automatic local placeholder substitute.

Attempts share a cooperative total time budget: Text defaults to 120 seconds, vision to 30 seconds, image generation to 120 seconds. Adapter socket timeouts cannot guarantee a hard wall-clock deadline. Existing host approvals, verification, repair controls and originating-companion attachment routing remain in force.

## Configuration and diagnostics

The private `model_routing` object contains `enabled`, `profiles`, `routes` and `failover`. Profile mode takes precedence over legacy Text/Live/image settings. Setup provider changes open the active profile menu when profiles are enabled. The standalone legacy image wizard does not change active profiles; use setup model settings or restore standard Text + Live settings. Restart after changing Live credentials or models.

`python -m core.model_profiles` prints a credential-free routing snapshot. `model_route` events record task, profile ID, provider, model, attempt and status, with error types rather than raw provider responses. Host model identity includes the selected routes; inference traces identify the model actually called. Selection is not proof that a past request succeeded.

For a safe first trial, import existing selections with failover disabled. Test typed chat and model identity, a Live exchange, image review, and one image generation using an entitled image API model. Then add one approved Text alternative and test a controlled provider failure. Never force an ambiguous image timeout to test fallback. Automated mocked tests do not replace account-access or physical-device tests.
