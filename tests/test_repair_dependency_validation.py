"""Dependency-aware test selection must remain conservative and read-only."""
from pathlib import Path

from core.repair_engine import select_related_tests


def _write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_related_tests_include_transitive_import_dependents(tmp_path):
    _write(tmp_path, "core/leaf.py", "VALUE = 1\n")
    _write(tmp_path, "core/service.py", "from core.leaf import VALUE\n")
    _write(tmp_path, "actions/consumer.py", "from core.service import VALUE\n")
    _write(tmp_path, "tests/test_direct.py", "from core.leaf import VALUE\n")
    _write(tmp_path, "tests/test_indirect.py", "from actions.consumer import VALUE\n")
    _write(tmp_path, "tests/test_unrelated.py", "import json\n")
    selected = select_related_tests(tmp_path, ["core/leaf.py"])
    assert selected == ["tests/test_direct.py", "tests/test_indirect.py"]


def test_non_python_change_keeps_full_suite_only(tmp_path):
    _write(tmp_path, "tests/test_one.py", "assert True\n")
    assert select_related_tests(tmp_path, ["dashboard/static/index.html"]) == []


def test_missing_or_unparseable_imports_do_not_execute_code(tmp_path):
    _write(tmp_path, "core/leaf.py", "VALUE = 1\n")
    _write(tmp_path, "tests/test_bad.py", "not valid python !!!\n")
    assert select_related_tests(tmp_path, ["core/leaf.py"]) == []


def test_relative_imports_include_indirect_dependents(tmp_path):
    _write(tmp_path, "core/__init__.py", "")
    _write(tmp_path, "core/leaf.py", "VALUE = 1\n")
    _write(tmp_path, "core/service.py", "from .leaf import VALUE\n")
    _write(tmp_path, "actions/consumer.py", "from core import service\n")
    _write(tmp_path, "tests/test_consumer.py", "from actions.consumer import service\n")
    assert select_related_tests(tmp_path, ["core/leaf.py"]) == ["tests/test_consumer.py"]


def test_relative_package_import_from_init(tmp_path):
    _write(tmp_path, "core/__init__.py", "from . import leaf\n")
    _write(tmp_path, "core/leaf.py", "VALUE = 1\n")
    _write(tmp_path, "tests/test_package.py", "import core\n")
    assert select_related_tests(tmp_path, ["core/leaf.py"]) == ["tests/test_package.py"]
