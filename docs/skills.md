# Reusable skills and image search

## Image requests

For a one-time picture or poster request, use `web_search` with `mode=images` and a query. Results contain an image URL and a source-page URL when available. They are search links, not downloaded files or companion attachments. Search results alone do not verify the image contents, event year, official status, or reuse rights. Transport failures return a failed result; never invent replacement links.

Example voice request: “Find poster images for National Santri Day 2026 and show their source links.”

## Saved skills

`skill_manager` exposes `list`, `create`, and `run`. Creation and execution use the existing host approval policy; listing does not execute code. Use the returned skill ID instead of inventing an identifier. Stored records live under `storage/autonomy/` and survive server restart.

Two creation kinds are supported:

- `image_search`: saves a fixed composition of the built-in image search. Registration does not prove network search succeeded. Run the saved ID with `inputs={"query":"..."}` to obtain results.
- `pure`: generates a deterministic Python transformation using the selected Text provider. The existing SkillCrucible policy and tests must pass before VERIFIED registration. Generated code is not imported into the server; subsequent runs use the existing restricted runner and integrity checks. Network, filesystem, process, and credential access remain prohibited. The restricted runner is not a general OS security sandbox.

Example voice requests:

1. “Create a reusable image-search skill named poster_search.”
2. “List my saved skills.”
3. “Run poster_search using its saved ID to find National Santri Day 2026 posters.”

For a pure skill: “Create a word-count skill named count_words. Test ‘Saya sedang menguji Mark’ with expected result 4.” Then list and run the saved skill after restart to verify persistence. A conversational answer alone is not evidence that a skill was created or executed.

Arbitrary network-enabled generated Python is not supported by this interface. Network workflows must use built-in authorized capabilities or the existing autonomy composition path. Skill registration never modifies pairing, Repair Guard, approval rules, or provider selection.
