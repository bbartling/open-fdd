from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .manifest import Manifest
from .prompts import build_system_prompt


@dataclass
class CodexInvocation:
    argv: list[str]
    system_prompt: str
    cwd: Path


def codex_available(codex_bin: str) -> bool:
    return shutil.which(codex_bin) is not None


def build_invocation(manifest: Manifest, user_message: str) -> CodexInvocation:
    system_prompt = build_system_prompt(manifest)
    argv = [
        manifest.codex_bin,
        "exec",
        "--cd",
        str(manifest.repo_root),
        "--full-auto",
        user_message,
    ]
    return CodexInvocation(argv=argv, system_prompt=system_prompt, cwd=manifest.repo_root)


def dry_run_command(invocation: CodexInvocation) -> str:
    return " ".join(_quote(arg) for arg in invocation.argv)


def _quote(value: str) -> str:
    if not value or any(ch.isspace() for ch in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def run_invocation(invocation: CodexInvocation) -> int:
    env = None
    proc = subprocess.run(
        invocation.argv,
        cwd=str(invocation.cwd),
        input=invocation.system_prompt,
        text=True,
    )
    return int(proc.returncode)
