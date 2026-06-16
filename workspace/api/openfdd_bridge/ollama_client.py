"""HTTP client for local Ollama (OpenAI-compatible /api/chat)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from .agent_chat_history import build_ollama_messages
from .ollama_profiles import GpuMode, OllamaProfile, normalize_ram_tier, profile_for_tier

DEFAULT_BASE = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_HEALTH_TIMEOUT_S = 8.0
_WORKING_BASE: str | None = None


def _ns_to_ms(value: Any) -> int | None:
    try:
        return int(int(value) / 1_000_000)
    except (TypeError, ValueError):
        return None


def _timing_from_response(data: dict[str, Any]) -> dict[str, Any]:
    eval_duration_ms = _ns_to_ms(data.get("eval_duration"))
    eval_count = data.get("eval_count")
    tokens_per_sec: float | None = None
    if eval_duration_ms and eval_count and eval_duration_ms > 0:
        tokens_per_sec = round(int(eval_count) / (eval_duration_ms / 1000.0), 1)
    return {
        "duration_ms": _ns_to_ms(data.get("total_duration")),
        "load_duration_ms": _ns_to_ms(data.get("load_duration")),
        "eval_duration_ms": eval_duration_ms,
        "eval_count": eval_count,
        "tokens_per_sec": tokens_per_sec,
    }

SYSTEM_PROMPT = (
    "You are the Open-FDD operator assistant on an OT BACnet/FDD edge host. "
    "Be concise. Help with BRICK data modeling (equipment, brick:feeds, Zone_Air_Temperature_Sensor), "
    "Python Rule Lab faults (fixed catalog codes like VAV-C), BACnet commissioning, feather historian trends, "
    "and building status. Interlink active faults to BRICK equipment names and feeds chains. "
    "Recommend POST /openfdd-agent/tool for read-only queries (model.graph, timeseries.snapshot, faults.lookup) "
    "or GET /api/model/graph and /api/timeseries/readings when operators need live data. "
    "Do not invent BACnet device IDs or write to field equipment unless asked."
)


def bridge_base_url() -> str:
    host = os.environ.get("OFDD_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.environ.get("OFDD_BRIDGE_PORT", "8765").strip() or "8765"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def mcp_agent_hints() -> dict[str, Any]:
    """Local MCP RAG discovery — surfaced in /openfdd-agent/context and the system prompt."""
    base = os.environ.get("OFDD_MCP_REST_BASE", "http://127.0.0.1:8090").rstrip("/")
    enabled = os.environ.get("OFDD_MCP_ENABLED", "").strip().lower() in {"1", "true", "yes"}
    hints: dict[str, Any] = {
        "mcp_enabled": enabled,
        "mcp_rest_base": base if enabled else None,
        "bridge_base_url": bridge_base_url(),
        "external_agents_recommended": (
            "Cursor, OpenClaw, or Claude Desktop/Code with MCP pointed at this bridge — "
            "typical on CPU-only edges without local Ollama."
        ),
        "edge_mcp_optional": (
            "On CPU-only hosts you do not need the MCP sidecar on the edge; run MCP from your workstation."
        ),
    }
    if not enabled:
        hints["note"] = (
            "MCP RAG sidecar off on this host — set OFDD_MCP_ENABLED=1 in workspace/mcp.env.local "
            "or run MCP from an external agent against the bridge REST/OpenAPI URLs."
        )
        return hints
    hints.update(
        {
            "mcp_health": f"{base}/health",
            "mcp_manifest": f"{base}/manifest",
            "mcp_streamable": f"{base}/mcp",
            "mcp_search_docs": f"{base}/tools/search_docs",
            "mcp_search_api": f"{base}/tools/search_api_capabilities",
            "search_docs_example": {"query": "Rule Lab BACnet", "top_k": 5},
            "search_api_example": {"query": "portfolio rollup building status", "top_k": 5},
            "bridge_openapi": f"{bridge_base_url()}/openapi.json",
            "bridge_agent_context": f"{bridge_base_url()}/openfdd-agent/context",
            "external_agents": (
                "On CPU-only edge hosts, prefer Cursor MCP (/mcp), Codex CLI, or OpenClaw — "
                "not the in-browser Ollama chat tab."
            ),
        }
    )
    return hints


def build_system_prompt(*, extra: str | None = None) -> str:
    parts = [SYSTEM_PROMPT]
    mcp = mcp_agent_hints()
    if mcp.get("mcp_enabled"):
        base = mcp["mcp_rest_base"]
        parts.append(
            "Local MCP RAG (same host as the bridge): "
            f"POST {base}/tools/search_docs with JSON "
            '{"query":"<topic>","top_k":5} for indexed Open-FDD docs; '
            f"GET {base}/manifest for tool list; "
            f"GET {mcp['bridge_openapi']} for REST routes. "
            "Prefer searching docs before guessing API paths or workflows."
        )
    else:
        parts.append(
            f"Bridge API base: {mcp['bridge_base_url']} — GET /openapi.json and GET /openfdd-agent/context. "
            "MCP doc search is disabled unless OFDD_MCP_ENABLED=1."
        )
    if extra and extra.strip():
        parts.append(extra.strip())
    return "\n\n".join(parts)


def ollama_base_url() -> str:
    return os.environ.get("OFDD_OLLAMA_BASE_URL", DEFAULT_BASE).rstrip("/")


def ollama_base_candidates() -> list[str]:
    """Probe order for Docker dev (in-compose ``ollama``) and host Ollama."""
    primary = ollama_base_url()
    extra = [
        u.strip().rstrip("/")
        for u in os.environ.get("OFDD_OLLAMA_FALLBACK_URLS", "").split(",")
        if u.strip()
    ]
    defaults = ["http://ollama:11434", "http://host.docker.internal:11434", DEFAULT_BASE]
    seen: set[str] = set()
    out: list[str] = []
    for url in [primary, *extra, *defaults]:
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _active_ollama_base() -> str:
    global _WORKING_BASE
    if _WORKING_BASE:
        return _WORKING_BASE
    return ollama_base_url()


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


def health(timeout: float | None = None, *, max_total_s: float | None = None) -> dict[str, Any]:
    global _WORKING_BASE
    to = timeout
    if to is None:
        try:
            to = float(os.environ.get("OFDD_OLLAMA_HEALTH_TIMEOUT_S", str(DEFAULT_HEALTH_TIMEOUT_S)))
        except ValueError:
            to = DEFAULT_HEALTH_TIMEOUT_S
    if max_total_s is None:
        try:
            max_total_s = float(os.environ.get("OFDD_OLLAMA_HEALTH_MAX_TOTAL_S", "12"))
        except ValueError:
            max_total_s = 12.0
    last_err = ""
    tried: list[str] = []
    started = time.monotonic()
    for base in ollama_base_candidates():
        remaining = max_total_s - (time.monotonic() - started)
        if remaining <= 0.15:
            last_err = last_err or "Ollama health budget exceeded"
            break
        per_try = min(to, remaining)
        tried.append(base)
        try:
            with httpx.Client(timeout=per_try) as client:
                tags = client.get(f"{base}/api/tags")
                tags.raise_for_status()
                body = tags.json()
                names = [m.get("name", "") for m in body.get("models", []) if isinstance(m, dict)]
                _WORKING_BASE = base
                return {
                    "ok": True,
                    "base_url": base,
                    "models_installed": names,
                    "configured_model": configured_model(),
                    "configured_ram_tier": configured_ram_tier(),
                    "num_gpu": configured_num_gpu(),
                    "health_timeout_s": per_try,
                    "health_max_total_s": max_total_s,
                    "tried_urls": tried,
                }
        except Exception as exc:
            last_err = str(exc)[:500]
    _WORKING_BASE = None
    return {
        "ok": False,
        "base_url": ollama_base_url(),
        "error": last_err or "no reachable Ollama URL",
        "configured_model": configured_model(),
        "configured_ram_tier": configured_ram_tier(),
        "num_gpu": configured_num_gpu(),
        "health_timeout_s": to,
        "health_max_total_s": max_total_s,
        "tried_urls": tried,
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
    history: list[dict[str, Any]] | None = None,
    timeout: float | None = None,
    think: bool | str | None = None,
) -> dict[str, Any]:
    use_model = resolve_model(ram_tier=ram_tier, model=model)
    num_gpu = resolve_num_gpu(gpu_mode=gpu_mode)
    think_value = normalize_think(think) if think is not None else configured_think()
    sys_text = system or build_system_prompt()
    payload: dict[str, Any] = {
        "model": use_model,
        "messages": build_ollama_messages(message=message, history=history, system=sys_text),
        "stream": False,
        "options": {"num_gpu": num_gpu},
    }
    if think_value is not None:
        payload["think"] = think_value
    url = f"{_active_ollama_base()}/api/chat"
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
            timing = _timing_from_response(data)
            return {
                "ok": True,
                "mode": "ollama",
                "model": use_model,
                "num_gpu": num_gpu,
                "think": think_value,
                "thinking": thinking.strip(),
                "reply": content.strip() or "(empty response)",
                **timing,
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


def gpu_available() -> bool:
    """True when an NVIDIA GPU is present (interactive local chat target)."""
    override = os.environ.get("OFDD_GPU_AVAILABLE", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    if Path("/dev/nvidia0").is_char_device():
        return True
    try:
        proc = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


def interactive_chat_enabled() -> bool:
    """Agent tab chat — disabled on CPU-only hosts (too slow for operators)."""
    if os.environ.get("OFDD_AGENT_CHAT_WITHOUT_GPU", "").strip().lower() in {"1", "true", "yes"}:
        return health(timeout=4.0).get("ok") is True
    return gpu_available() and health(timeout=4.0).get("ok") is True


def should_use_ollama() -> bool:
    pref = ai_backend_preference()
    if pref == "codex":
        return False
    if pref == "ollama":
        return health().get("ok") is True
    return health().get("ok") is True


def should_use_ollama_for_insight() -> bool:
    """Home dashboard one-liner — skip slow CPU inference; analytics still refresh."""
    if not health(timeout=6.0).get("ok"):
        return False
    if os.environ.get("OFDD_INSIGHT_USE_OLLAMA_WITHOUT_GPU", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return gpu_available()
