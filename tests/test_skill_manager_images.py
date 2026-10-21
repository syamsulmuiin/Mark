import json
from actions import skill_manager as manager
from actions import web_search as search
from core.action_policy import requires_confirmation


def test_image_results_are_real_links_not_claimed_downloads(monkeypatch):
    class Engine:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def images(self, query, **kwargs):
            assert query == 'poster santri 2026'
            return [{'title':'Poster','image':'https://example.org/poster.jpg','url':'https://example.org/page'},
                    {'image':'javascript:bad'}]
    monkeypatch.setattr(search, '_get_ddgs', lambda: Engine)
    monkeypatch.setattr(search, '_ddg_available', lambda: True)
    result = json.loads(search.web_search({'mode':'images','query':'poster santri 2026','delivery':'links'}))
    assert len(result['results']) == 1
    assert result['downloaded'] is False
    assert result['results'][0]['source_url'] == 'https://example.org/page'


def test_image_transport_failure_is_explicit_and_sanitized(monkeypatch):
    def fail(): raise RuntimeError('token=private')
    monkeypatch.setattr(search, '_get_ddgs', fail)
    monkeypatch.setattr(search, '_ddg_available', lambda: True)
    monkeypatch.setattr(search, '_note_ddg_failure', lambda e: None)
    result = search.web_search({'mode':'images','query':'poster'})
    assert json.loads(result)['status'] == 'FAILED'
    assert 'private' not in result


def test_saved_image_composition_is_callable_in_a_fresh_handler(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, 'BASE_DIR', tmp_path)
    created = json.loads(manager.skill_manager({'operation':'create','kind':'image_search','name':'poster_search'}))
    sid = created['skill_id']
    listed = json.loads(manager.skill_manager({'operation':'list'}))
    assert listed['skills'][0]['skill_id'] == sid
    monkeypatch.setattr(search, 'web_search', lambda args: json.dumps({'mode':args['mode'],'query':args['query']}))
    result = json.loads(manager.skill_manager({'operation':'run','skill_id':sid,'inputs':{'query':'santri'}}))
    assert result == {'mode':'images','query':'santri'}
    assert requires_confirmation('skill_manager', {'operation':'create'})
    assert requires_confirmation('skill_manager', {'operation':'run'})
    assert not requires_confirmation('skill_manager', {'operation':'list'})
    assert json.loads(manager.skill_manager({'operation':'run','skill_id':'../../secret'}))['status'] == 'FAILED'


def test_pure_skill_passes_existing_crucible_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, 'BASE_DIR', tmp_path)
    class Synth:
        def synthesize(self, *a, **kw):
            return {'name':'count_words','description':'Count words',
                    'parameters':{'type':'OBJECT','properties':{'text':{'type':'STRING'}}},
                    'code':'def execute(**kwargs):\n    return len(kwargs["text"].split())',
                    'tests':[{'input':{'text':'Saya sedang menguji Mark'},'expected':4}]}
    monkeypatch.setattr(manager, 'SkillSynthesizer', Synth)
    result = json.loads(manager.skill_manager({'operation':'create','kind':'pure','name':'count_words','purpose':'Count words'}))
    assert result['status'] == 'VERIFIED'
    run = json.loads(manager.skill_manager({'operation':'run','skill_id':result['skill_id'],
                                          'inputs':{'text':'one two three'}}))
    assert run['status'] == 'SUCCESS'


def test_network_python_candidate_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, 'BASE_DIR', tmp_path)
    class Synth:
        def synthesize(self, *a, **kw):
            return {'name':'unsafe','code':'import os\ndef execute(**kwargs):\n    return os.getcwd()',
                    'tests':[{'input':{},'expected':'anything'}]}
    monkeypatch.setattr(manager, 'SkillSynthesizer', Synth)
    result = json.loads(manager.skill_manager({'operation':'create','kind':'pure','name':'unsafe'}))
    assert result['status'] in {'REJECTED','FAILED'}
    assert json.loads(manager.skill_manager({'operation':'list'}))['skills'] == []
