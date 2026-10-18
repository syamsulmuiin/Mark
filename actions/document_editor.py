"""Inspect and revise real DOCX artifacts without overwriting their originals."""
import json
from core import document_revisions


def document_editor(parameters, player=None):
    try:
        action = parameters.get('action', 'inspect')
        source = parameters.get('file_path', '')
        if action == 'list':
            result = document_revisions.list_documents()
        elif action == 'inspect':
            result = document_revisions.inspect(source)
        elif action in {'revise', 'append_section'}:
            from core.llm_text import generate
            result = document_revisions.revise(source, parameters, generate=generate)
        else:
            raise ValueError('Supported document actions: list, inspect, revise, append_section')
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({'ok': False, 'status': 'FAILED', 'verified': False, 'executed': False,
            'error': str(exc), 'instruction': 'No revised artifact was verified. Keep the original; inspect the actual source before retrying. Never invent an output path.'}, ensure_ascii=False)


TOOL = {
    'name': 'document_editor',
    'description': 'Add new bibliography using append_section at document end, never by replacing a conclusion. Use replacement_blocks to keep numbered subheadings separate from body text. Inspect and revise existing DOCX papers/documents. First list real generated DOCX paths if unknown, then inspect the exact source. Revise a unique exact paragraph or a structural heading section using its source_sha256. Creates a verified new .docx version and leaves the original untouched. Never use dev_agent to regenerate an entire paper for a partial edit. Send only the returned verified file_path via send_server_file.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['list', 'inspect', 'revise', 'append_section']},
        'file_path': {'type': 'STRING', 'description': 'Exact existing source path from a tool result; never invent updated_paper.docx.'},
        'source_sha256': {'type': 'STRING', 'description': 'Exact source version hash returned by inspect/list; required for revise.'},
        'target_text': {'type': 'STRING', 'description': 'Exact full text of one unique paragraph; alternative to section_heading.'},
        'section_heading': {'type': 'STRING', 'description': 'Exact unique heading whose body should change; heading is preserved.'},
        'end_heading': {'type': 'STRING', 'description': 'Exact next section boundary, required if heading styles do not encode a level.'},
        'replacement_text': {'type': 'STRING', 'description': 'Replacement paragraphs separated by real newlines, never escaped backslash-n. Prefer replacement_blocks.'},
        'replacement_blocks': {'type': 'ARRAY', 'description': 'Preferred structured replacement: separate heading and body blocks. Do not combine with replacement_text.', 'items': {'type': 'OBJECT', 'properties': {'type': {'type': 'STRING', 'enum': ['heading', 'paragraph']}, 'text': {'type': 'STRING'}, 'level': {'type': 'INTEGER', 'description': 'Heading only: 1 to 9; subheadings below preserved heading'}}, 'required': ['type', 'text']}},
        'instruction': {'type': 'STRING', 'description': 'Requested changes to the selected text only, if replacement_text is absent.'},
        'output_name': {'type': 'STRING', 'description': 'Optional .docx display filename; a unique revision suffix is always added.'},
    }, 'required': ['action']},
    'handler': document_editor,
}
