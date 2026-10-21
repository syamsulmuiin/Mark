# Reusable skills and image search

## Image requests

For a one-time picture or poster request, use `web_search` with `mode=images` and a query. The default `delivery=attachments` targets six visually matching images by default; `count` selects 1-20 per request. Larger requests must be explicitly split rather than silently truncated. Fewer provider results or failed downloads are reported as partial. It hands format-validated and visually reviewed files to the requesting companion Inbox. `delivery=links` returns image/source links only when explicitly requested. A TXT list of URLs is not a substitute for requested pictures. Downloaded files are limited to 20 MiB each and 40 million pixels; JPEG, PNG, WebP and GIF are supported, while HTML/SVG are rejected. Public addresses are checked and pinned for each HTTP request, including redirects. Pillow is required for format validation. Search results alone do not verify content. Before delivery the configured Text model evaluates actual image previews against the complete query, including image type, subject, readable text and year when requested. The rule applies to photos, logos, diagrams, illustrations, collages and posters; unwanted image types are rejected according to the query. Visual assessment is probabilistic and does not establish official status, factual accuracy or reuse rights. Transport failures return a failed result; never invent replacement links.

Example voice request: “Find poster images for National Santri Day 2026 and send the images to this device.”

Candidate selection checks up to three times the requested count (minimum 12, maximum 60), in batches of six with a cooperative 90-second search/download/review budget and a 30-second cap per model call. Network operations retain their own timeouts; this is not a hard process deadline. Rejected candidates are replaced from the remaining search pool; no unbounded searches or retries run. Duplicate URLs and identical normalized previews are removed; near-duplicate detection is not guaranteed. Original files are retained on the server; only 1280-pixel JPEG previews are sent for review. Animated files are reviewed using their first frame only.

Only the selected primary Text model receives previews. Image-input adapters exist for Gemini, Google OAuth, OpenAI API/Codex account, Claude, OpenRouter and Ollama; the selected model must actually support images. DeepSeek has no image-input adapter here and returns BLOCKED before downloading, with no fallback to another provider or Live. Provider rejection, malformed verdicts or time limits never authorize unreviewed delivery. Explicit `delivery=links` returns unreviewed links without image assessment.

The result distinguishes `delivery_verified` (Inbox handoffs) from `goal_verified` (requested count of visually accepted images handed off). A successful partial delivery returns PARTIAL with matched/delivered/requested counts, rather than claiming the full request completed. Content review is evidence, not a guarantee of image quality. Events `image_content_review` record counts and stop reasons; provider traces identify the configured model without logging image payloads.

## Saved skills

`skill_manager` exposes `list`, `create`, `run`, and `ensure`. Fixed built-in image-search and image-create template creation and execution need no approval or Text proposal round trip. The host checks the saved composition before allowing a run without approval. Generated Python creation and execution retain host approval; listing does not execute code. Use the returned skill ID instead of inventing an identifier. Stored records live under `storage/autonomy/` and survive server restart.

The `create` operation supports three kinds; `ensure` additionally supports approved general scripts:

- `image_search`: saves a fixed composition of the built-in image search. Registration does not prove network search succeeded. Run the saved ID with `inputs={"query":"...","count":10}` to obtain image attachments through the conversation executor. Direct internal calls without a companion executor return downloaded artifact metadata; they do not prove delivery.
- `image_create`: saves the image-creation workflow using the explicitly configured generation service by default. Run with `inputs={"prompt":"Create a simple poster ..."}`. Registration stores a template; it does not generate an image until run.
- `pure`: generates a deterministic Python transformation using the selected Text provider. The existing SkillCrucible policy and tests must pass before VERIFIED registration. Generated code is not imported into the server; subsequent runs use the existing restricted runner and integrity checks. Network, filesystem, process, and credential access remain prohibited. The restricted runner is not a general OS security sandbox.

Example voice requests:

1. “Create a reusable image-search skill named poster_search.”
2. “List my saved skills.”
3. “Run poster_search using its saved ID to find National Santri Day 2026 posters.”

For a pure skill: “Create a word-count skill named count_words. Test ‘Saya sedang menguji Mark’ with expected result 4.” Then list and run the saved skill after restart to verify persistence. A conversational answer alone is not evidence that a skill was created or executed.

Pure generated skills cannot use network/filesystem access. General host scripts use the separate approved `ensure(kind=script)` workflow described below; built-in image operations retain their fixed service and authority boundaries. Skill registration never modifies pairing, Repair Guard, approval rules, or provider selection.

## Create an image rather than search

Use `image_create(prompt=...)` for a new image. Default `mode=generate` calls the explicitly configured Gemini Image API, OpenAI Image API or NVIDIA NIM hosted image API once, validates the returned image bytes, reviews the image with the selected Text model, and hands accepted results to the requesting companion Inbox. Preserve the user's complete request. No plain frame/text renderer or internet-search image may silently substitute for generation. Provider/model errors and missing setup stop with a truthful result. A timeout returns WAITING because provider completion/charges may be unknown; do not automatically retry.

Configure once in the server environment:

```bash
python -m core.image_generation --configure
```

