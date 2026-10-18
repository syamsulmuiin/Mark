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

## Creating files

`code_helper` and `dev_agent` provide general content/code workflows. A new extension does not inherently require a new tool, but installed libraries, runtime support, and execution approval still apply.

New papers and DOCX can use the general creation workflow. Generated code execution retains host approval; verify the actual output file and send its returned path to the requesting companion Inbox. A dedicated format-specific tool is not required.

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
