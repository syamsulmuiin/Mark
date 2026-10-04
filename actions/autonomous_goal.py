from __future__ import annotations
import json
from pathlib import Path
from core.autonomy_state import GoalStore,WorldState
BASE=Path(__file__).resolve().parents[1]
_STORE=GoalStore(BASE/"storage"/"autonomy")
_WORLD=WorldState(BASE/"storage"/"autonomy")
def autonomous_goal(parameters,**kwargs):
    op=str(parameters.get("operation","inspect")).lower()
    if op=="create":
        goal=_STORE.create(parameters.get("objective",""),parameters.get("origin_device",""),parameters.get("origin_session",""),parameters.get("requested_target",""))
        return json.dumps(goal,ensure_ascii=False)
    gid=str(parameters.get("goal_id",""))
    if op=="inspect":return json.dumps(_STORE.load(gid),ensure_ascii=False)
    if op=="resume":return json.dumps(_STORE.reconcile(gid),ensure_ascii=False)
    if op=="observe":
        section=str(parameters.get("section",""));_WORLD.update_observed(section,parameters.get("value"),"autonomous_goal observation")
        return json.dumps({"status":"observed","section":section})
    return json.dumps({"status":"NO_SAFE_PROGRESS_POSSIBLE","reason":"unsupported_operation"})
TOOL={"name":"autonomous_goal","description":"Persist, inspect, reconcile, or add observed world state for a long-running goal. This tool does not execute arbitrary commands or bypass approval/security boundaries.",
"parameters":{"type":"OBJECT","properties":{"operation":{"type":"STRING"},"objective":{"type":"STRING"},"goal_id":{"type":"STRING"},"origin_device":{"type":"STRING"},"origin_session":{"type":"STRING"},"requested_target":{"type":"STRING"},"section":{"type":"STRING"},"value":{}}},"handler":autonomous_goal}
