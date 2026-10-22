# Files and attachments

## Delivery and storage

File delivery defaults to the requesting companion's attachment Inbox. The recipient chooses Open, Save As, or Share where supported. Direct saving occurs only when explicitly requested; the destination is not forced to Downloads.

Files are streamed through authenticated transfer tickets and verified by SHA-256 and size. Server copies use a single-copy object store under `storage/objects/`, with metadata under `storage/metadata/`. Inbox delivery can be queued for offline companions.

Native source pickers support multiple selections in one request. Each selected file remains an independent attachment. A user turn owns one picker transaction for the source/destination pair; repeated calls reuse its actual status. Partial failure does not reopen the picker automatically.

Attachments and user-generated objects are durable by default. Cleanup applies only to disposable, unreferenced processing objects; there is no blanket 30-day expiry for Inbox history.

## Attachment actions

Android and desktop separate Received and Sent entries.

| Action | Scope |
| --- | --- |
| Open / Save As / Share | Recipient-side actions where the platform supports them |
| Remove from my list | Persistent hiding for that companion; file retained |
| Delete server attachment | Confirmed transfer-entry removal for sender/recipient; object removed only when unreferenced |

Only the authenticated sender or recipient can manage an entry. Shared objects and other aliases are retained. Original server source documents and already-downloaded device copies are unchanged by server attachment deletion.

File processing requires an actual `file_path` from a prior tool result or inspected file; missing paths are rejected before an approval can be requested. Text action proposals receive recent verified artifact paths scoped to the requesting device session, without file contents. These observations do not authorize another device or arbitrary server paths. Read-only inspection of supported inert files inside `storage/artifacts/` runs without a popup; execution with unverified external effects and broader filesystem operations retain approval.

CSV processing uses pandas UTF-8 decoding with replacement for invalid bytes. Read failures are reported as failures rather than successful inspection; inspect the actual generated file before treating its content as correct.

## Creating files

`code_helper` and `dev_agent` provide general content/code workflows. A new extension does not inherently require a new tool, but installed libraries, runtime support, and execution approval still apply.

New papers and DOCX can use the general creation workflow. Host assessment determines execution approval; verify the actual output file and send its returned path to the requesting companion Inbox. A dedicated format-specific tool is not required.

As an optional structured route, `document_editor create` accepts a title and complete instruction. The configured Text model supplies structured content; the host creates a unique file without executing generated code. Complete `replacement_blocks` can also be supplied. Newly created documents are handed to the captured requesting companion Inbox; failed handoff retains the file for delivery retry.

If structured creation fails before producing an artifact, inspect existing outputs and propose general creation using the complete original request. Do not treat a validation failure as absence of host file-creation capability. A delivery-only failure requires resending the existing artifact, not regeneration.

Structured creation rejects malformed blocks, literal escaped newlines, misplaced bibliographies, and body-less outlines. Text/heading verification does not establish rendered layout quality or source/citation accuracy. Do not invent author or institution information.

## Revising DOCX

1. Locate the actual source with `list` if its path is unknown.
2. Inspect it and retain its `source_sha256`.
3. Revise an exact paragraph or a uniquely identified heading section.
4. Use separate heading/paragraph blocks for subheadings and body text.
5. Use `append_section` for a new bibliography at the end; do not replace the conclusion.
6. Use the returned version/path and inspect it again before another edit.

Revisions leave the original and unrelated content intact. Output names are unique. Literal backslash-newline sequences are rejected instead of being written into Word or blindly decoded. Never invent an updated path or claim delivery before the actual result.

Failed scoped revisions report a validation reason and require fresh inspection/corrected arguments before retry. They must not trigger whole-document regeneration. Structured creation accepts a single outer JSON code fence as well as bare JSON; commentary, malformed JSON, escaped content and invalid blocks remain rejected. Intermediate steps and task bookkeeping should not repeat the final spoken result.

Inspection exposes `heading_level` as Word levels 1–9 (`null` for body text), matching replacement block levels. It also returns `source_sha256` as an explicit alias of `sha256`. Choose exactly one `section_heading` or `target_text`. Preserve the selected heading and use strictly greater levels for child headings. An unchanged replacement creates no new revision; do not deliver the old source as a newly updated file.

