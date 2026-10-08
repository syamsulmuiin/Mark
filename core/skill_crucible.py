"""Policy-first verifier for generated *pure* skills.

This is deliberately narrower than Mark's normal action system.  Generated
skills may transform data but may not touch files, networks, processes,
credentials, devices, dynamic imports, or the Mark codebase.  External effects
must be composed from already-authorized capabilities instead.
"""
from __future__ import annotations
import ast, hashlib, json, os, subprocess, sys, tempfile, textwrap, time
from pathlib import Path

SAFE_IMPORTS={"json","math","re","statistics","datetime","collections","itertools","functools","decimal","fractions","string","typing"}
BANNED_NAMES={"open","eval","exec","compile","__import__","input","breakpoint","globals","locals","vars","getattr","setattr","delattr"}
BANNED_ROOTS={"os","sys","subprocess","socket","ssl","pathlib","shutil","ctypes","pickle","marshal","importlib","requests","urllib","http","asyncio","multiprocessing","threading"}
BANNED_ATTRS={"system","popen","spawn","fork","remove","unlink","rmdir","rename","replace","chmod","chown","write_text","write_bytes","read_text","read_bytes"}

class SkillPolicyError(ValueError): pass

class SkillCrucible:
    @staticmethod
    def validate_source(source:str)->dict:
        if not source or not source.strip():raise SkillPolicyError("empty_source")
        try: tree=ast.parse(source)
        except SyntaxError as e: raise SkillPolicyError(f"syntax_error:{e.lineno}:{e.msg}") from e
        execute=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=="execute"]
        if len(execute)!=1:raise SkillPolicyError("exactly_one_execute_required")
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                mods=[]
                if isinstance(node,ast.Import):mods=[a.name.split('.')[0] for a in node.names]
                elif node.module:mods=[node.module.split('.')[0]]
                bad=[m for m in mods if m not in SAFE_IMPORTS]
                if bad:raise SkillPolicyError("forbidden_import:"+','.join(sorted(set(bad))))
            if isinstance(node,ast.Name) and node.id in BANNED_NAMES|BANNED_ROOTS:
                raise SkillPolicyError("forbidden_name:"+node.id)
            if isinstance(node,ast.Attribute):
                if node.attr in BANNED_ATTRS:
                    raise SkillPolicyError("forbidden_attribute:"+node.attr)
                if node.attr.startswith("__"):
                    raise SkillPolicyError("dunder_introspection_forbidden:"+node.attr)
            if isinstance(node,ast.Call):
                fn=node.func
                if isinstance(fn,ast.Name) and fn.id in BANNED_NAMES:raise SkillPolicyError("forbidden_call:"+fn.id)
            if isinstance(node,(ast.Global,ast.Nonlocal)):raise SkillPolicyError("mutable_global_state_forbidden")
        digest=hashlib.sha256(source.encode()).hexdigest()
        return {"ok":True,"sha256":digest,"policy":"pure-v1","imports":sorted({
            (a.name.split('.')[0] if isinstance(n,ast.Import) else n.module.split('.')[0])
            for n in ast.walk(tree) for a in (n.names if isinstance(n,ast.Import) else [None])
            if isinstance(n,(ast.Import,ast.ImportFrom)) and ((isinstance(n,ast.Import) and a) or (isinstance(n,ast.ImportFrom) and n.module))
        })}

    @classmethod
    def run_tests(cls,source:str,test_cases:list[dict],timeout:float=8.0)->dict:
        policy=cls.validate_source(source)
        cases=test_cases or [{"input":{}}]
        harness = (
            "import json, inspect, asyncio\n"
            + source.rstrip() + "\n"
            + f"cases=json.loads({json.dumps(json.dumps(cases))})\n"
            + "out=[]\n"
            + "for i,case in enumerate(cases):\n"
            + "    args=case.get('input') or {}\n"
            + "    try:\n"
            + "        value=asyncio.run(execute(**args)) if inspect.iscoroutinefunction(execute) else execute(**args)\n"
            + "        expected=case.get('expected',{'__mark_no_expected__':True})\n"
            + "        matched=True if isinstance(expected,dict) and expected.get('__mark_no_expected__') else value==expected\n"
            + "        out.append({'index':i,'ok':bool(matched),'result':value,'expected':None if (isinstance(expected,dict) and expected.get('__mark_no_expected__')) else expected})\n"
            + "    except Exception as e:\n"
            + "        out.append({'index':i,'ok':False,'error':type(e).__name__+':'+str(e)})\n"
            + "print(json.dumps(out,ensure_ascii=False,default=str))\n"
        )
        env={"PYTHONIOENCODING":"utf-8","PYTHONDONTWRITEBYTECODE":"1"}
        started=time.monotonic()
        try:
            p=subprocess.run([sys.executable,"-I","-S","-c",harness],capture_output=True,text=True,timeout=timeout,env=env,cwd=tempfile.gettempdir())
        except subprocess.TimeoutExpired:
            return {"ok":False,"reason":"timeout","elapsed":timeout,"policy":policy}
        elapsed=time.monotonic()-started
        if p.returncode!=0:return {"ok":False,"reason":"runner_failed","stderr":p.stderr[-1200:],"elapsed":elapsed,"policy":policy}
        try: results=json.loads((p.stdout.strip().splitlines() or ['[]'])[-1])
        except Exception:return {"ok":False,"reason":"invalid_test_output","stdout":p.stdout[-1200:],"elapsed":elapsed,"policy":policy}
        return {"ok":bool(results) and all(x.get("ok") for x in results),"results":results,"elapsed":elapsed,"policy":policy}

    @classmethod
    def run_once(cls,source:str,args:dict,timeout:float=5.0)->dict:
        test=cls.run_tests(source,[{"input":dict(args or {})}],timeout=timeout)
        if not test.get("ok"):return {"ok":False,"reason":test.get("reason") or "execution_failed","evidence":test}
        result=(test.get("results") or [{}])[0].get("result")
        return {"ok":True,"result":result,"verified":True,"evidence":{"policy":test["policy"],"elapsed":test.get("elapsed")}}