The wizard selects the service, accepts an API key privately (or explicitly reuses the selected provider's existing key), and retrieves candidate image-model IDs from its catalog for Gemini/OpenAI. NVIDIA shows the implemented hosted-adapter list rather than claiming account-catalog discovery. Catalog availability does not prove entitlement, billing/quota or successful generation. Select a model from the numbered list or enter an exact compatible ID if discovery is unavailable. OpenAI uses GPT Image models returning base64 image data; Gemini uses native image-capable models with `generateContent`. Imagen's separate prediction API is not implemented. No model ID is guessed automatically. Codex account login is not reused as an Image API credential. The wizard saves a private `image_generation` setting while preserving Text/Live provider/model choices. Image generation may incur provider charges. `python -m core.image_generation` shows selected provider/model without exposing the key.

Generation uses fixed official HTTPS endpoints, no auth redirects, one request without automatic retry, and bounded JSON/base64/image size validation. Returned arbitrary image URLs are not fetched. Metadata-only `image_generation` log events record the actual provider/model and outcome; prompts, image payloads and keys are omitted. No new Python dependency or companion APK is required. This integration supports text-to-image generation; image editing is not implemented here. Visual review remains probabilistic and does not guarantee artistic quality or provenance.

`mode=local_design` is available ONLY on explicit request for a simple text/geometric PNG layout. Its fixed Pillow renderer accepts text, rectangles, ellipses and lines, 256-2048 pixel dimensions, up to 80 elements and bounded text. It rejects clipped text and invalid layouts. It is not a general image-generation service and must not be selected merely because the user asks for a poster, logo or illustration. Both paths require the selected Text provider to support visual review; they never fall back to another Text/Live model.

For reuse, create an `image_create` skill with `skill_manager` and run its saved ID with `inputs.prompt`. Existing saved image-creation templates now use the generation service by default; explicit `inputs.mode=local_design` retains local rendering. Registration is separate from generation and delivery. Fixed templates retain host-side approval checks; unrestricted generated Python remains guarded.

## Fulfill a request when a capability is missing

Use `skill_manager(operation=ensure, name=..., kind=..., purpose=..., inputs={...})` to reuse a matching saved skill or synthesize/build one and execute the original inputs in the same call. `name` is a stable snake_case identifier, `purpose` describes the reusable behavior, and `inputs` contains this invocation's actual data. Preserve them across reuse; a name collision with another purpose/kind or an inactive skill fails without overwriting it. The caller must continue verifying and delivering the actual requested result; registration is not completion.

- `pure`: generate a restricted Python skill, require tests with explicit expected values, run Crucible, persist only a passing candidate, and execute the original inputs. A failed candidate can be regenerated once using validation evidence; two failures stop without task execution. Subsequent calls use the saved verified skill and its existing source-integrity checks.
- `script`: use the existing `code_helper` build/run workflow, with one host approval, for general host tasks that require filesystem/network access. A standalone Python CLI accepts invocation inputs as JSON in `sys.argv[1]`. Build already runs the original task; registration must not trigger a second execution. If registration fails after execution, preserve process/output evidence and report persistence failure separately; do not rebuild or rerun merely to save the skill. Only a successful process result is registered, with a host-computed source hash and a unique path under `storage/artifacts/code/skills/`. Later approved runs verify the source hash and pass new inputs. Altered scripts fail closed. Script skills remain HIGH-risk COMPOSITE records, not VERIFIED pure skills.
- `image_search` / `image_create`: save or reuse the fixed built-in composition and execute its supplied inputs immediately. Existing image-provider and visual-review limitations still apply; this does not add image-generation API access.

Script workflows are not an OS sandbox. They retain the existing host execution authority and confirmation gate. Build uses the existing bounded repair attempts and stops on timeout; inspect partial effects before retrying. Process success is UNVERIFIED for the user goal until its actual output is checked. Missing credentials, unavailable services or required dependencies must be reported explicitly. Do not invent access, install packages automatically, or select a fallback provider/model. A missing dedicated tool alone is not a reason to ask for a manual Mark code patch.

Events `skill_fulfillment` record creation, tests, reuse and execution stages, IDs and status without logging invocation contents. Fixed image templates retain their existing approval exemption; pure generation/execution and general scripts retain host approval. `create(kind=script)` is intentionally unsupported: use `ensure` so a script must build/run successfully before registration.

### NVIDIA hosted image generation

Select option 4 in the image-service wizard and enter an NVIDIA API key. Supported hosted adapters are `black-forest-labs/flux.1-schnell` and `black-forest-labs/flux.1-dev`. They use fixed `ai.api.nvidia.com/v1/genai/...` endpoints, Bearer authentication, one 1024×1024 image in base mode, and model-specific step/guidance settings. The model ID is selected from the implemented-adapter list; it is not fetched from the language-model catalog and does not prove access/quota. Unknown NVIDIA IDs or arbitrary URLs are rejected before network access. This integration uses NVIDIA's hosted service, not a local GPU/NIM installation. A provider HTTP 202 response remains WAITING; this version does not poll asynchronous jobs or resubmit them. Text/Live choices and no-fallback rules are unchanged.

API references: [FLUX.1-schnell](https://docs.api.nvidia.com/nim/reference/black-forest-labs-flux_1-schnell-infer), [FLUX.1-dev](https://docs.api.nvidia.com/nim/reference/black-forest-labs-flux_1-dev-infer), [NVIDIA visual generation response format](https://docs.nvidia.com/nim/visual-genai/latest/getting-started.html).
