"""Synthesize low-risk pure capabilities; never installs dependencies or activates code."""
from __future__ import annotations
import json,re
from core import gemini

_SYSTEM='''You generate a PURE Python capability for Mark. Return strict JSON only.
The skill MUST define exactly one public entry point: def execute(**kwargs) or async def execute(**kwargs).
It may only use Python builtins plus these imports: json, math, re, statistics, datetime, collections, itertools, functools, decimal, fractions, string, typing.
It MUST NOT read/write files, access network, spawn processes/threads, inspect environment, access credentials, import dynamically, call eval/exec/open, or mutate Mark.
Return: {"name":"snake_case","description":"...","parameters":{"type":"OBJECT","properties":{}},"code":"...","tests":[{"input":{},"expected":...}]}
Tests must be deterministic. Do not use markdown fences.'''

def _json(text):
    t=(text or '').strip();t=re.sub(r'^```(?:json)?\s*','',t);t=re.sub(r'\s*```$','',t)
    start=t.find('{')
    if start<0:raise ValueError('no_json_object')
    obj,_=json.JSONDecoder().raw_decode(t[start:])
    if not isinstance(obj,dict):raise ValueError('response_not_object')
    return obj

class SkillSynthesizer:
    def synthesize(self,capability:str,purpose:str="",parameters:dict|None=None,context=None):
        prompt=json.dumps({"capability":capability,"purpose":purpose,"parameters":parameters or {"type":"OBJECT","properties":{}},"verified_context":context or []},ensure_ascii=False)
        response=gemini.call(prompt,tier=gemini.SMART,config={"system_instruction":_SYSTEM,"response_mime_type":"application/json"},timeout_ms=30000)
        if response is None:raise RuntimeError("skill_synthesis_model_unavailable")
        data=_json(getattr(response,'text','') or '')
        if not data.get('code') or not data.get('name'):raise ValueError('incomplete_skill_candidate')
        return data
