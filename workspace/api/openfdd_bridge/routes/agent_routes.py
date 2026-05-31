from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import require_roles
from .. import agent_tools, audit, ollama_client
from ..agent_tools import ToolError
from ..ollama_profiles import thinking_models_payload, tiers_payload
from ..paths import repo_root

router = APIRouter(
    prefix="/openfdd-agent",
    tags=["agent"],
    dependencies=[Depends(require_roles("operator", "integrator", "agent"))],
)


class ChatBody(BaseModel):
    message: str
    ram_tier: str | None = None
    model: str | None = None
    gpu_mode: str | None = None
    think: bool | str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class ToolBody(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


@router.get("/context")
def agent_context() -> dict:
    ollama = ollama_client.health()
    tier = ollama_client.configured_ram_tier()
    return {
        "repo_root": str(repo_root()),
        "ollama": ollama,
        "ollama_ram_tier": tier,
        "ollama_model": ollama_client.configured_model(),
        "ollama_gpu_mode": os.environ.get("OFDD_OLLAMA_GPU_MODE", "cpu"),
        "ollama_timeout_s": float(os.environ.get("OFDD_OLLAMA_TIMEOUT_S", str(ollama_client.DEFAULT_TIMEOUT_S))),
        "ollama_tiers": tiers_payload(),
        "ollama_thinking_models": thinking_models_payload(),
        "ollama_think": ollama_client.configured_think(),
        "mcp": ollama_client.mcp_agent_hints(),
        **agent_tools.model_context(),
    }


@router.get("/tools")
def list_tools() -> dict:
    return {"tools": agent_tools.tool_specs(), "app_edit_enabled": agent_tools.app_edit_enabled()}


@router.post("/tool")
def run_tool(
    body: ToolBody,
    request: Request,
    user: dict = Depends(require_roles("agent")),
) -> dict:
    """Execute an agent maintenance tool. Restricted to the `agent` role, audited."""
    try:
        result = agent_tools.run_tool(body.tool, body.args)
    except ToolError as exc:
        audit.write_audit(
            event_type="agent.tool",
            action=body.tool,
            outcome="failure",
            severity="warning",
            request=request,
            user=user,
            resource_type="agent_tool",
            resource_id=body.tool,
            detail={"args": body.args, "error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.write_audit(
        event_type="agent.tool",
        action=body.tool,
        outcome="success",
        request=request,
        user=user,
        resource_type="agent_tool",
        resource_id=body.tool,
        detail={"args": body.args},
    )
    return {"ok": True, "tool": body.tool, "result": result}


@router.get("/ollama/health")
def ollama_health() -> dict:
    return {"ok": True, **ollama_client.health()}


@router.post("/chat")
def agent_chat(body: ChatBody) -> dict:
    """Local operator chat — always Ollama (configured via workspace/ollama.env.local)."""
    return ollama_client.chat(
        body.message,
        model=body.model or ollama_client.configured_model(),
        ram_tier=body.ram_tier or ollama_client.configured_ram_tier(),
        gpu_mode=body.gpu_mode or os.environ.get("OFDD_OLLAMA_GPU_MODE", "cpu"),
        think=body.think,
        history=body.history,
    )
