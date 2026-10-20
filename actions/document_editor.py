"""Inspect and revise real DOCX artifacts without overwriting their originals."""
import json
from core import document_revisions


# Fixed validation messages only: never persist generated document text or paths.
_VALIDATION_REASONS = {
    'Source is not a DOCX document': 'invalid_source_format',
    'DOCX body is missing': 'missing_document_body',
    'Document inspection exceeds the text limit; select a smaller source': 'inspection_limit',
    'Revision is empty or too large': 'replacement_size',
    'Revised document must retain .docx format': 'invalid_revision_format',
    'Provide a short document title on one line': 'invalid_title',
    'New documents use replacement_blocks or an instruction, not replacement_text': 'invalid_creation_input',
    'Output filename must end in .docx': 'invalid_output_format',
    'Document is too large for targeted revision': 'source_size',
    'Do not replace a section with a bibliography. Use append_section for a new bibliography at document end.': 'bibliography_requires_append',
    'append_section needs a new section_heading and no target_text': 'invalid_append_target',
    'Section already exists; inspect and revise that section instead of appending a duplicate': 'duplicate_section',
    'A bibliography already exists; revise it without appending after it': 'duplicate_bibliography',
    'Selected section is too large; choose a smaller revision target': 'section_size',
    'Source changed during revision; retry from a fresh inspection': 'source_changed_during_revision',
    'Saved replacement text did not verify': 'replacement_verification_failed',
    'Unselected content changed before the revision': 'unselected_content_changed',
    'Unselected content changed after the revision': 'unselected_content_changed',
    'Provide a creation instruction or complete replacement_blocks': 'missing_creation_input',
    'Created document text did not verify': 'creation_verification_failed',
    'Revised DOCX verification failed': 'revision_verification_failed',
    'Saved heading structure did not verify': 'heading_verification_failed',
    'Created heading structure did not verify': 'heading_verification_failed',
    'Separate numbered subheading and its body using replacement_blocks': 'unstructured_subheading',

    'Source version is missing or changed. Inspect the document and use its exact sha256 before revising.': 'source_version_changed',
    'Provide exactly one section_heading or exact paragraph target_text': 'ambiguous_target',
    'Revision target must match exactly one paragraph; inspect the current source': 'target_not_unique',
    'end_heading must uniquely identify the next boundary': 'invalid_section_boundary',
    'This heading has no structural level. Supply end_heading or use exact paragraph target_text.': 'missing_section_boundary',
    'Target is empty or includes tables/structured content; use an exact text paragraph target instead': 'unsupported_target_structure',
    'Target includes protected document structures; select a plain text paragraph': 'protected_target_structure',
    'No verified text change was produced; no revised file was saved': 'no_text_change',
    'Provide replacement_blocks OR replacement_text, not both': 'conflicting_replacement',
    'Adding a bibliography requires append_section; preserve this section and perform separate scoped edits': 'bibliography_requires_append',
    'Replacement subheadings must be below the preserved section heading': 'invalid_subheading_level',
    'Provide replacement_text or a revision instruction': 'missing_replacement',
    'Revision is empty or invalid': 'empty_replacement',
    'Heading level must be an integer from 1 to 9': 'invalid_heading_level',

    'Text provider returned invalid or oversized document content': 'invalid_content_size',
    'Text provider did not return structured document blocks; no file was created': 'invalid_blocks_json',
    'Text provider omitted document blocks; no file was created': 'missing_blocks',
    'Document content is an outline or ends in an empty heading; complete body paragraphs are required': 'incomplete_body',
    'Bibliography must be the final section': 'bibliography_not_last',
    'Bibliography title must be a heading block': 'bibliography_not_heading',
    'Each replacement block must be a paragraph or heading': 'invalid_block_type',
    'Each block needs one nonempty text line; separate paragraphs into blocks': 'invalid_block_text',
    'Literal escaped newlines/code fences are not document paragraphs. Use actual newlines or replacement_blocks; never decode paths blindly.': 'escaped_content',
    'Numbered subheadings must be heading blocks, separate from body paragraphs': 'unstructured_subheading',
}