General creation must distinguish source code from its generated document. `code_helper` and `dev_agent` source writers reject known binary document/container extensions such as DOCX, PDF, XLSX and PPTX. Generate a script under its source extension, execute it through the existing approval gate with a format library, verify the actual document, then deliver that document. Source-file readback verifies only that write. Format-only heading changes count as a revision even when their text is unchanged.
 Project source paths are resolved inside their project directory before writing, including symlink resolution; absolute and escaping paths are rejected.

Attachment metadata is not reset when its JSON is corrupt or has an invalid
structure. Startup reports the error so the original metadata can be recovered.
Failed metadata writes restore the previous in-memory state. Object ingestion
keeps the source until the index commits; deletion commits the index before
removing bytes. An interrupted operation can leave an unreferenced object for
recovery, rather than removing bytes still referenced by committed metadata.
These guarantees do not make the object index and attachment inbox a single
cross-file transaction. Object lookups accept only canonical SHA-256 identifiers
and do not follow object symlinks.

## Content checks

DOCX inspection includes a bounded `quality` report. Supported content readback
formats are DOCX, UTF-8 TXT and Markdown. Checks cover required headings/text,
text required within a named section, forbidden text, word-count minima,
bibliography placement, empty sections, duplicated headings, merged numbered
subheadings and obvious escaped-newline defects. DOCX heading inheritance is
resolved, and finding indices match the actual body-paragraph indices used by
inspection. Findings report codes and positions rather than copying document
content into diagnostic logs.

A `document_content` host probe can use these conditions independently of the
creation tool. Omit `path` to use the host-returned artifact reference for that
step; final checks can name its `step_id`. Thus generated files do not require a
model-invented path or a new format-specific creation tool.

```json
{"section":"report_content","equals":true,"probe":{"type":"document_content","field":"checks_passed","criteria":{"required_headings":["Conclusion"],"section_required_text":{"Conclusion":["observed results"]},"require_bibliography":true,"min_words":500}}}
```

Passing verifies only the listed structural/content conditions. The report keeps
`semantic_accuracy_verified`, `citations_verified` and `layout_rendered` false.
It does not establish factual accuracy, source authenticity, academic quality or
visual layout. Other formats/unsupported criteria need separate adapters and
remain unverified. Quality inspection never rewrites an existing document.

For small UTF-8 text, Markdown, CSV and JSON outputs, Mark returns bounded file
readback to the conversation after writing and attachment notification. Readback
must match the returned SHA-256 and stay within the artifact directory. The final
answer should include the requested substantive results and revision changes,
not just a delivery acknowledgement. File identity verification does not certify
calculation correctness; requested calculations still require verification.

After a server restart, action proposals and memory recall can recover output
references from the requesting device's durable attachment inbox. Recovery checks
that the original absolute artifact path still exists and matches its stored
SHA-256. References are ordered newest first so revisions can preserve earlier
changes. Other devices, deleted inbox entries, missing files, changed content and
symlink paths are excluded. Recovery provides context; it never replays actions
or approvals. The model must inspect the relevant file before revising it.

Attachment metadata stores project-relative source paths. Recovery resolves these
against Mark's installation directory, independently of the service working
directory, and then applies the same artifact-root and hash checks. Memory recall,
Text action proposals and Text reasoning receive the recovered references.
`artifact_context_recovered` events record counts and consumers without file
contents or paths, making empty recovery visible in runtime diagnostics.

CSV/Excel analysis includes source rows, column names and a file hash alongside
the model's analysis, and respects the supplied analysis instruction. Small text
artifact references also include hash-matched source content during recovery.
This allows sequential revisions to retain earlier changes instead of rebuilding
unchanged values from memory. Readback verification proves file identity, not
semantic correctness: compare requested changes and preserved values before
claiming completion, especially after a user reports an incorrect revision.

DOCX listing responses also expose the requesting device's recovered artifact
references so non-DOCX outputs are discoverable without repeating DOCX lookups.
Small CSV, TSV, TXT, Markdown and JSON sources support `file_processor inspect`
for bounded exact text readback without an LLM analysis call. A DOCX inspection
request naming one of these formats is routed through the same file inspection
policy; authorization and export restrictions still apply. Oversized sources
require bounded analysis rather than being reported missing.

Server storage discovery uses `file_processor` with `action=list_directory` and `file_path=storage`. Browse returned directory paths and use `offset`/`limit` for subsequent pages (maximum 200 entries). This read-only operation needs no approval, covers all file formats, excludes credential/key files and symlinks, and does not prove content correctness. Attachment history is not a complete storage inventory. Deleting a server attachment copy does not guarantee that an original artifact remains; inspect actual storage before reporting availability.
