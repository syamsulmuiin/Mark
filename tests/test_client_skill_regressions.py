"""Regressions from Android model/skill/CSV acceptance logs."""

import json
import sys
from types import SimpleNamespace

from actions import skill_manager as manager
from core import skill_catalog, llm_action_proposals, llm_text
from core.action_outcomes import assess, trace_metadata
from core.skill_registry import SkillRegistry
from core.dynamic_skill_registry import DynamicSkillRegistry


def test_list_includes_real_callable_schema_and_verifies_only_listing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(manager, "BASE_DIR", tmp_path)
    store = SkillRegistry(tmp_path / "storage/autonomy")
    record = store.create("count_words", "Count words", [], skill_type="GENERATED")
    record.update(status="VERIFIED", operational_state="ACTIVE")
    store._save(record)
    dynamic = DynamicSkillRegistry(tmp_path / "storage/autonomy", store)
    dynamic.install_verified(
        record,
        'def execute(**kwargs):\n    return len(kwargs["text"].split())',
        {
            "parameters": {
                "type": "OBJECT",
                "properties": {"text": {"type": "STRING", "default": "private-value"}},
                "required": ["text"],
            }
        },
        {"ok": True},
    )
    result = json.loads(manager.skill_manager({"operation": "list"}))
    assert assess(result) == "VERIFIED"
    assert "metadata only" in result["verification_scope"]
    assert result["skills"][0]["parameters"]["properties"] == {
        "text": {"type": "STRING"}
    }
    assert "private-value" not in json.dumps(result)
    # Fresh handler reads the installed schema and executes the same ID after restart.
    actual = json.loads(
        manager.skill_manager(
            {
                "operation": "run",
                "skill_id": record["skill_id"],
                "inputs": {"text": "Mark siap diuji"},
            }
        )
    )
    assert actual["result"] == 3 and assess(actual) == "VERIFIED"


def test_text_proposal_receives_saved_skill_context(monkeypatch):
    sid = "a" * 32
    monkeypatch.setattr(
        skill_catalog,
        "proposal_context",
        lambda: {"skills": [{"skill_id": sid, "parameters": {"text": "STRING"}}]},
    )
    seen = []

    def generate(prompt, **kwargs):
        seen.append(prompt)
        return json.dumps(
            {
                "tool": "skill_manager",
                "args": {
                    "operation": "run",
                    "skill_id": sid,
                    "inputs": {"text": "Mark siap diuji"},
                },
                "reason": "Use saved skill",
            }
        )

    monkeypatch.setattr(llm_text, "generate", generate)
    proposal = llm_action_proposals.propose_action(
        "Run my saved word counter", [{"name": "skill_manager"}]
    )
    assert sid in seen[0] and "input schema" in seen[0]
    assert proposal["args"]["operation"] == "run"
    assert proposal["executed"] is False


def test_csv_reader_uses_supported_encoding_parameter(tmp_path, monkeypatch):
    from actions import file_processor

    path = tmp_path / "numbers.csv"
    path.write_text("value\n2\n3\n")
    calls = []

    class Columns(list):
        def tolist(self):
            return list(self)

    class Frame:
        columns = Columns(["value"])

        def __len__(self):
            return 2

    def read_csv(path, *, encoding, encoding_errors):
        calls.append((encoding, encoding_errors))
        return Frame()

    monkeypatch.setitem(sys.modules, "pandas", SimpleNamespace(read_csv=read_csv))
    result = file_processor._process_data(path, "csv", "info", {})
    assert "Rows: 2, Columns: 1" in result
    assert calls == [("utf-8", "replace")]


def test_file_read_failure_is_not_a_successful_inspection():
    assert assess("Could not read file: parser failure") == "FAILED"


def test_trace_metadata_never_logs_inputs_exception_messages_or_paths():
    result = {
        "status": "FAILED",
        "reason": "source_file_missing",
        "error_type": "ValueError",
        "error": "token=private-key /root/private",
        "file_path": "/root/private",
        "result": "secret contents",
    }
    args = {"operation": "run", "kind": "pure", "inputs": {"token": "private-key"}}
    details = trace_metadata(json.dumps(result), args)
    assert details == {
        "status": "FAILED",
        "reason": "source_file_missing",
        "error_type": "ValueError",
        "operation": "run",
        "kind": "pure",
    }
    assert "private" not in json.dumps(details)
    assert trace_metadata(
        {"reason": "credential=private", "error_type": ["unsafe"]}
    ) == {"reason": "postcondition_unverified"}


def test_catalog_bounds_and_never_exposes_script_source(tmp_path):
    store = SkillRegistry(tmp_path)
    for index in range(3):
        store.create(
            "script_" + str(index),
            "Script task",
            [
                {
                    "capability": "code_helper",
                    "inputs": {"file_path": "/private/script.py"},
                }
            ],
            provenance={
                "parameters": {
                    "properties": {"rows": {"type": "ARRAY", "default": "secret"}}
                }
            },
        )
    result = skill_catalog.catalog(
        store, DynamicSkillRegistry(tmp_path, store), limit=2
    )
    assert len(result["skills"]) == 2 and result["truncated"]
    assert "/private" not in json.dumps(result) and "secret" not in json.dumps(result)
