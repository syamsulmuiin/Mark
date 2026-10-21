"""Host classification and snapshot execution for computation-only Python scripts."""

from __future__ import annotations
import ast
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from core.artifact_paths import ARTIFACT_ROOT

CALLS = {
    "print",
    "len",
    "sum",
    "min",
    "max",
    "sorted",
    "range",
    "enumerate",
    "zip",
    "abs",
    "round",
    "str",
    "int",
    "float",
    "bool",
    "list",
    "tuple",
    "dict",
    "set",
    "all",
    "any",
    "isinstance",
    "ValueError",
    "TypeError",
    "Exception",
}
METHODS = {
    "split",
    "strip",
    "lower",
    "upper",
    "join",
    "get",
    "items",
    "keys",
    "values",
    "count",
    "append",
    "extend",
    "sort",
    "replace",
    "startswith",
    "endswith",
    "isdigit",
    "isalpha",
    "add",
    "update",
    "pop",
}


def _analyze_source(source):
    try:
        tree = ast.parse(source)
        functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    a.name not in {"json", "math", "sys"} or a.asname
                    for a in node.names
                ):
                    return None
            if isinstance(
                node,
                (
                    ast.ImportFrom,
                    ast.ClassDef,
                    ast.Global,
                    ast.Nonlocal,
                    ast.With,
                    ast.AsyncWith,
                ),
            ):
                return None
            if (
                isinstance(node, ast.Name)
                and node.id.startswith("__")
                and node.id != "__name__"
            ):
                return None
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == "json":
                    if node.attr not in {"loads", "dumps"}:
                        return None
                elif isinstance(node.value, ast.Name) and node.value.id == "math":
                    import math

                    if node.attr.startswith("_") or not hasattr(math, node.attr):
                        return None
                elif isinstance(node.value, ast.Name) and node.value.id == "sys":
                    if node.attr != "argv":
                        return None
                elif node.attr not in METHODS:
                    return None
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id not in CALLS | functions:
                        return None
                elif not isinstance(node.func, ast.Attribute):
                    return None

        # Every sys reference must be the current JSON argument, never stdout,
        # modules, interpreter state, environment, imports or another file.
        class Normalize(ast.NodeTransformer):
            def visit_Import(self, node):
                node.names = [a for a in node.names if a.name != "sys"]
                return node if node.names else None

            def visit_Subscript(self, node):
                if (
                    isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "sys"
                    and node.value.attr == "argv"
                    and isinstance(node.slice, ast.Constant)
                    and node.slice.value == 1
                ):
                    return ast.copy_location(
                        ast.Name(id="_mark_input_json", ctx=ast.Load()), node
                    )
                return self.generic_visit(node)

        normalized = Normalize().visit(tree)
        wrapped = 'def execute(_mark_input_json="", **kwargs):\n' + "\n".join(
            "    " + line for line in ast.unparse(normalized).splitlines()
        )
        from core.skill_crucible import SkillCrucible

        SkillCrucible.validate_source(wrapped)
        return True
    except (ValueError, TypeError, SyntaxError):
        return False


def source_assessment(path):
    try:
        path = Path(path)
        path.resolve().relative_to(ARTIFACT_ROOT.resolve())
        if (
            path.suffix != ".py"
            or path.resolve() != path
            or not path.is_file()
            or path.stat().st_size > 64000
        ):
            return None
        source = path.read_bytes().decode("utf-8")
        from core.script_assessment import assessment

        return source, assessment(source, _analyze_source)
    except (OSError, ValueError, TypeError):
        return None


def validated_source(path):
    checked = source_assessment(path)
    return (
        checked[0] if checked is not None and checked[1]["computation_only"] else None
    )


def run_checked(path, args=None, timeout=5, *, expected_sha256=None):
    source = validated_source(path)
    if source is None:
        raise ValueError("script_effects_not_verified_as_computation_only")
    if (
        expected_sha256 is not None
        and hashlib.sha256(source.encode()).hexdigest() != expected_sha256
    ):
        raise ValueError("saved_script_integrity_mismatch")
    # Execute this exact snapshot, never reopen the potentially changed file.
    prefix = (
        "try:\n import resource as _mark_resource\n"
        " _mark_resource.setrlimit(_mark_resource.RLIMIT_AS, (268435456, 268435456))\n"
        " _mark_resource.setrlimit(_mark_resource.RLIMIT_CPU, (5, 5))\n _mark_resource.setrlimit(_mark_resource.RLIMIT_FSIZE, (1048576, 1048576))\n"
        " del _mark_resource\nexcept ImportError:\n pass\n"
    )
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-c", prefix + source, *list(args or [])],
                stdout=stdout,
                stderr=stderr,
                cwd=tempfile.gettempdir(),
                env={"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=max(0.1, min(float(timeout), 5)),
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "FAILED",
                "verified": False,
                "executed": True,
                "reason": "computation_timeout",
            }
        stdout.seek(0, 2)
        length = stdout.tell()
        stdout.seek(max(0, length - 8000))
        output = stdout.read().decode("utf-8", errors="replace")
        stderr.seek(0, 2)
        error_length = stderr.tell()
        stderr.seek(max(0, error_length - 8000))
        error_output = stderr.read().decode("utf-8", errors="replace")
    ok = completed.returncode == 0
    return {
        "status": "SUCCESS" if ok else "FAILED",
        "verified": ok,
        "executed": True,
        "process_verified": ok,
        "output": output,
        "task_result": output,
        "stderr": error_output if not ok else "",
        "output_truncated": length > 8000,
        "error_type": "" if ok else "ComputationProcessError",
        "verification_scope": "checked computation process and captured output; semantic correctness is separate",
        "instruction": "Report the actual output in this response without asking the user to request it again. No filesystem/network/process authority was granted to this script.",
    }
