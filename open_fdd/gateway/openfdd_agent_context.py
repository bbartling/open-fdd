"""Bootstrap context for the built-in Open-FDD agent (ports, URLs, key API paths).

`start-local.ps1` writes `stack/local-data/openfdd-agent-bootstrap.json`; the bridge merges
that file (when present) with live environment variables so Codex always sees a stable map.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


def _strip(s: str | None) -> str:
    return (s or "").strip()


def _default_mcp_rest_base() -> str:
    explicit = _strip(os.environ.get("OFDD_MCP_REST_BASE"))
    if explicit:
        return explicit.rstrip("/")
    host = _strip(os.environ.get("OFDD_MCP_LISTEN_HOST")) or "127.0.0.1"
    port = _strip(os.environ.get("OFDD_MCP_LISTEN_PORT")) or "8090"
    return f"http://{host}:{port}".rstrip("/")


def _bootstrap_file_path() -> Path | None:
    raw = _strip(os.environ.get("OFDD_AGENT_BOOTSTRAP_FILE"))
    if raw:
        return Path(raw).expanduser()
    # Repo convention when cwd is repo root (gateway / bridge)
    candidate = Path.cwd() / "stack" / "local-data" / "openfdd-agent-bootstrap.json"
    if candidate.is_file():
        return candidate
    return None


def _load_bootstrap_file() -> dict[str, Any]:
    path = _bootstrap_file_path()
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _logger.warning("Could not read or parse agent bootstrap file %s: %s", path, exc)
        return {}


def _merge_bootstrap_overlay(ctx: dict[str, Any], overlay: dict[str, Any]) -> None:
    """Apply bootstrap file on top of generated defaults without clobbering nested dicts/lists."""
    for k, v in overlay.items():
        if v is None:
            continue
        existing = ctx.get(k)
        if isinstance(existing, dict) and isinstance(v, dict):
            _merge_bootstrap_overlay(existing, v)
        elif isinstance(existing, list) and isinstance(v, list):
            ctx[k] = list(existing) + list(v)
        else:
            ctx[k] = v


def build_agent_bootstrap_context() -> dict[str, Any]:
    """Return JSON-serializable map for UI + Codex system prompts."""
    file_overlay = _load_bootstrap_file()

    bridge = _strip(os.environ.get("OFDD_BRIDGE_URL")) or _strip(os.environ.get("OFDD_MCP_OFDD_API_URL"))
    if not bridge:
        bridge = "http://127.0.0.1:8765"
    bridge = bridge.rstrip("/")

    mcp = _default_mcp_rest_base()
    ui = _strip(os.environ.get("OFDD_UI_PUBLIC_BASE")) or "http://127.0.0.1:5173"
    ui = ui.rstrip("/")

    desktop_data = _strip(os.environ.get("OFDD_DESKTOP_DATA_DIR"))

    ctx: dict[str, Any] = {
        "bridge_base": bridge,
        "mcp_rest_base": mcp,
        "ui_public_base": ui,
        "desktop_data_dir": desktop_data or None,
        "endpoints": {
            "bridge_health": f"{bridge}/health",
            "bridge_openapi": f"{bridge}/openapi.json",
            "bridge_docs": f"{bridge}/docs",
            "readiness": f"{bridge}/assistant/readiness",
            "sites": f"{bridge}/sites",
            "timeseries_clean_metrics": f"{bridge}/timeseries/clean-metrics",
            "plots_frame": f"{bridge}/plots/frame",
            "plots_site_frame": f"{bridge}/plots/site-frame",
            "plots_fdd_frame": f"{bridge}/plots/fdd-frame",
            "local_codex_diagnostics": f"{bridge}/local-codex/diagnostics",
            "openfdd_agent_context": f"{bridge}/openfdd-agent/context",
            "openfdd_agent_chat": f"{bridge}/openfdd-agent/chat",
            "mcp_manifest": f"{mcp}/manifest",
            "mcp_health": f"{mcp}/health",
        },
        "mcp_tools_examples": [
            f"POST {mcp}/tools/search_docs — JSON body: query, top_k (e.g. query mentions clean-metrics, plots frame, FDD, readiness)",
            f"POST {mcp}/tools/search_api_capabilities — list bridge capabilities",
        ],
        "notes": [
            "MCP RAG is REST on mcp_rest_base (not Streamable MCP unless you add an adapter).",
            "Action tools may require OFDD_MCP_ENABLE_ACTION_TOOLS and OFDD_MCP_OFDD_API_KEY — see docs/howto/desktop_app.md.",
            "Codex auth: use `codex login` on the bridge host; GET /local-codex/diagnostics for status.",
            "String metrics / plots: use POST timeseries/clean-metrics with commit:false first when readiness recommends it; Plots JSON from GET plots/site-frame or POST plots/fdd-frame.",
        ],
    }
    _merge_bootstrap_overlay(ctx, file_overlay)
    return ctx


def format_agent_context_markdown(ctx: dict[str, Any]) -> str:
    """Compact markdown block injected into Codex system prompt."""
    lines = [
        "### Open-FDD stack (authoritative for this session)",
        f"- **Bridge**: `{ctx.get('bridge_base', '')}`",
        f"- **MCP RAG (REST)**: `{ctx.get('mcp_rest_base', '')}`",
        f"- **UI**: `{ctx.get('ui_public_base', '')}`",
    ]
    dd = ctx.get("desktop_data_dir")
    if dd:
        lines.append(f"- **Desktop data dir**: `{dd}`")
    ep = ctx.get("endpoints")
    if isinstance(ep, dict):
        lines.append("- **HTTP**")
        for name in sorted(ep.keys()):
            lines.append(f"  - `{name}`: {ep[name]}")
    mcp_base = ctx.get("mcp_rest_base") or ""
    if isinstance(mcp_base, str) and mcp_base.strip():
        lines.append(
            "- **MCP RAG (optional)** — use when docs, API discovery, or RAG search would help; "
            f"skip if the human only needs bridge/UI actions. Start with `{mcp_base.strip()}/manifest` "
            "(or `mcp_health`) to confirm the server, then call tools as needed."
        )
    examples = ctx.get("mcp_tools_examples")
    if isinstance(examples, list) and examples:
        lines.append("  - Example tool calls (REST JSON):")
        for ex in examples:
            if isinstance(ex, str) and ex.strip():
                lines.append(f"    - {ex.strip()}")
    notes = ctx.get("notes")
    if isinstance(notes, list):
        lines.append("- **Remarks**")
        for n in notes:
            lines.append(f"  - {n}")
    return "\n".join(lines)
