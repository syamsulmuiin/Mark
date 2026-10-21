# LLM routing

The current configuration and authentication guide is [Providers and authentication](llm-providers.md). Runtime evidence and troubleshooting are covered in [Operations](operations.md).

This path is retained for existing links. Historical audit notes and test-count snapshots have been removed.

## Capability profiles

Optional `model_routing` profiles now take precedence over legacy selections in Text chat, helper reasoning, visual review, image generation and Live client creation. Legacy primary-only behavior is retained when disabled. [Model profiles](model-profiles.md) documents the approved route policy, private configuration, catalog coverage and unsupported video/music capabilities. Host identity and routing events use the active selection; request traces record the actual attempted model. Startup credential checks use active profile credentials. Live remains single-profile, and uncertain image jobs never trigger provider replay.

Regression coverage includes bounded approved alternatives, explicit opt-in, refusal and pending-image stop conditions, credential isolation, missing and incompatible routes, legacy migration, atomic saving, cancellation, actual-alternative identity and fixed Gemini request encoding. Physical provider entitlement, device reconnect behavior after switching providers and image quality still require client trials.
