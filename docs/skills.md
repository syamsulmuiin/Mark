# Reusable skills and image search

## Image requests

For a one-time picture or poster request, use `web_search` with `mode=images` and a query. The default `delivery=attachments` targets six visually matching images by default; `count` selects 1-20 per request. Larger requests must be explicitly split rather than silently truncated. Fewer provider results or failed downloads are reported as partial. It hands format-validated and visually reviewed files to the requesting companion Inbox. `delivery=links` returns image/source links only when explicitly requested. A TXT list of URLs is not a substitute for requested pictures. Downloaded files are limited to 20 MiB each and 40 million pixels; JPEG, PNG, WebP and GIF are supported, while HTML/SVG are rejected. Public addresses are checked and pinned for each HTTP request, including redirects. Pillow is required for format validation. Search results alone do not verify content. Before delivery the configured Text model evaluates actual image previews against the complete query, including image type, subject, readable text and year when requested. The rule applies to photos, logos, diagrams, illustrations, collages and posters; unwanted image types are rejected according to the query. Visual assessment is probabilistic and does not establish official status, factual accuracy or reuse rights. Transport failures return a failed result; never invent replacement links.

Example voice request: “Find poster images for National Santri Day 2026 and send the images to this device.”

Candidate selection checks up to three times the requested count (minimum 12, maximum 60), in batches of six with a cooperative 90-second search/download/review budget and a 30-second cap per model call. Network operations retain their own timeouts; this is not a hard process deadline. Rejected candidates are replaced from the remaining search pool; no unbounded searches or retries run. Duplicate URLs and identical normalized previews are removed; near-duplicate detection is not guaranteed. Original files are retained on the server; only 1280-pixel JPEG previews are sent for review. Animated files are reviewed using their first frame only.

Only the selected primary Text model receives previews. Image-input adapters exist for Gemini, Google OAuth, OpenAI API/Codex account, Claude, OpenRouter and Ollama; the selected model must actually support images. DeepSeek has no image-input adapter here and returns BLOCKED before downloading, with no fallback to another provider or Live. Provider rejection, malformed verdicts or time limits never authorize unreviewed delivery. Explicit `delivery=links` returns unreviewed links without image assessment.

The result distinguishes `delivery_verified` (Inbox handoffs) from `goal_verified` (requested count of visually accepted images handed off). A successful partial delivery returns PARTIAL with matched/delivered/requested counts, rather than claiming the full request completed. Content review is evidence, not a guarantee of image quality. Events `image_content_review` record counts and stop reasons; provider traces identify the configured model without logging image payloads.

## Saved skills

`skill_manager` exposes `list`, `create`, and `run`. Fixed built-in image-search template creation and execution need no approval or Text proposal round trip. The host checks the saved composition before allowing a run without approval. Generated Python creation and execution retain host approval; listing does not execute code. Use the returned skill ID instead of inventing an identifier. Stored records live under `storage/autonomy/` and survive server restart.

Two creation kinds are supported:

- `image_search`: saves a fixed composition of the built-in image search. Registration does not prove network search succeeded. Run the saved ID with `inputs={"query":"...","count":10}` to obtain image attachments through the conversation executor. Direct internal calls without a companion executor return downloaded artifact metadata; they do not prove delivery.
- `pure`: generates a deterministic Python transformation using the selected Text provider. The existing SkillCrucible policy and tests must pass before VERIFIED registration. Generated code is not imported into the server; subsequent runs use the existing restricted runner and integrity checks. Network, filesystem, process, and credential access remain prohibited. The restricted runner is not a general OS security sandbox.

Example voice requests:

1. “Create a reusable image-search skill named poster_search.”
2. “List my saved skills.”
3. “Run poster_search using its saved ID to find National Santri Day 2026 posters.”

For a pure skill: “Create a word-count skill named count_words. Test ‘Saya sedang menguji Mark’ with expected result 4.” Then list and run the saved skill after restart to verify persistence. A conversational answer alone is not evidence that a skill was created or executed.

Arbitrary network-enabled generated Python is not supported by this interface. Network workflows must use built-in authorized capabilities or the existing autonomy composition path. Skill registration never modifies pairing, Repair Guard, approval rules, or provider selection.