def document_editor(parameters, player=None):
    action = 'invalid'
    try:
        action = parameters.get('action', 'inspect')
        source = parameters.get('file_path', '')
        from core.interaction_log import write_event
        write_event(document_revisions.BASE_DIR / 'runtime' / 'interaction.log', 'document_operation_requested',
                    operation=action if action in {'create','list','inspect','revise','append_section'} else 'invalid')
        if action == 'create':
            from core.llm_text import generate
            result = document_revisions.create(parameters, generate=generate)
        elif action == 'list':
            result = document_revisions.list_documents()
        elif action == 'inspect':
            result = document_revisions.inspect(source)
        elif action in {'revise', 'append_section'}:
            from core.llm_text import generate
            result = document_revisions.revise(source, parameters, generate=generate)
        else:
            raise ValueError('Supported document actions: create, list, inspect, revise, append_section')
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        from core.interaction_log import write_event
        reason = _VALIDATION_REASONS.get(str(exc), 'validation_failed') if isinstance(exc, ValueError) else 'operation_failed'
        write_event(document_revisions.BASE_DIR / 'runtime' / 'interaction.log', 'document_operation_failed',
                    operation=action if action in {'create','list','inspect','revise','append_section'} else 'invalid',
                    error_type=type(exc).__name__,
                    reason=reason)
        result = {'ok': False, 'status': 'FAILED', 'verified': False, 'executed': False,
            'error': str(exc), 'reason': reason, 'instruction': 'No new or revised artifact was verified. Keep any original and correct the returned error. Existing documents require inspection. Never invent an output path.'}
        if action in {'revise', 'append_section'}:
            result['recovery'] = {'operation': 'inspect_before_retry', 'executed': False}
            result['instruction'] = (
                'Revision failed; the original remains unchanged. Do not repeat unchanged revision arguments '
                'or create a replacement document. Inspect the exact source again and correct the returned '
                'version, target, boundary or replacement validation error before a new revision. '
                'If the error cannot be corrected, explain the specific failure once and stop; do not repeat progress promises.')
        if action in {'revise', 'append_section'}:
            corrections = {
                'ambiguous_target': 'Provide exactly one nonempty section_heading OR target_text, never both and never neither.',
                'invalid_subheading_level': 'Use inspect heading_level (Word 1..9). Keep the selected heading out of replacement_blocks; child heading levels must be greater. Body blocks must use type=paragraph without level.',
                'no_text_change': 'The replacement matches the current selected text. No revised file was created. Apply the requested actual content changes, or explain once that the current text already matches; do not resend the old file as a new revision.',
            }
            if reason in corrections:
                result['recovery']['correction'] = corrections[reason]
        if action == 'create':
            result['recovery'] = {'operation': 'propose_general_creation',
                'tools': ['code_helper', 'dev_agent'], 'executed': False}
            result['instruction'] = (
                'Structured creation failed; this does not mean Mark cannot create documents. '
                'Inspect existing artifacts before retrying. If none was created, use propose_text_action '
                'to continue through available code_helper/dev_agent with the complete original user request '
                'and required format. Preserve execution approval and use a unique output path. '
                'Verify the actual created file before send_server_file to the requesting companion attachment Inbox. '
                'Do not regenerate an existing artifact after a delivery-only failure, invent paths, or claim completion.')
        return json.dumps(result, ensure_ascii=False)


TOOL = {
    'name': 'document_editor',
    'description': 'Optional structured DOCX creation: create accepts a title and complete user instruction; the selected Text LLM writes blocks and the host builds the file directly. General code_helper/dev_agent creation remains available for new papers and DOCX; this tool is not a prerequisite. Existing documents use scoped revision. Add new bibliography using append_section at document end, never by replacing a conclusion. Use replacement_blocks to keep numbered subheadings separate from body text. Inspect and revise existing DOCX papers/documents. First list real generated DOCX paths if unknown, then inspect the exact source. Revise a unique exact paragraph or a structural heading section using its source_sha256. Creates a verified new .docx version and leaves the original untouched. Never use dev_agent to regenerate an entire paper for a partial edit. Send only the returned verified file_path via send_server_file.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['create', 'list', 'inspect', 'revise', 'append_section']},
        'title': {'type': 'STRING', 'description': 'Required document title for create; infer a concise title from the user topic.'},
        'file_path': {'type': 'STRING', 'description': 'Exact existing source path from a tool result; never invent updated_paper.docx.'},
        'source_sha256': {'type': 'STRING', 'description': 'Exact source version hash returned by inspect/list; required for revise.'},
        'target_text': {'type': 'STRING', 'description': 'Choose this OR section_heading, never both. Exact full text of one unique paragraph.'},
        'section_heading': {'type': 'STRING', 'description': 'Choose this OR target_text, never both. Exact unique heading whose body should change; heading is preserved. Inspect heading_level uses Word levels 1..9.'},
        'end_heading': {'type': 'STRING', 'description': 'Exact next section boundary, required if heading styles do not encode a level.'},
        'replacement_text': {'type': 'STRING', 'description': 'Replacement paragraphs separated by real newlines, never escaped backslash-n. Prefer replacement_blocks.'},
        'replacement_blocks': {'type': 'ARRAY', 'description': 'Preferred structured replacement: separate heading and body blocks. Do not combine with replacement_text.', 'items': {'type': 'OBJECT', 'properties': {'type': {'type': 'STRING', 'enum': ['heading', 'paragraph']}, 'text': {'type': 'STRING'}, 'level': {'type': 'INTEGER', 'description': 'Heading only: Word 1 to 9, strictly greater than the preserved section heading_level returned by inspect; omit level for paragraphs'}}, 'required': ['type', 'text']}},
        'instruction': {'type': 'STRING', 'description': 'For create: complete user request/topic, requirements and supplied sources. For revise: requested changes to selected text only.'},
        'output_name': {'type': 'STRING', 'description': 'Optional .docx display filename; a unique revision suffix is always added.'},
    }, 'required': ['action']},
    'handler': document_editor,
}
