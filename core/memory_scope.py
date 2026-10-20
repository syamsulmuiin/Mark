"""Current non-secret runtime scope for automatic procedural-memory retrieval."""
import platform
import subprocess
from pathlib import Path


def current_scope(base_dir=None):
    environment = {'os': platform.system(), 'machine': platform.machine(),
                   'python': platform.python_version()}
    commit = ''
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'],
            cwd=base_dir or Path(__file__).resolve().parents[1], capture_output=True,
            text=True, timeout=2, check=True)
        commit = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return environment, commit
