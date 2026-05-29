from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..deps import require_roles
from ..paths import repo_root, resolve_workdir_under_repo

router = APIRouter(
    prefix="/openfdd-agent",
    tags=["agent"],
    dependencies=[Depends(require_roles("integrator", "agent"))],
)


class ChatBody(BaseModel):
    message: str
    workdir: str | None = None


class ContextResponse(BaseModel):
    bridge_base: str = "http://127.0.0.1:8765"
    repo_root: str
    codex_available: bool
    agent_shell: str = "openfdd-agent-shell --repo-root ."
    note: str


@router.get("/context")
def agent_context() -> dict:
    root = repo_root()
    codex = shutil.which("codex") or shutil.which("codex.cmd")
    return {
        "bridge_base": os.environ.get("OFDD_PUBLIC_BRIDGE_BASE", "http://127.0.0.1:8765"),
        "repo_root": str(root),
        "mcp_rest_base": os.environ.get("OFDD_MCP_REST_BASE", "http://127.0.0.1:8090"),
        "ui_public_base": os.environ.get("OFDD_UI_PUBLIC_BASE", "http://127.0.0.1:5173"),
        "codex_available": bool(codex),
        "agent_shell": f"openfdd-agent-shell --repo-root {root}",
        "note": "Use Cursor, Codex CLI, or OpenClaw on this repo. Python Rule Lab + BRICK model at /api/model/export. Update building alerts via PUT /api/building/alerts.",
    }


@router.post("/chat")
def agent_chat(body: ChatBody) -> dict:
    """Thin Codex exec when CLI is on PATH; otherwise return operator guidance."""
    root = resolve_workdir_under_repo(body.workdir)
    codex = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex:
        return {
            "ok": True,
            "mode": "guidance",
            "reply": (
                "Codex CLI not found on bridge host PATH. "
                "Run openfdd-agent-shell locally, or install Codex and codex login. "
                f"Your message was recorded ({len(body.message)} chars)."
            ),
        }
    cmd = [
        codex,
        "exec",
        "--cd",
        str(root),
        "-m",
        body.message[:8000],
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("OFDD_CODEX_EXEC_TIMEOUT_S", "300")),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "mode": "codex", "error": "codex exec timed out"}
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "ok": proc.returncode == 0,
        "mode": "codex",
        "exit_code": proc.returncode,
        "reply": out[-12000:],
    }
