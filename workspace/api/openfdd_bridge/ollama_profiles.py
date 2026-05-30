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


# Default model per tier — qwen3 thinking line (CPU-friendly ladder).
# On a 4GB Raspberry Pi, override to qwen3:0.6b; keep the thinking toggle off on Pi.
OLLAMA_PROFILES: dict[RamTier, OllamaProfile] = {
    "8gb": OllamaProfile(
        ram_tier="8gb",
        model="qwen3:1.7b",
        label="Qwen3 1.7B",
        approx_vram_gb=1.4,
        description="Small thinking model (~1.4GB) for 8GB / Raspberry Pi 5 hosts. On a 4GB Pi use qwen3:0.6b.",
    ),
    "16gb": OllamaProfile(
        ram_tier="16gb",
        model="qwen3:4b",
        label="Qwen3 4B",
        approx_vram_gb=2.5,
        description="Balanced thinking model (~2.5GB, 256K context). Recommended default for 16GB hosts.",
    ),
    "32gb": OllamaProfile(
        ram_tier="32gb",
        model="qwen3:8b",
        label="Qwen3 8B",
        approx_vram_gb=5.2,
        description="Higher-quality thinking model (~5.2GB) for 32GB hosts.",
    ),
    "64gb": OllamaProfile(
        ram_tier="64gb",
        model="qwen3:14b",
        label="Qwen3 14B",
        approx_vram_gb=9.3,
        description="Heavier thinking model (~9.3GB) when RAM/GPU headroom allows.",
    ),
}


# Thinking-capable models (emit a `message.thinking` trace). The default tier
# models above are NOT thinking models, so the operator must pick one of these
# (installed via `ollama pull <model>`) to see a reasoning trace.
THINKING_MODELS: list[dict[str, object]] = [
    {"model": "qwen3", "label": "Qwen 3", "think": "boolean", "approx_vram_gb": 5.0},
    {"model": "deepseek-r1", "label": "DeepSeek R1", "think": "boolean", "approx_vram_gb": 5.0},
    {"model": "gpt-oss", "label": "GPT-OSS", "think": "level", "approx_vram_gb": 14.0},
]


def thinking_models_payload() -> list[dict[str, object]]:
    return [dict(m) for m in THINKING_MODELS]


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
