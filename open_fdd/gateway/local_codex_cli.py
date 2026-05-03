"""Resolve the OpenAI `codex` CLI on the host and run `login status` / `exec` (same pattern as a local Python harness)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

_DEFAULT_SYSTEM = """You are a local coding assistant.

Rules:
- Answer the human's latest question directly.
- Be practical and concise.
- If the user asks for code changes, inspect the local workspace and make safe edits.
- When editing code, explain what changed and why.
"""


def _decode_completed(cp: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": int(cp.returncode),
        "stdout": (cp.stdout or "").strip(),
        "stderr": (cp.stderr or "").strip(),
    }


def resolve_codex_executable() -> str | None:
    """Return path to `codex` (Windows: often `codex.cmd` under npm global)."""
    override = (os.environ.get("OFDD_CODEX_CMD") or "").strip()
    if override:
        p = Path(override)
        if p.is_file():
            return str(p.resolve())

    w = shutil.which("codex")
    if w:
        return w

    if os.name == "nt":
        for arg in ("codex.cmd", "codex"):
            try:
                r = subprocess.run(
                    ["where.exe", arg],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    encoding="utf-8",
                    errors="replace",
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if r.returncode != 0 or not (r.stdout or "").strip():
                continue
            first = (r.stdout or "").strip().splitlines()[0].strip().strip('"')
            if first and Path(first).is_file():
                return str(Path(first).resolve())
    return None


def npm_global_prefix() -> str | None:
    try:
        r = subprocess.run(
            ["npm", "config", "get", "prefix"],
            capture_output=True,
            text=True,
            timeout=25,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    s = (r.stdout or "").strip()
    return s or None


def where_codex_lines() -> list[str]:
    """Windows `where.exe` lines for troubleshooting (empty on non-Windows or failure)."""
    if os.name != "nt":
        return []
    lines: list[str] = []
    for arg in ("codex.cmd", "codex"):
        try:
            r = subprocess.run(
                ["where.exe", arg],
                capture_output=True,
                text=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.stdout:
            lines.extend([ln.strip() for ln in r.stdout.splitlines() if ln.strip()])
    return lines


def run_codex_login_status(codex_path: str) -> dict[str, Any]:
    try:
        cp = subprocess.run(
            [codex_path, "login", "status"],
            capture_output=True,
            text=True,
            timeout=90,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "codex login status timed out.", "logged_in": False}
    out = _decode_completed(cp)
    out["logged_in"] = cp.returncode == 0
    return out


def run_codex_exec(
    codex_path: str,
    workdir: Path,
    *,
    stdin_text: str,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    t = timeout_s if timeout_s is not None else int(os.environ.get("OFDD_CODEX_EXEC_TIMEOUT_S") or "600")
    t = max(30, min(t, 3600))
    try:
        cp = subprocess.run(
            [codex_path, "exec", "--skip-git-repo-check", "--color", "never", "-"],
            cwd=str(workdir),
            input=stdin_text,
            text=True,
            capture_output=True,
            timeout=t,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"codex exec timed out after {t}s.",
            "ok": False,
        }
    out = _decode_completed(cp)
    out["ok"] = cp.returncode == 0
    return out


def build_chat_stdin(*, user_message: str, system_context: str | None) -> str:
    system = (system_context or "").strip() or _DEFAULT_SYSTEM
    return f"{system}\n\nHuman message:\n{user_message.strip()}\n\nRespond to the human message above.\n"


def gather_diagnostics() -> dict[str, Any]:
    codex = resolve_codex_executable()
    npm = npm_global_prefix()
    where_lines = where_codex_lines()
    hints: list[str] = []
    if not codex:
        hints.extend(
            [
                "Install CLI: npm install -g @openai/codex",
                "PowerShell: where.exe codex.cmd",
                "PowerShell: where.exe codex",
                "PowerShell: npm config get prefix   (then look under node_modules\\.bin)",
                "Then in a terminal: codex login   or   codex login --device-auth",
                "Check: codex login status",
            ]
        )
    login: dict[str, Any] | None = None
    if codex:
        login = run_codex_login_status(codex)
        if not login.get("logged_in"):
            hints.extend(["Run: codex login", "Or: codex login --device-auth", "Then: codex login status"])
    return {
        "codex_path": codex,
        "npm_prefix": npm,
        "where_codex": where_lines,
        "login_status": login,
        "hints": hints,
    }


def resolve_workdir(raw: str | None) -> Path:
    if raw and str(raw).strip():
        p = Path(str(raw).strip()).expanduser().resolve(strict=False)
    else:
        env = (os.environ.get("OFDD_CODEX_WORKDIR") or "").strip()
        p = Path(env).expanduser().resolve(strict=False) if env else Path.cwd().resolve()
    return p
