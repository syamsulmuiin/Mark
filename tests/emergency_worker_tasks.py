"""Trusted subprocess fixtures: never registered as Mark tools."""
import json
import os
from pathlib import Path
import subprocess
import sys


def spin(payload, rpc):
    child = None
    if payload.get('descendant'):
        child=subprocess.Popen([sys.executable,'-c','while True: pass'])
    Path(payload['marker']).write_text(json.dumps({'pid':os.getpid(),'child':child.pid if child else None}))
    while True:pass


def echo(payload, rpc):
    print('Worker output belongs in the log, not the control pipe.')
    return {'status':'SUCCESS','pid':os.getpid(),'echo':payload}


def roundtrip(payload, rpc):
    return rpc({'type':'device_call','capability':{'name':'app.inspect'},'args':{},'goal':{}})
