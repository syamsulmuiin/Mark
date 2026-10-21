"""Approval depends on inspected effects, not a Python extension or model label."""

import hashlib
import json
from pathlib import Path
import pytest
from core import (
    computation_script as scripts,
    action_policy,
    script_skills,
    script_assessment,
)
from core.skill_registry import SkillRegistry


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / "storage/artifacts"
    root.mkdir(parents=True)
    monkeypatch.setattr(scripts, "ARTIFACT_ROOT", root)
    monkeypatch.setattr(script_assessment, "ASSESSMENT_ROOT", tmp_path / "assessments")
    return root


def make(root, source):
    path = root / "compute.py"
    path.write_text(source)
    return path


def test_plain_script_computation_runs_without_popup_and_returns_actual_output(root):
    path = make(
        root,
        'import json, sys\ndata=json.loads(sys.argv[1])\nprint(sum(data["values"]))',
    )
    assert not action_policy.requires_confirmation(
        "code_helper", {"action": "run", "file_path": str(path)}
    )
    result = scripts.run_checked(path, [json.dumps({"values": [2, 3]})])
    assert result["verified"] is True and result["task_result"].strip() == "5"


@pytest.mark.parametrize(
    "source",
    [
        'import os\nos.remove("file")',
        'open("file", "w").write("change")',
        'import subprocess\nsubprocess.run(["reboot"])',
        "import socket\nsocket.socket()",
        'import json\njson.codecs.open("/etc/passwd").read()',
        'print(__builtins__["open"]("/etc/passwd").read())',
        "import sys\nprint(sys.modules)",
        "import sys\nprint(sys.argv[0])",
        "import math as m\nprint(m.sqrt(4))",
        'print(getattr(1,"__class__"))',
    ],
)
def test_effects_and_indirect_authority_are_not_auto_approved(root, source):
    path = make(root, source)
    assert scripts.validated_source(path) is None
    assert action_policy.requires_confirmation(
        "code_helper", {"action": "run", "file_path": str(path), "risk": "LOW"}
    )


def test_changed_source_never_runs_as_unrestricted_fallback(root):
    path = make(root, "print(5)")
    assert not action_policy.requires_confirmation(
        "code_helper", {"action": "run", "file_path": str(path)}
    )
    path.write_text('open("unauthorized", "w").write("bad")')
    with pytest.raises(ValueError):
        scripts.run_checked(path)
    assert not (root / "unauthorized").exists()


def test_snapshot_digest_is_checked_before_execution(root):
    path = make(root, "print(5)")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_text("print(6)")
    with pytest.raises(ValueError, match="integrity"):
        scripts.run_checked(path, expected_sha256=digest)


def test_computation_timeout_stops_without_retry(root):
    path = make(root, "while True:\n    pass")
    result = scripts.run_checked(path, timeout=0.1)
    assert result["reason"] == "computation_timeout" and not result["verified"]


