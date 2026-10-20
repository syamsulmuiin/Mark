"""Safety primitives for Mark self-repair.

This module is policy/transaction infrastructure, not a model-facing tool.  The
repair actions may call it, but autonomous repair is forbidden from modifying
this file or weakening its policy.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import shutil
import stat
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "storage" / "self_repair"
TX_DIR = STATE_DIR / "transactions"
KNOWLEDGE_DIR = STATE_DIR / "knowledge"
AUDIT_FILE = STATE_DIR / "audit.jsonl"
MAX_FILES = 8
MAX_DIFF_CHARS = 60000
MAX_ATTEMPTS = 3
VALIDATION_TIMEOUT = 120

# Immutable to the autonomous repair path. Human development may change these
# through the normal repository workflow, but the agent itself cannot.
PROTECTED_EXACT = {
    "core/repair_engine.py",
    "core/hotkey.py",
    "core/agent_worker.py",
    "core/autonomy_engine.py",
    "core/autonomy_state.py",
    "core/server_lifecycle.py",
    "actions/autonomous_goal.py",
    "main.py",
    "actions/self_repair_apply.py",
    "actions/self_repair_diagnostic.py",
    "core/action_loader.py",
    "core/plugin_loader.py",
    "core/confirm.py",
    "core/action_policy.py",
    "core/local_api_auth.py",
    "core/server_export_policy.py",
    "core/llm_proposal_handoff.py",
    "core/undo.py",
    "config/api_keys.json",
    "requirements.txt",
    "setup.py",
}
PROTECTED_PREFIXES = (
    ".git/", "config/", "devices/", "runtime/", "storage/", ".github/workflows/",
)
SENSITIVE_RE = re.compile(r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|cookie|authorization)\s*[:=]\s*([^\s,;]+)")


class RepairPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class RepairPolicy:
    risk: str
    max_files: int = MAX_FILES
    max_diff_chars: int = MAX_DIFF_CHARS
    max_attempts: int = MAX_ATTEMPTS


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def redact(value: str) -> str:
    return SENSITIVE_RE.sub(lambda m: f"{m.group(1)}=<redacted>", str(value))


def audit(event: str, **fields) -> None:
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": int(time.time()), "event": event}
    for key, value in fields.items():
        if isinstance(value, str):
            record[key] = redact(value)
        else:
            record[key] = value
    with AUDIT_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_rel(rel: str) -> str:
    raw = str(rel or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or "\x00" in raw:
        raise RepairPolicyError("invalid repair path")
    p = Path(raw)
    if any(part in {"", ".", ".."} for part in p.parts):
        raise RepairPolicyError("path traversal is not allowed")
    normalized = p.as_posix()
    current = BASE_DIR
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise RepairPolicyError("symlink repair targets are not allowed")
    resolved = (BASE_DIR / normalized).resolve()
    try:
        resolved.relative_to(BASE_DIR.resolve())
    except ValueError as exc:
        raise RepairPolicyError("repair path escapes repository") from exc
    return normalized


def is_protected(rel: str) -> bool:
    rel = normalize_rel(rel).casefold()
    return rel in {name.casefold() for name in PROTECTED_EXACT} or any(rel.startswith(prefix.casefold()) for prefix in PROTECTED_PREFIXES)


def classify_risk(requested: str, files: Iterable[str], new_texts: Iterable[str]) -> str:
    requested = str(requested or "").lower().strip()
    if requested not in {"low", "medium", "high"}:
        raise RepairPolicyError("risk must be low, medium, or high")
    joined = "\n".join(files).lower() + "\n" + "\n".join(new_texts).lower()
    high_markers = ("auth", "credential", "permission", "privilege", "database migration", "subprocess", "os.system", "remote execution")
    medium_markers = ("network", "socket", "async", "thread", "database", "api", "routing")
    minimum = "high" if any(x in joined for x in high_markers) else "medium" if any(x in joined for x in medium_markers) else "low"
    order = {"low": 0, "medium": 1, "high": 2}
    return requested if order[requested] >= order[minimum] else minimum


def enforce_policy(files: list[str], replacement_chars: int, risk: str, high_risk_approval: bool) -> RepairPolicy:
    normalized = [normalize_rel(x) for x in files]
    if len({name.casefold() for name in normalized}) != len(normalized):
        raise RepairPolicyError("duplicate repair file")
    if len(normalized) > MAX_FILES:
        raise RepairPolicyError(f"repair exceeds file budget ({MAX_FILES})")
    if replacement_chars > MAX_DIFF_CHARS:
        raise RepairPolicyError(f"repair exceeds change budget ({MAX_DIFF_CHARS} chars)")
    bad = [x for x in normalized if is_protected(x)]
    if bad:
        raise RepairPolicyError("protected safety area cannot be modified: " + ", ".join(bad))
    if risk == "high" and not high_risk_approval:
        raise RepairPolicyError("HIGH risk repair requires explicit HIGH_RISK_REPAIR_APPROVED approval")
    return RepairPolicy(risk=risk)


def begin_transaction(request: str, risk: str, originals: dict[str, str], validation_plan: list[str]) -> str:
    txid = f"{int(time.time())}-{uuid.uuid4().hex[:10]}"
    root = TX_DIR / txid
    (root / "snapshot").mkdir(parents=True, exist_ok=False)
    manifest = {
        "id": txid, "status": "PREPARED", "request": redact(request), "risk": risk,
        "created_at": int(time.time()), "validation_plan": validation_plan,
        "files": [], "attempt": 1,
    }
    for rel, text in originals.items():
        target = root / "snapshot" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        manifest["files"].append({"path": rel, "sha256": sha256_text(text)})
    _atomic_json(root / "manifest.json", manifest)
    audit("transaction_prepared", transaction=txid, risk=risk, files=list(originals), request=request)
    return txid


def _atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def _transaction_manifest(txid: str):
    if not isinstance(txid, str) or not re.fullmatch(r'[0-9]+-[0-9a-f]{10}', txid):
        raise RepairPolicyError('invalid transaction identifier')
    root = TX_DIR / txid
    manifest = root / 'manifest.json'
    if root.is_symlink() or manifest.is_symlink() or root.resolve().parent != TX_DIR.resolve():
        raise RepairPolicyError('transaction path is not trusted')
    obj = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(obj, dict) or obj.get('id') != txid:
        raise RepairPolicyError('transaction manifest identity mismatch')
    return root, obj


def set_status(txid: str, status: str, **extra) -> None:
    root, obj = _transaction_manifest(txid)
    obj['status'] = status; obj.update(extra); obj['updated_at'] = int(time.time())
    _atomic_json(root / 'manifest.json', obj)
    audit('transaction_status', transaction=txid, status=status, **extra)


def rollback(txid: str) -> list[str]:
    root, manifest = _transaction_manifest(txid)
    files = manifest.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise RepairPolicyError('invalid rollback file list')
    prepared = []
    seen = set()
    # Check every snapshot before restoring any source. A damaged later file
    # must not cause an otherwise avoidable partial rollback.
    for item in files:
        if not isinstance(item, dict):
            raise RepairPolicyError('invalid rollback file entry')
        rel = normalize_rel(item.get('path', ''))
        if is_protected(rel) or rel.casefold() in seen:
            raise RepairPolicyError('rollback target is protected or duplicated')
        seen.add(rel.casefold())
        snapshot = root / 'snapshot' / rel
        current = root
        for part in snapshot.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise RepairPolicyError('symlink rollback snapshots are not allowed')
        text = snapshot.read_text(encoding='utf-8')
        if sha256_text(text) != item.get('sha256'):
            raise RepairPolicyError('rollback snapshot integrity check failed')
        prepared.append((rel, text))
    restored = []
    for rel, text in prepared:
        _atomic_write(BASE_DIR / rel, text)
        restored.append(rel)
    set_status(txid, 'ROLLED_BACK', restored=restored)
    return restored


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.repair-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def write_candidate(rel: str, text: str) -> None:
    _atomic_write(BASE_DIR / normalize_rel(rel), text)


def _imported_modules(path: Path, module: str = "") -> set[str]:
    """Collect static imports, including package-relative imports, without execution."""
    import ast
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return set()
    modules = set()
    package = module.split(".")[:-1]
    if path.name == "__init__.py":
        package = module.split(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package):
                    continue
                prefix = package[:len(package) - node.level + 1]
                base = ".".join(prefix + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if base:
                modules.add(base)
            # from . import sibling / from pkg import child
            for alias in node.names:
                if alias.name != "*" and base:
                    modules.add(base + "." + alias.name)
    return modules


def select_related_tests(root: Path, changed_files: list[str]) -> list[str]:
    """Conservative direct/reverse import graph; full suite still runs afterward."""
    import ast
    root = Path(root)
    tests = root / "tests"
    if not tests.is_dir():
        return []
    source_modules = set()
    for rel in changed_files:
        path = Path(str(rel))
        if path.suffix != ".py":
            continue
        parts = path.with_suffix("").parts
        if parts and parts[0] in {"core", "actions", "dashboard", "memory", "plugins"}:
            source_modules.add(".".join(parts))
        elif path.name == "main.py":
            source_modules.add("main")
    if not source_modules:
        return []
    py_files = [p for directory in ("core", "actions", "dashboard", "memory", "plugins", "tests")
                for p in (root / directory).rglob("*.py") if (root / directory).is_dir()]
    py_files += [root / "main.py"] if (root / "main.py").is_file() else []
    graph = {}
    for p in py_files:
        module = ".".join(p.relative_to(root).with_suffix("").parts)
        if p.name == "__init__.py":
            module = module.removesuffix(".__init__")
        graph[module] = _imported_modules(p, module)
    impacted = set(source_modules)
    while True:
        next_impacted = impacted | {module for module, imports in graph.items()
            if any(used == changed or used.startswith(changed + ".")
                   for used in imports for changed in impacted)}
        if next_impacted == impacted:
            break
        impacted = next_impacted
    selected = []
    for p in sorted(tests.glob("test_*.py")):
        module = ".".join(p.relative_to(root).with_suffix("").parts)
        if module in impacted or any(used == changed or used.startswith(changed + ".")
                                     for used in graph.get(module, ()) for changed in impacted):
            selected.append(p.relative_to(root).as_posix())
    return selected


def _validator_environment(root: Path, home: Path) -> dict[str, str]:
    # Keep runtime discovery/locale, never inherit provider tokens, Python hooks,
    # user configuration homes, or arbitrary deployment secrets.
    allowed = ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
               'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'SYSTEMDRIVE')
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    temporary = home / 'tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / 'AppData' / 'Roaming'),
               LOCALAPPDATA=str(home / 'AppData' / 'Local'), XDG_CONFIG_HOME=str(home / '.config'),
               XDG_CACHE_HOME=str(home / '.cache'), TMPDIR=str(temporary), TEMP=str(temporary), TMP=str(temporary),
               PYTHONPATH=str(root), PYTHONNOUSERSITE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    return env


def _run_validators(root: Path, changed_files: list[str], timeout: int) -> tuple[bool, list[dict]]:
    if importlib.util.find_spec("pytest") is None:
        return False, [{"command": "repair validation preflight", "returncode": -1,
            "output": "pytest is missing from the server interpreter. Run python -m pip install -r requirements.txt, then retry the reviewed repair."}]
    related = select_related_tests(root, changed_files)
    commands = [
        [sys.executable, "-c", "import core.repair_engine, actions.self_repair_apply, actions.self_repair_diagnostic"],
        [sys.executable, "-m", "compileall", "-q", "actions", "core", "dashboard", "main.py"],
        [sys.executable, "-m", "pytest", "-q", "tests"],
    ]
    if related:
        commands.insert(2, [sys.executable, "-m", "pytest", "-q", *related])
    results = []
    with tempfile.TemporaryDirectory(prefix='mark-validator-home-') as temporary_home:
        env = _validator_environment(root, Path(temporary_home))
        for cmd in commands:
            started = time.monotonic()
            try:
                proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout, env=env)
                result = {"command": " ".join(cmd), "returncode": proc.returncode, "duration_ms": int((time.monotonic()-started)*1000), "output": redact((proc.stdout + proc.stderr)[-4000:])}
            except subprocess.TimeoutExpired:
                result = {"command": " ".join(cmd), "returncode": -1, "duration_ms": int((time.monotonic()-started)*1000), "output": "validation timeout"}
            except OSError as exc:
                result = {"command": " ".join(cmd), "returncode": -1,
                    "duration_ms": int((time.monotonic()-started)*1000), "error_type": type(exc).__name__,
                    "stage": "validator_launch", "output": "Validator could not start; inspect interpreter access and OS resources."}
            results.append(result); audit("validation", files=changed_files, root=str(root), **result)
            if result["returncode"] != 0:
                return False, results

    return True, results


def _validation_copy_ignored(directory, names):
    ignored = shutil.ignore_patterns('.git', '.venv', 'venv', '__pycache__', 'storage',
        'build', 'dist', '.pytest_cache', 'pytest-of-root',
        'provider_auth', 'api_keys.json', 'credentials.json', 'token*.json', '.env', '.env.*',
        '*.key', '*.pem', '*.p12', '*.pfx')(directory, names)
    # Runtime state exists at the server root; the desktop's nested runtime
    # directory is application source and must remain in the validation checkout.
    if Path(directory).resolve() == BASE_DIR.resolve():
        ignored.update(name for name in names if name in {'runtime', 'devices'})
    return set(ignored) | {name for name in names if (Path(directory) / name).is_symlink()}


def validate_sandbox(candidates: dict[str, str], timeout: int = VALIDATION_TIMEOUT) -> tuple[bool, list[dict]]:
    """Validate in a filtered temporary copy; this is not OS-level isolation."""
    stage = 'prepare_copy'
    try:
        with tempfile.TemporaryDirectory(prefix="mark-repair-sandbox-") as td:
            root = Path(td) / "repo"
            stage = 'copy_source'
            shutil.copytree(BASE_DIR, root, ignore=_validation_copy_ignored)
            stage = 'write_candidates'
            for rel, text in candidates.items():
                target = root / normalize_rel(rel); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text, encoding="utf-8")
            stage = 'run_validators'
            return _run_validators(root, list(candidates), timeout)
    except (OSError, UnicodeError, RepairPolicyError) as exc:
        return False, [{"command": "candidate validation", "returncode": -1,
            "stage": stage, "error_type": type(exc).__name__,
            "output": "Candidate validation could not complete; production source was not written."}]



def validate_repository(changed_files: list[str], timeout: int = VALIDATION_TIMEOUT) -> tuple[bool, list[dict]]:
    """Fixed post-write health validators; never executes model/user commands."""
    return _run_validators(BASE_DIR, changed_files, timeout)



def recover_incomplete_transactions() -> list[str]:
    """Rollback transactions interrupted before ACCEPTED/ROLLED_BACK.

    Called before a new repair. It never touches accepted transactions.
    """
    recovered = []
    failed = False
    if not TX_DIR.exists():
        return recovered
    for manifest_path in sorted(TX_DIR.glob("*/manifest.json")):
        try:
            obj = json.loads(manifest_path.read_text(encoding="utf-8"))
            status = obj.get("status")
            if status not in {"PREPARED", "CANDIDATE_WRITTEN"}:
                continue
            txid = manifest_path.parent.name
            _, obj = _transaction_manifest(txid)
            if status == "PREPARED":
                # No production write has started: do not overwrite unrelated edits.
                set_status(txid, "ROLLED_BACK", restored=[])
            else:
                rollback(txid)
            recovered.append(txid)
            audit("transaction_recovered_after_interruption", transaction=txid)
        except Exception as exc:
            failed = True
            audit("transaction_recovery_failed", transaction=manifest_path.parent.name, error_type=type(exc).__name__)
    if failed:
        raise RepairPolicyError('Incomplete transaction recovery failed; inspect snapshots before starting another repair')
    return recovered

def record_knowledge(kind: str, payload: dict) -> Path:
    if kind not in {"incidents", "fixes", "patterns", "failures", "environment", "architecture"}:
        raise RepairPolicyError("invalid knowledge category")
    root = KNOWLEDGE_DIR / kind
    root.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("timestamp", int(time.time()))
    payload.setdefault("confidence", "EXPERIMENTAL")
    payload.setdefault("validation_status", "candidate")
    path = root / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.json"
    _atomic_json(path, payload)
    audit("knowledge_recorded", kind=kind, path=str(path.relative_to(BASE_DIR)))
    return path


def search_knowledge(problem: str, limit: int = 5) -> list[dict]:
    terms = {x for x in re.findall(r"[a-z0-9_]{4,}", problem.lower())}
    scored = []
    if not KNOWLEDGE_DIR.exists():
        return []
    for path in KNOWLEDGE_DIR.rglob("*.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = json.dumps(obj, ensure_ascii=False).lower()
        score = sum(1 for term in terms if term in text)
        if score:
            scored.append((score, path.stat().st_mtime, obj))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [x[2] for x in scored[:limit]]
