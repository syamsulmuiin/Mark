"""Bounded callable skill metadata; never expose source, outputs or credentials."""

from __future__ import annotations
import json
from pathlib import Path


def input_schema(inputs):
    return {
        "type": "OBJECT",
        "properties": {
            key: {
                "type": "BOOLEAN"
                if isinstance(value, bool)
                else "NUMBER"
                if isinstance(value, (int, float))
                else "ARRAY"
                if isinstance(value, list)
                else "OBJECT"
                if isinstance(value, dict)
                else "STRING"
            }
            for key, value in inputs.items()
        },
    }


def catalog(store, dynamic, *, limit=100):
    records = store.all()
    rows = []
    for record in records[:limit]:
        row = {
            key: record.get(key)
            for key in (
                "skill_id",
                "name",
                "purpose",
                "skill_type",
                "status",
                "operational_state",
            )
        }
        schema = None
        if record.get("skill_type") == "GENERATED":
            meta = dynamic.get(record["skill_id"]) or {}
            schema = (meta.get("manifest") or {}).get("parameters")
        else:
            schema = (record.get("provenance") or {}).get("parameters")
        if isinstance(schema, dict):
            # Only input names, types and required keys, never model-authored defaults.
            props = schema.get("properties") or {}
            row["parameters"] = {
                "type": "OBJECT",
                "properties": {
                    key: {"type": value.get("type", "STRING")}
                    for key, value in props.items()
                    if isinstance(key, str) and isinstance(value, dict)
                },
            }
            row["parameters"]["required"] = [
                key
                for key in schema.get("required", [])
                if key in row["parameters"]["properties"]
            ]
        rows.append(row)
    return {
        "status": "SUCCESS",
        "verified": True,
        "verification_scope": "readable skill registry metadata only; no skill executed",
        "skills": rows,
        "truncated": len(records) > limit,
        "instruction": "Listing is inspection only. To execute an existing skill, use operation=run with its exact skill_id and inputs matching parameters. Do not recreate it or repeat listing as task completion. Pure runs use host source/integrity validation without a popup; script execution requires host approval.",
    }


def proposal_context():
    from core.skill_registry import SkillRegistry
    from core.dynamic_skill_registry import DynamicSkillRegistry

    root = Path(__file__).resolve().parents[1] / "storage/autonomy"
    store = SkillRegistry(root)
    data = catalog(store, DynamicSkillRegistry(root, store), limit=30)
    while len(json.dumps(data, ensure_ascii=False)) > 12000 and data["skills"]:
        data["skills"].pop()
        data["truncated"] = True
    return data
