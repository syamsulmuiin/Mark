"""Bounded DOCX/text content checks, not semantic or citation certification."""
from __future__ import annotations
import io
import re
import zipfile
from pathlib import Path


def _norm(text):
    return ' '.join(text.split()).casefold()


def audit_document(path, criteria=None):
    criteria = dict(criteria or {})
    allowed = {'required_headings', 'required_text', 'forbidden_text', 'min_words',
               'require_bibliography', 'section_min_words', 'section_required_text', 'allow_escaped_newlines'}
    if set(criteria) - allowed:
        raise ValueError('unsupported_document_quality_criterion')
    for name in ('required_headings', 'required_text', 'forbidden_text'):
        if not isinstance(criteria.get(name, []), list) or any(not isinstance(x, str) or not x.strip() for x in criteria.get(name, [])):
            raise ValueError('invalid_document_quality_criterion')
    for name in ('require_bibliography', 'allow_escaped_newlines'):
        if name in criteria and type(criteria[name]) is not bool:
            raise ValueError('invalid_document_quality_criterion')
    minimum = criteria.get('min_words', 0)
    sections = criteria.get('section_min_words', {})
    if (type(minimum) is not int or minimum < 0 or not isinstance(sections, dict)
            or any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in sections.items())):
        raise ValueError('invalid_document_quality_criterion')
    section_text = criteria.get('section_required_text', {})
    if not isinstance(section_text, dict) or any(not isinstance(k, str) or not k.strip() or
            not isinstance(v, list) or any(not isinstance(x, str) or not x.strip() for x in v) for k,v in section_text.items()):
        raise ValueError('invalid_document_quality_criterion')
    path = Path(path)
    with path.open("rb") as stream:
        snapshot = stream.read(25 * 1024 * 1024 + 1)
    if len(snapshot) > 25 * 1024 * 1024:
        raise ValueError('document_quality_size_limit')
    records = []
    if path.suffix.casefold() == '.docx':
        from lxml import etree
        from core.document_revisions import W, _level, _style_levels, _text, _bibliography
        with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
            entries = archive.infolist()
            if len({p.filename for p in entries}) != len(entries):
                raise ValueError('ambiguous_docx_archive')
            if len(entries) > 2000 or sum(p.file_size for p in entries) > 100 * 1024 * 1024:
                raise ValueError('document_quality_size_limit')
            parts = [(p, archive.read(p)) for p in entries if p.filename in {'word/document.xml', 'word/styles.xml'}]
        xml = next((data for info, data in parts if info.filename == 'word/document.xml'), None)
        if xml is None:
            raise ValueError('invalid_docx_content')
        root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
        body = root.find(W + 'body')
        if body is None:
            raise ValueError('invalid_docx_content')
        styles = _style_levels(parts)
        for body_index, node in enumerate(body):
            if node.tag not in {W+'p', W+'tbl'}:
                continue
            text = _text(node) if node.tag == W+'p' else ' '.join(n.text or '' for n in node.iter(W+'t'))
            level = _level(node, styles) if node.tag == W+'p' else None
            if text.strip():
                style = node.find('./'+W+'pPr/'+W+'pStyle') if node.tag == W+'p' else None
                records.append({'text': text, 'index': body_index, 'level': level+1 if level is not None else None,
                    'title': style is not None and style.get(W+'val') in {'Title','Subtitle'}})
    elif path.suffix.casefold() in {'.txt', '.md'}:
        from core.document_revisions import _bibliography
        for line_index, line in enumerate(snapshot.decode('utf-8').splitlines()):
            if line.strip():
                match = re.match(r'^(#{1,6})\s+(.+)$', line)
                records.append({'text': match[2] if match else line, 'index': line_index,
                                'level': len(match[1]) if match else None})
    else:
        raise ValueError('unsupported_document_quality_format')
    findings = []
    def flag(code, index=None):
        entry = {'code': code}
        if index is not None:entry['paragraph'] = records[index]['index']
        if entry not in findings:findings.append(entry)
    all_text = '\n'.join(r['text'] for r in records)
    words = len(re.findall(r'\b\w+\b', all_text))
    headings = {_norm(r['text']) for r in records if r['level'] is not None}
    if not records:flag('empty_document')
    if records and not any(r['level'] is None and not r.get('title') for r in records):flag('empty_body')
    if words < minimum:flag('minimum_words_not_met')
    for text in criteria.get('required_headings', []):
        if _norm(text) not in headings:flag('required_heading_missing')
    for text in criteria.get('required_text', []):
        if _norm(text) not in _norm(all_text):flag('required_text_missing')
    for text in criteria.get('forbidden_text', []):
        if _norm(text) in _norm(all_text):flag('forbidden_text_present')
    bibliography = [i for i, r in enumerate(records) if _bibliography(r['text'])]
    if criteria.get('require_bibliography') and not bibliography:flag('bibliography_missing')
    if len(bibliography) > 1:flag('duplicate_bibliography')
    previous_level = 0
    for i, record in enumerate(records):
        text, level = record['text'], record['level']
        if not criteria.get('allow_escaped_newlines') and re.search(r'(?:\\{1,2}[nr]){2,}|\\{1,2}n(?=[A-Z0-9])', text):
            flag('escaped_newlines', i)
        if level is None and re.match(r'^\d+(?:\.\d+)+\s+', text):flag('subheading_in_body', i)
        if re.search(r'\bTODO\b|\[INSERT[^\]]*\]|\bNIM\s*:\s*0{4,}', text, re.IGNORECASE):flag('placeholder_text', i)
        is_bibliography = i in bibliography
        if is_bibliography:
            if level is None:flag('bibliography_not_heading', i)
            if any(r['level'] is not None for r in records[i+1:]):flag('bibliography_not_last', i)
        if level is None:continue
        if not 1 <= level <= 9 or level > previous_level+1:flag('heading_hierarchy_gap', i)
        previous_level = level
        end = next((j for j in range(i+1, len(records)) if j in bibliography or
                    (records[j]['level'] is not None and records[j]['level'] <= level)), len(records))
        body_words = sum(len(re.findall(r'\b\w+\b', r['text'])) for r in records[i+1:end]
                         if r['level'] is None and not _bibliography(r['text']))
        if not body_words:flag('empty_section', i)
        for heading, phrases in section_text.items():
            if _norm(text) == _norm(heading):
                body_text = _norm(' '.join(r['text'] for r in records[i+1:end] if r['level'] is None))
                if any(_norm(phrase) not in body_text for phrase in phrases):flag('section_required_text_missing', i)
        for heading, section_minimum in sections.items():
            if _norm(text) == _norm(heading) and body_words < section_minimum:flag('section_minimum_words_not_met', i)
        if i+1 < len(records) and _norm(records[i+1]['text']) == _norm(text):flag('repeated_heading', i)
    for heading in set(sections) | set(section_text):
        if _norm(heading) not in headings:flag('required_heading_missing')
    if bibliography and not any(r['text'].strip() for r in records[bibliography[0]+1:]):flag('empty_bibliography')
    return {'checks_passed': not findings, 'findings': findings, 'word_count': words,
            'heading_count': len(headings), 'scope': 'declared_content_and_structure_checks',
            'semantic_accuracy_verified': False, 'citations_verified': False, 'layout_rendered': False}
