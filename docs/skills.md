# Reusable skills and image search

## Image requests

For a one-time picture or poster request, use `web_search` with `mode=images` and a query. The default `delivery=attachments` downloads six image results by default; `count` selects 1-20 per request. Larger requests must be explicitly split rather than silently truncated. Fewer provider results or failed downloads are reported as partial. It hands validated files to the requesting companion Inbox. `delivery=links` returns image/source links only when explicitly requested. A TXT list of URLs is not a substitute for requested pictures. Downloaded files are limited to 20 MiB each and 40 million pixels; JPEG, PNG, WebP and GIF are supported, while HTML/SVG are rejected. Public addresses are checked and pinned for each HTTP request, including redirects. Pillow is required for format validation. Search results alone do not verify the image contents, event year, official status, or reuse rights. Transport failures return a failed result; never invent replacement links.

Example voice request: “Find poster images for National Santri Day 2026 and send the images to this device.”

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
