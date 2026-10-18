import ast
import json
from pathlib import Path

from core.action_loader import discover_actions
from core.host_capabilities import capability_instruction
from core.llm_policy import live_delegation_instruction

ROOT = Path(__file__).resolve().parents[1]


def server_allowlist():
    tree=ast.parse((ROOT/'main.py').read_text())
    assignment=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='_server_actions' for t in n.targets))
    return ast.literal_eval(assignment.value)


def test_actual_server_allowlist_discovers_maintenance_and_general_tools(monkeypatch):
    registry=discover_actions(actions_dir=ROOT/'actions',allowed_names=server_allowlist(),logger=lambda _:None)
    assert {'server_maintenance','code_helper','dev_agent','document_editor'} <= registry.names()
    # Execute the discovered handler, not an independent direct module import.
    from core import server_maintenance
    monkeypatch.setattr(server_maintenance,'_read_state',lambda:{})
    result=json.loads(registry.run('server_maintenance',{'operation':'status'},{}))
    assert result['ok'] and 'update_restart' in result['operations']
    declarations=registry.get_tool_declarations()
    assert any(d['name']=='server_maintenance' for d in declarations)


def test_delegated_text_sees_only_loaded_capabilities():
    instruction=capability_instruction({'server_maintenance','code_helper','dev_agent','document_editor'})
    assert 'server_maintenance' in instruction and 'returning shell instructions alone' in instruction
    assert 'new extension does not inherently require' in instruction
    assert 'not the exclusive route' in instruction
    assert 'bypass execution approval' in instruction
    absent=capability_instruction(set())
    assert 'server_maintenance' not in absent and 'Generic code/file tools are available' not in absent


def test_live_policy_preserves_general_file_workflow():
    policy=live_delegation_instruction({})
    assert 'code_helper/dev_agent' in policy
    assert 'does not inherently require adding a new tool' in policy


def test_live_delegation_passes_loaded_host_context_without_executing(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from core import llm_text
    from test_approval_report_regressions import _proposal_runtime
    runtime,events,logs=_proposal_runtime()
    runtime._action_registry=SimpleNamespace(names=lambda:{'server_maintenance','code_helper','dev_agent'})
    calls=[]
    monkeypatch.setattr(llm_text,'generate',lambda prompt:calls.append(prompt) or 'Use the available host update tool.')
    response=asyncio.run(runtime._execute_tool(SimpleNamespace(id='delegation',name='delegate_to_text_llm',args={'prompt':'Update script Mark dari GitHub'})))
    assert len(calls)==1 and 'server_maintenance' in calls[0] and calls[0].endswith('Update script Mark dari GitHub')
    assert response.response['executed'] is False
    assert 'Continue operational requests' in response.response['instruction']
    assert not any(event['event']=='tool_started' for event in events)


def test_maintenance_schema_reaches_text_action_proposer(monkeypatch):
    from core import llm_text
    from core.llm_action_proposals import propose_action
    registry=discover_actions(actions_dir=ROOT/'actions',allowed_names=server_allowlist(),logger=lambda _:None)
    prompts=[]
    monkeypatch.setattr(llm_text,'generate',lambda prompt,**kwargs:prompts.append(prompt) or json.dumps({
        'tool':'server_maintenance','args':{'operation':'update_restart'},'reason':'Requested server update and restart'}))
    proposal=propose_action('Update Mark lalu restart',registry.get_tool_declarations())
    assert proposal['tool']=='server_maintenance' and proposal['executed'] is False
    assert 'update_restart' in prompts[0]
