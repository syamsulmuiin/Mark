# Contributing

## Development guidelines

Preserve existing behavior unless a change is explicitly requested. Fix root causes with the smallest compatible patch. Device automation must remain application-agnostic. Do not add per-application UI recipes when the generic companion capability model can perform the task.

Documentation should describe the current implementation. Keep temporary audit notes and version-by-version patch history out of the repository unless they have an ongoing operational purpose.


## Documentation and prompts

Write project documentation, model instructions, and tool descriptions in English. Use English examples and concise, neutral wording. User conversations and explicitly requested user content follow the configured response language; multilingual input aliases are compatibility data, not documentation.

Keep the root README an entry point: overview, quick start, essential commands, and links. Put setup, provider, operations, and file details in their dedicated guides. Update the existing section instead of appending a patch diary or duplicating it across companion guides. Avoid dated test-count snapshots and unverified capability claims.

Every fix must include a documentation-impact review before completion. Update affected commands, setup requirements, dependencies, configuration, contracts, architecture, and operational limits in the same change. If no documentation change is needed, state why in the pull request.

When changing behavior, check the relevant guide, tool description, and system prompt together. Preserve protocol identifiers, prompt placeholders, authorization boundaries, and saved language preferences. Verify local links and examples against current code. Report real-device validation separately from unit tests and compilation.
