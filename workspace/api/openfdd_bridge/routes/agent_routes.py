from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..deps import require_roles
from .. import ollama_client
from ..ollama_profiles import tiers_payload
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
        "ollama_tiers": tiers_payload(),
    }


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
    )
