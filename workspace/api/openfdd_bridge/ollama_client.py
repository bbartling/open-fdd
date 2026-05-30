"""HTTP client for local Ollama (OpenAI-compatible /api/chat)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from .ollama_profiles import GpuMode, OllamaProfile, normalize_ram_tier, profile_for_tier

DEFAULT_BASE = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_S = 120.0

SYSTEM_PROMPT = (
    "You are the Open-FDD operator assistant on an OT BACnet/FDD edge host. "
    "Be concise. Help with BRICK data modeling, Python Rule Lab faults, BACnet commissioning, "
    "and building status. Do not invent BACnet device IDs or write to field equipment unless asked."
)


def ollama_base_url() -> str:
    return os.environ.get("OFDD_OLLAMA_BASE_URL", DEFAULT_BASE).rstrip("/")


def configured_ram_tier() -> str:
    return normalize_ram_tier(os.environ.get("OFDD_OLLAMA_RAM_TIER", "8gb"))


def configured_model() -> str:
    override = os.environ.get("OFDD_OLLAMA_MODEL", "").strip()
    if override:
        return override
    return profile_for_tier(configured_ram_tier()).model  # type: ignore[arg-type]


def configured_num_gpu() -> int:
    raw = os.environ.get("OFDD_OLLAMA_NUM_GPU", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    mode = os.environ.get("OFDD_OLLAMA_GPU_MODE", "cpu").strip().lower()
    if mode == "auto":
        return -1
    if mode == "gpu":
        return 99
    return 0


def ai_backend_preference() -> str:
    """ollama | codex | auto"""
    return os.environ.get("OFDD_AI_BACKEND", "auto").strip().lower() or "auto"


_THINK_LEVELS = frozenset({"low", "medium", "high"})


def normalize_think(value: Any) -> bool | str | None:
    """Coerce a think request to what Ollama accepts.

    Returns a bool (qwen3 / deepseek-r1 style), a level string for gpt-oss
    (``low`` / ``medium`` / ``high``), or ``None`` to omit the field entirely.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text in _THINK_LEVELS:
        return text
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def configured_think() -> bool | str | None:
    return normalize_think(os.environ.get("OFDD_OLLAMA_THINK", ""))


def resolve_model(*, ram_tier: str | None = None, model: str | None = None) -> str:
    if model and model.strip():
        return model.strip()
    tier = normalize_ram_tier(ram_tier or configured_ram_tier())
    return profile_for_tier(tier).model


def resolve_num_gpu(*, gpu_mode: str | None = None) -> int:
    if gpu_mode:
        mode = gpu_mode.strip().lower()
        if mode == "cpu":
            return 0
        if mode == "auto":
            return -1
        if mode == "gpu":
            return 99
    return configured_num_gpu()


def health(timeout: float = 3.0) -> dict[str, Any]:
    base = ollama_base_url()
    try:
        with httpx.Client(timeout=timeout) as client:
            tags = client.get(f"{base}/api/tags")
            tags.raise_for_status()
            body = tags.json()
            names = [m.get("name", "") for m in body.get("models", []) if isinstance(m, dict)]
            return {
                "ok": True,
                "base_url": base,
                "models_installed": names,
                "configured_model": configured_model(),
                "configured_ram_tier": configured_ram_tier(),
                "num_gpu": configured_num_gpu(),
            }
    except Exception as exc:
        return {
            "ok": False,
            "base_url": base,
            "error": str(exc)[:500],
            "configured_model": configured_model(),
            "configured_ram_tier": configured_ram_tier(),
            "num_gpu": configured_num_gpu(),
        }


def model_installed(model: str, *, timeout: float = 3.0) -> bool:
    h = health(timeout=timeout)
    if not h.get("ok"):
        return False
    names = [str(x) for x in (h.get("models_installed") or [])]
    if model in names:
        return True
    if ":" not in model:
        return any(n.split(":")[0] == model for n in names)
    return False


def chat(
    message: str,
    *,
    model: str | None = None,
    ram_tier: str | None = None,
    gpu_mode: str | None = None,
    system: str | None = None,
    timeout: float | None = None,
    think: bool | str | None = None,
) -> dict[str, Any]:
    use_model = resolve_model(ram_tier=ram_tier, model=model)
    num_gpu = resolve_num_gpu(gpu_mode=gpu_mode)
    think_value = normalize_think(think) if think is not None else configured_think()
    payload: dict[str, Any] = {
        "model": use_model,
        "messages": [
            {"role": "system", "content": system or SYSTEM_PROMPT},
            {"role": "user", "content": message[:8000]},
        ],
        "stream": False,
        "options": {"num_gpu": num_gpu},
    }
    if think_value is not None:
        payload["think"] = think_value
    url = f"{ollama_base_url()}/api/chat"
    to = timeout or float(os.environ.get("OFDD_OLLAMA_TIMEOUT_S", str(DEFAULT_TIMEOUT_S)))
    try:
        with httpx.Client(timeout=to) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = ""
            thinking = ""
            msg = data.get("message")
            if isinstance(msg, dict):
                content = str(msg.get("content") or "")
                thinking = str(msg.get("thinking") or "")
            return {
                "ok": True,
                "mode": "ollama",
                "model": use_model,
                "num_gpu": num_gpu,
                "think": think_value,
                "thinking": thinking.strip(),
                "reply": content.strip() or "(empty response)",
                "eval_count": data.get("eval_count"),
            }
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        return {
            "ok": False,
            "mode": "ollama",
            "model": use_model,
            "error": f"HTTP {exc.response.status_code}: {detail}",
            "reply": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "mode": "ollama",
            "model": use_model,
            "error": str(exc)[:500],
            "reply": "",
        }


def should_use_ollama() -> bool:
    pref = ai_backend_preference()
    if pref == "codex":
        return False
    if pref == "ollama":
        return True
    return health().get("ok") is True
