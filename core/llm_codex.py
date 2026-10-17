"""Text reasoning through the official Codex CLI and its existing login state."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def executable() -> str:
    binary = shutil.which("codex")
    if not binary:
        raise RuntimeError("Codex CLI missing. Install: npm install -g @openai/codex; then codex login --device-auth")
    return binary


def _account_env():
    return {k: v for k, v in os.environ.items()
            if not (k.upper().endswith("_API_KEY") or k.upper().endswith("_TOKEN"))}


def check_login() -> None:
    """Ask the CLI about auth; never open or copy its token files."""
    try:
        result = subprocess.run([executable(), "login", "status"],
                                capture_output=True, text=True, timeout=15, check=False, env=_account_env())
    except subprocess.TimeoutExpired:
        raise RuntimeError("Codex login status timed out") from None
    status = (getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or "")
    if result.returncode or "chatgpt" not in status.lower():
        raise RuntimeError("Codex is not signed in with ChatGPT. Run: codex login --device-auth as the Mark server user")


def generate_text(model: str, prompt: str, *, timeout: float = 120.0) -> str:
    if not model.strip() or not prompt.strip():
        raise ValueError("Model and prompt are required")
    check_login()
    # Do not inherit server API keys into an account-auth text subprocess.
    env = _account_env()
    # Empty cwd, read-only sandbox and disabled shell: no Mark tools/actions are
    # delegated to the CLI. Authentication remains managed by Codex itself.
    with tempfile.TemporaryDirectory(prefix="mark-codex-") as workspace:
        output = Path(workspace) / "answer.txt"
        command = [executable(), "--ask-for-approval", "never", "exec",
                   "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                   "--sandbox", "read-only", "-c", "features.shell_tool=false",
                   "-c", 'web_search="disabled"', "--model", model,
                   "--output-last-message", str(output), "-"]
        try:
            result = subprocess.run(command, input=prompt, text=True, cwd=workspace,
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Codex text request timed out") from None
        if result.returncode:
            # CLI stderr can contain prompt fragments; do not forward it.
            raise RuntimeError("Codex text request failed; check CLI version, login and model access")
        if not output.is_file() or output.stat().st_size > 4 * 1024 * 1024:
            raise RuntimeError("Codex returned an invalid text response")
        answer = output.read_text(encoding="utf-8").strip()
        if not answer:
            raise RuntimeError("Codex returned an empty answer")
        return answer
