"""Describe actual loaded host tools to Text reasoning without granting execution."""
from __future__ import annotations
import json
import re


def capability_instruction(names):
    tools = sorted({name for name in names if isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name)})[:200]
    notes = ['You provide reasoning/content; Mark executes through its loaded host tools. '
             'Your inability to execute directly is not proof that Mark cannot perform the request. '
             'Never claim execution, file creation, updates or delivery without host tool evidence.']
    if 'server_maintenance' in tools:
        notes.append('Mark can check GitHub script updates, update, restart, and update_restart through server_maintenance. '
                     'Mutations require the existing host approval flow; returning shell instructions alone does not execute them.')
    generic = [name for name in ('code_helper', 'dev_agent') if name in tools]
    if generic:
        notes.append('Generic code/file tools are available: ' + ', '.join(generic) + '. '
                     'They can write content or generate/run code for formats supported by the installed runtime. '
                     'A new extension does not inherently require implementing a new tool. '
                     'Check actual dependencies/execution evidence; do not promise every format or bypass execution approval.')
    if 'document_editor' in tools:
        notes.append('document_editor is a specialized DOCX path, not the exclusive route for creating all files.')
    return '[LOADED HOST CAPABILITIES]\n' + json.dumps({'tools': tools}) + '\n' + ' '.join(notes) + '\n\n'
