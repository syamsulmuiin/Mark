"""Low-risk exemptions require real pure validation, and results must reach speech."""

import json
from pathlib import Path
import pytest
from core import skill_registry, action_policy, tool_feedback
from core.skill_registry import SkillRegistry
from core.dynamic_skill_registry import DynamicSkillRegistry
from core.llm_action_proposals import validate_proposal


@pytest.fixture
def pure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        skill_registry, "__file__", str(tmp_path / "core/skill_registry.py")
    )
    root = tmp_path / "storage/autonomy"
    store = SkillRegistry(root)
    record = store.create("count_words", "Count words", [], skill_type="GENERATED")
    record.update(status="VERIFIED", operational_state="ACTIVE")
    store._save(record)
    dynamic = DynamicSkillRegistry(root, store)
    dynamic.install_verified(
        record,
        'def execute(**kwargs):\n    return len(kwargs["text"].split())',
        {"parameters": {"type": "OBJECT", "properties": {"text": {"type": "STRING"}}}},
        {"ok": True},
    )
    return store, dynamic, record


def test_verified_pure_run_requires_no_popup_and_returns_answer(pure):
    store, dynamic, record = pure
    args = {
        "operation": "run",
        "skill_id": record["skill_id"],
        "inputs": {"text": "Mark siap diuji"},
    }
    assert not action_policy.requires_confirmation("skill_manager", args)
    output = dynamic.execute(record["skill_id"], args["inputs"])
    feedback = tool_feedback.skill_feedback(json.dumps(output), args)
    assert feedback["task_result"] == 3
    assert "current response" in feedback["result_instruction"]


@pytest.mark.parametrize(
    "change", ["source", "status", "permissions", "risk", "script"]
)
def test_modified_or_nonpure_skills_stay_guarded(pure, change):
    store, dynamic, record = pure
    if change == "source":
        (dynamic.root / record["skill_id"] / "skill.py").write_text(
            "import os\ndef execute(**kwargs):return os.getcwd()"
        )
    else:
        record.update(
            {
                "status": {"status": "CANDIDATE"},
                "permissions": {"permissions": ["server.script.execute"]},
                "risk": {"risk_level": "HIGH"},
                "script": {"skill_type": "COMPOSITE"},
            }[change]
        )
        store._save(record)
    assert action_policy.requires_confirmation(
        "skill_manager",
        {"operation": "run", "kind": "pure", "skill_id": record["skill_id"]},
    )


@pytest.mark.parametrize("value", [0, False, "", None, {"count": 4}])
def test_falsey_results_are_preserved(value):
    result = {"status": "SUCCESS", "verified": True, "result": value}
    assert (
        tool_feedback.skill_feedback(result, {"operation": "run"})["task_result"]
        == value
    )
    assert (
        tool_feedback.skill_feedback(
            {**result, "verified": False}, {"operation": "run"}
        )
        == {}
    )
    assert tool_feedback.skill_feedback(result, {"operation": "list"}) == {}


def test_pure_creation_is_direct_but_maintenance_and_scripts_need_approval():
    for operation in ("create", "ensure"):
        assert not action_policy.requires_confirmation(
            "skill_manager", {"operation": operation, "kind": "pure"}
        )
        assert action_policy.requires_confirmation(
            "skill_manager", {"operation": operation, "kind": "script"}
        )
    assert action_policy.requires_confirmation(
        "server_maintenance", {"operation": "restart"}
    )
    assert action_policy.requires_confirmation("code_helper", {"action": "run"})
    # Native repair applies its own immutable approval guard.
    assert "self_repair_apply" in action_policy.NATIVE_GATES


def test_read_only_artifact_inspection_is_direct_but_code_and_external_paths_are_guarded(
    tmp_path, monkeypatch
):
    root = tmp_path / "artifacts"
    root.mkdir()
    csv = root / "numbers.csv"
    csv.write_text("value\n2\n3\n")
    monkeypatch.setattr(action_policy, "ARTIFACT_ROOT", root)
    assert not action_policy.requires_confirmation(
        "file_processor", {"action": "info", "file_path": str(csv)}
    )
    assert action_policy.requires_confirmation(
        "file_processor", {"action": "run", "file_path": str(csv)}
    )
    assert action_policy.requires_confirmation(
        "file_processor", {"action": "info", "file_path": ""}
    )
    outside = tmp_path / "config.json"
    outside.write_text("{}")
    assert action_policy.requires_confirmation(
        "file_processor", {"action": "analyze", "file_path": str(outside)}
    )


def test_missing_file_path_is_rejected_before_approval():
    raw = json.dumps(
        {"tool": "file_processor", "args": {"action": "info"}, "reason": "Inspect file"}
    )
    with pytest.raises(ValueError, match="observed file_path"):
        validate_proposal(raw, {"file_processor"})


def test_only_existing_verified_artifacts_are_grounded(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "data.csv"
    path.write_text("value\n2\n3\n")
    outside = tmp_path / "private"
    outside.write_text("secret")
    monkeypatch.setattr(tool_feedback, "ARTIFACT_ROOT", root)
    assert tool_feedback.observed_files({"verified": True, "file_path": str(path)}) == [
        str(path)
    ]
    assert not tool_feedback.observed_files({"verified": False, "file_path": str(path)})
    assert not tool_feedback.observed_files(
        {"verified": True, "file_path": str(outside)}
    )
