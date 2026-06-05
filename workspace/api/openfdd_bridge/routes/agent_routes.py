from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..deps import require_roles, require_user
from .. import agent_tools, audit, building_insight, ollama_client, device_poll_health, zone_temp_analytics
from ..agent_tools import ToolError
from ..audit import sanitize_agent_tool_args
from ..ollama_profiles import thinking_models_payload, tiers_payload
from ..paths import repo_root
from .. import auth
from ..security import debug_diagnostics_enabled

router = APIRouter(prefix="/openfdd-agent", tags=["agent"])

_AGENT_ROLES = Depends(require_roles("operator", "integrator", "agent"))
_TOOL_ROLES = Depends(require_roles("operator", "integrator", "agent"))


def require_insight_access(request: Request) -> dict:
    """Read-only home-dashboard briefings — public like /api/faults/status (auth optional)."""
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    payload = auth.verify_token(token) if token else None
    if payload is not None:
        request.state.user = payload
        return payload
    user = {"sub": "anonymous", "role": "none"}
    request.state.user = user
    return user


_INSIGHT = Depends(require_insight_access)


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
def agent_context(user: dict = _AGENT_ROLES) -> dict:
    # Cap total Ollama probe time so /context stays under reverse-proxy health budgets.
    ollama = ollama_client.health(timeout=2.0, max_total_s=6.0)
    tier = ollama_client.configured_ram_tier()
    gpu_ok = ollama_client.gpu_available()
    chat_enabled = ollama_client.interactive_chat_enabled()
    payload: dict = {
        "ollama": ollama,
        "gpu_available": gpu_ok,
        "interactive_chat_enabled": chat_enabled,
        "interactive_chat_disabled_reason": (
            ""
            if chat_enabled
            else (
                "No NVIDIA GPU detected — local Agent chat is disabled (CPU inference is too slow)."
                if not gpu_ok
                else str(ollama.get("error") or "Ollama unreachable")
            )
        ),
        "ollama_ram_tier": tier,
        "ollama_model": ollama_client.configured_model(),
        "ollama_gpu_mode": os.environ.get("OFDD_OLLAMA_GPU_MODE", "cpu"),
        "ollama_timeout_s": float(os.environ.get("OFDD_OLLAMA_TIMEOUT_S", str(ollama_client.DEFAULT_TIMEOUT_S))),
        "ollama_tiers": tiers_payload(),
        "ollama_thinking_models": thinking_models_payload(),
        "ollama_think": ollama_client.configured_think(),
        "mcp": ollama_client.mcp_agent_hints(),
        **(
            agent_tools.operator_model_context()
            if user.get("role") == "operator"
            else agent_tools.model_context()
        ),
    }
    if debug_diagnostics_enabled() and user.get("role") in {"integrator", "agent"}:
        payload["repo_root"] = str(repo_root())
    return payload


@router.get("/tools")
def list_tools(user: dict = _AGENT_ROLES) -> dict:
    role = str(user.get("role") or "operator")
    return {
        "tools": agent_tools.tool_specs_for_role(role),
        "app_edit_enabled": agent_tools.app_edit_enabled() and role in {"integrator", "agent"},
    }


@router.post("/tool")
def run_tool(
    body: ToolBody,
    request: Request,
    user: dict = _TOOL_ROLES,
) -> dict:
    """Execute agent tools. Read-only tools allowed for operator; writes need integrator/agent."""
    try:
        result = agent_tools.run_tool(body.tool, body.args, role=str(user.get("role") or ""))
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
            detail={"args": sanitize_agent_tool_args(body.tool, body.args), "error": str(exc)},
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
        detail={"args": sanitize_agent_tool_args(body.tool, body.args)},
    )
    return {"ok": True, "tool": body.tool, "result": result}


@router.get("/ollama/health")
def ollama_health(_user: dict = _INSIGHT) -> dict:
    return {"ok": True, **ollama_client.health()}


@router.get("/building-insight")
def building_insight_snapshot(force: bool = Query(default=False), _user: dict = _INSIGHT) -> dict:
    """Read-only briefing for the home dashboard (fixed interval cache).

    Do NOT add chat POST handlers on the home page — use ``/chat`` on the Agent tab only.
    """
    return building_insight.get_building_insight(force=force)


@router.get("/operational-brief")
def operational_brief(force: bool = Query(default=False), _user: dict = _INSIGHT) -> dict:
    """Structured zone-temp, device poll health, and fault lines (same window as home insight)."""
    return building_insight.get_operational_brief(force=force)


@router.get("/device-poll-health")
def device_poll_health_snapshot(
    force: bool = Query(default=False),
    site_id: str | None = Query(default=None),
    _user: dict = _INSIGHT,
) -> dict:
    """Per-equipment online/flaky status from feather poll timestamps (+ FDD bindings)."""
    return device_poll_health.get_device_poll_snapshot(site_id=site_id, force=force)


@router.get("/zone-temps")
def zone_temps_snapshot(
    force: bool = Query(default=False),
    site_id: str | None = Query(default=None),
    _user: dict = _INSIGHT,
) -> dict:
    """Prebuilt zone temperature levers (day/night averages, recovery rates)."""
    return zone_temp_analytics.get_zone_temp_snapshot(site_id=site_id, force=force)


@router.post("/chat")
def agent_chat(body: ChatBody, _user: dict = _AGENT_ROLES) -> dict:
    """Local operator chat — Ollama with GPU; disabled on CPU-only hosts."""
    if not ollama_client.interactive_chat_enabled():
        reason = (
            "Local Agent chat requires a GPU (CPU-only Ollama is too slow)."
            if not ollama_client.gpu_available()
            else "Ollama is not reachable."
        )
        return {
            "ok": False,
            "mode": "disabled",
            "reply": "",
            "error": reason,
            "hint": "Use the home dashboard Refresh for building analytics, or enable a GPU / OFDD_AGENT_CHAT_WITHOUT_GPU=1.",
        }
    from ..brick_model_context import build_agent_system_extra

    return ollama_client.chat(
        body.message,
        model=body.model or ollama_client.configured_model(),
        ram_tier=body.ram_tier or ollama_client.configured_ram_tier(),
        gpu_mode=body.gpu_mode or os.environ.get("OFDD_OLLAMA_GPU_MODE", "cpu"),
        think=body.think,
        history=body.history,
        system=ollama_client.build_system_prompt(extra=build_agent_system_extra()),
    )