def test_saved_script_uses_actual_source_not_declared_high_risk_or_kind(
    root, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        script_skills, "__file__", str(tmp_path / "core/script_skills.py")
    )
    folder = root / "code/skills"
    folder.mkdir(parents=True)
    path = folder / "saved.py"
    path.write_text("print(5)")
    store = SkillRegistry(tmp_path / "storage/autonomy")
    record = store.create(
        "sum",
        "Compute sum",
        [
            {
                "capability": "code_helper",
                "inputs": {"action": "run", "file_path": str(path)},
            }
        ],
        permissions=["server.script.execute"],
        risk_level="HIGH",
        provenance={
            "template": "approved_script_v1",
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    )
    assert not action_policy.requires_confirmation(
        "skill_manager", {"operation": "run", "skill_id": record["skill_id"]}
    )
    path.write_text("print(6)")
    assert action_policy.requires_confirmation(
        "skill_manager",
        {"operation": "run", "kind": "pure", "skill_id": record["skill_id"]},
    )


def test_external_or_symlink_scripts_are_not_auto_approved(root, tmp_path):
    outside = tmp_path / "external.py"
    outside.write_text("print(5)")
    assert scripts.validated_source(outside) is None
    link = root / "link.py"
    link.symlink_to(outside)
    assert scripts.validated_source(link) is None


def test_inert_source_creation_needs_no_execution_approval(root, monkeypatch):
    monkeypatch.setattr(action_policy, "ARTIFACT_ROOT", root)
    assert not action_policy.requires_confirmation(
        "code_helper",
        {
            "action": "write",
            "description": "Compute a sum",
            "output_path": str(root / "compute.py"),
        },
    )
    assert action_policy.requires_confirmation(
        "code_helper", {"action": "build", "description": "Run arbitrary code"}
    )


def test_source_write_does_not_execute_or_overwrite(root, monkeypatch):
    from actions import code_helper
    from types import SimpleNamespace

    monkeypatch.setattr(code_helper, "ARTIFACT_ROOT", root)
    monkeypatch.setattr(
        code_helper,
        "_get_gemini",
        lambda: SimpleNamespace(
            generate_content=lambda prompt: SimpleNamespace(text="print(5)")
        ),
    )
    path = root / "compute.py"
    path.write_text("original")
    result = json.loads(
        code_helper._write_action("Compute five", "python", str(path), None)
    )
    assert result["verified"] and result["code_executed"] is False
    assert Path(result["file_path"]) != path and path.read_text() == "original"
    assert Path(result["file_path"]).read_text() == "print(5)"


def test_classification_saved_at_creation_and_reused_until_code_or_policy_changes(
    root, monkeypatch
):
    from actions import code_helper
    from types import SimpleNamespace

    monkeypatch.setattr(code_helper, "ARTIFACT_ROOT", root)
    monkeypatch.setattr(
        code_helper,
        "_get_gemini",
        lambda: SimpleNamespace(
            generate_content=lambda prompt: SimpleNamespace(text="print(5)")
        ),
    )
    analyze = scripts._analyze_source
    analyses = []

    def track(source):
        analyses.append(source)
        return analyze(source)

    monkeypatch.setattr(scripts, "_analyze_source", track)
    created = json.loads(
        code_helper._write_action("Compute", "python", str(root / "cached.py"), None)
    )
    path = Path(created["file_path"])
    assert len(analyses) == 1
    assert scripts.validated_source(path) == "print(5)"
    assert scripts.run_checked(path)["task_result"].strip() == "5"
    assert len(analyses) == 1
    path.write_text("print(6)")
    assert scripts.validated_source(path) == "print(6)" and len(analyses) == 2
    monkeypatch.setattr(script_assessment, "POLICY_VERSION", "changed-policy")
    assert scripts.validated_source(path) == "print(6)" and len(analyses) == 3


def test_cached_decision_survives_fresh_reader_without_model_or_analysis(
    root, monkeypatch
):
    path = make(root, "print(5)")
    assert scripts.validated_source(path)
    monkeypatch.setattr(
        scripts,
        "_analyze_source",
        lambda source: pytest.fail("Already assessed source must use stored verdict"),
    )
    assert scripts.run_checked(path)["verified"]
    assert list(script_assessment.ASSESSMENT_ROOT.glob("*.json"))


def test_saved_low_risk_script_metadata_is_assigned_at_registration(
    root, tmp_path, monkeypatch
):
    from actions import code_helper

    monkeypatch.setattr(code_helper, "ARTIFACT_ROOT", root)

    def build(description, language, path, args, timeout, **kwargs):
        Path(path).write_text("print(5)")
        return json.dumps(
            {
                "status": "UNVERIFIED",
                "process_verified": True,
                "executed": True,
                "file_path": path,
                "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            }
        )

    monkeypatch.setattr(code_helper, "_build", build)
    store = SkillRegistry(tmp_path / "storage/autonomy")
    result = script_skills.build_script_skill(store, tmp_path, "sum", "Compute", {})
    record = store.get(result["skill_id"])
    assert record["risk_level"] == "LOW" and record["permissions"] == []
    assert (
        record["provenance"]["risk_assessment"]["source_sha256"]
        == record["provenance"]["source_sha256"]
    )
    assert (
        record["provenance"]["risk_assessment"]["policy_version"]
        == script_assessment.POLICY_VERSION
    )


@pytest.mark.parametrize(
    "body",
    [
        'return __builtins__["open"]("/etc/passwd").read()',
        'import json\n    return json.codecs.open("/etc/passwd").read()',
        "import collections\n    return collections._sys.modules",
        'return help("antigravity")',
    ],
)
def test_pure_policy_rejects_indirect_host_access(body):
    from core.skill_crucible import SkillCrucible, SkillPolicyError

    source = "def execute(**kwargs):\n    " + body
    with pytest.raises(SkillPolicyError):
        SkillCrucible.validate_source(source)
