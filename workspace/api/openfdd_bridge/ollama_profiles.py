"""Ollama model presets by host RAM tier (smoke → production-ish)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RamTier = Literal["8gb", "16gb", "32gb", "64gb"]
GpuMode = Literal["cpu", "auto", "gpu"]


@dataclass(frozen=True)
class OllamaProfile:
    ram_tier: RamTier
    model: str
    label: str
    approx_vram_gb: float
    description: str


# Default model per tier — 8gb is intentionally the flimsiest smoke-test model.
OLLAMA_PROFILES: dict[RamTier, OllamaProfile] = {
    "8gb": OllamaProfile(
        ram_tier="8gb",
        model="tinyllama",
        label="TinyLlama 1.1B",
        approx_vram_gb=0.7,
        description="Ultra-light smoke test (~637MB). Best for 8GB RAM lab hosts.",
    ),
    "16gb": OllamaProfile(
        ram_tier="16gb",
        model="llama3.2:1b",
        label="Llama 3.2 1B",
        approx_vram_gb=1.3,
        description="Small instruct model for 16GB RAM edges.",
    ),
    "32gb": OllamaProfile(
        ram_tier="32gb",
        model="llama3.2:3b",
        label="Llama 3.2 3B",
        approx_vram_gb=2.0,
        description="Balanced local assistant for 32GB hosts.",
    ),
    "64gb": OllamaProfile(
        ram_tier="64gb",
        model="llama3.1:8b",
        label="Llama 3.1 8B",
        approx_vram_gb=5.0,
        description="Heavier local model when RAM/GPU headroom allows.",
    ),
}


def normalize_ram_tier(raw: str | None) -> RamTier:
    key = (raw or "8gb").strip().lower()
    if key in OLLAMA_PROFILES:
        return key  # type: ignore[return-value]
    return "8gb"


def profile_for_tier(tier: RamTier) -> OllamaProfile:
    return OLLAMA_PROFILES[tier]


def gpu_options_payload() -> list[dict[str, str | int]]:
    return [
        {"id": "cpu", "label": "CPU only", "num_gpu": 0, "detail": "No GPU layers — safest on low-RAM hosts."},
        {"id": "auto", "label": "Auto", "num_gpu": -1, "detail": "Let Ollama decide GPU offload."},
        {"id": "gpu", "label": "GPU max", "num_gpu": 99, "detail": "Offload as many layers as possible."},
    ]


def tiers_payload() -> list[dict[str, object]]:
    return [
        {
            "ram_tier": p.ram_tier,
            "model": p.model,
            "label": p.label,
            "approx_vram_gb": p.approx_vram_gb,
            "description": p.description,
        }
        for p in OLLAMA_PROFILES.values()
    ]
