from __future__ import annotations

import os
import shutil
import subprocess
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..deps import require_roles
from .. import ollama_client
from ..ollama_profiles import gpu_options_payload, tiers_payload
from ..paths import repo_root, resolve_workdir_under_repo

router = APIRouter(
    prefix="/openfdd-agent",
    tags=["agent"],
    dependencies=[Depends(require_roles("integrator", "agent"))],
)


class ChatBody(BaseModel):
    message: str
    workdir: str | None = None
    backend: Literal["auto", "ollama", "codex"] = "auto"
    ram_tier: str | None = None
    model: str | None = None
    gpu_mode: Literal["cpu", "auto", "gpu"] | None = None


@router.get("/context")
def agent_context() -> dict:
    root = repo_root()
    codex = shutil.which("codex") or shutil.which("codex.cmd")
    ollama = ollama_client.health()
    tier = ollama_client.configured_ram_tier()
    return {
        "bridge_base": os.environ.get("OFDD_PUBLIC_BRIDGE_BASE", "http://127.0.0.1:8765"),
        "repo_root": str(root),
        "mcp_rest_base": os.environ.get("OFDD_MCP_REST_BASE", "http://127.0.0.1:8090"),
        "ui_public_base": os.environ.get("OFDD_UI_PUBLIC_BASE", "http://127.0.0.1:5173"),
        "codex_available": bool(codex),
        "agent_shell": f"openfdd-agent-shell --repo-root {root}",
        "ai_backend_default": ollama_client.ai_backend_preference(),
        "ollama": ollama,
        "ollama_ram_tier": tier,
        "ollama_model": ollama_client.configured_model(),
        "ollama_gpu_mode": os.environ.get("OFDD_OLLAMA_GPU_MODE", "cpu"),
        "ollama_tiers": tiers_payload(),
        "ollama_gpu_options": gpu_options_payload(),
        "note": (
            "Local chat uses Ollama on this host. For heavy work use Cursor / Claude Code / Codex remotely "
            "against this repo. BRICK export: GET /api/model/export. Building alerts: PUT /api/building/alerts."
        ),
    }


@router.get("/ollama/health")
def ollama_health() -> dict:
    return {"ok": True, **ollama_client.health()}


@router.post("/chat")
def agent_chat(body: ChatBody) -> dict:
    use_ollama = body.backend == "ollama" or (
        body.backend == "auto" and ollama_client.should_use_ollama()
    )
    if use_ollama:
        result = ollama_client.chat(
            body.message,
            model=body.model,
            ram_tier=body.ram_tier,
            gpu_mode=body.gpu_mode,
        )
        if result.get("ok") or body.backend == "ollama":
            return result
        if body.backend == "auto" and not shutil.which("codex") and not shutil.which("codex.cmd"):
            result["hint"] = "Install Ollama: ./scripts/bootstrap_ollama.sh --ram-tier 8gb"
            return result

    root = resolve_workdir_under_repo(body.workdir)
    codex = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex:
        ollama_hint = ollama_client.health()
        return {
            "ok": False,
            "mode": "guidance",
            "reply": (
                "No local Ollama and no Codex CLI on PATH. "
                "Run ./scripts/bootstrap_ollama.sh --ram-tier 8gb for local AI, "
                "or use Cursor / Claude Code remotely. "
                f"Ollama: {ollama_hint.get('error', 'down')}"
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
        return {"ok": False, "mode": "codex", "error": "codex exec timed out", "reply": ""}
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "ok": proc.returncode == 0,
        "mode": "codex",
        "exit_code": proc.returncode,
        "reply": out[-12000:],
    }
