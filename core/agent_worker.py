"""Dedicated process entry point; never start the service or companion here."""
import dataclasses
import importlib
import json
import os
import sys


def advance_goal(payload, rpc):
    from actions import autonomous_goal as runtime
    from core.action_loader import discover_actions
    registry = discover_actions(runtime.BASE/'actions',
        allowed_names=set(payload['server_actions']) - {'autonomous_goal','self_repair_apply'})
    def device_executor(cap, args, goal):
        return rpc({'type':'device_call','capability':dataclasses.asdict(cap),'args':args,'goal':goal})
    runtime.configure_runtime(isolate=False,devices_provider=lambda:payload['devices'],
        server_actions_provider=registry.names,device_executor=device_executor,
        server_executor=lambda cap,args,goal:registry.run(cap.name,args,{}))
    return runtime._coordinator().advance(payload['goal_id'])


def main():
    # Dedicated protocol descriptors are non-inheritable. Tool subprocesses get
    # logs/DEVNULL, not the control pipe, so prints cannot corrupt the protocol.
    reader = os.fdopen(os.dup(sys.stdin.fileno()), 'r', encoding='utf-8')
    writer = os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf-8', buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    with open(os.devnull, 'r') as null:os.dup2(null.fileno(), sys.stdin.fileno())
    sys.stdout=sys.stderr
    def send(message):writer.write(json.dumps(message)+'\n');writer.flush()
    def rpc(message):
        send(message)
        response=reader.readline(8*1024*1024+1)
        if not response:raise ConnectionError('host_disconnected')
        return json.loads(response)['result']
    try:
        request=json.loads(reader.readline(8*1024*1024+1))
        module, name=request['entrypoint'].split(':',1)
        # Entrypoints are chosen by trusted host code, never an LLM tool argument.
        function=getattr(importlib.import_module(module),name)
        send({'type':'result','result':function(request['payload'],rpc)})
    except Exception as exc:
        send({'type':'error','error_type':type(exc).__name__})
    finally:
        reader.close();writer.close()


if __name__ == '__main__':main()
