"""Built-in Open-FDD agent: Codex CLI + stack context + SIMPLE/COMPLEX routing."""

from __future__ import annotations

import os
from typing import Any

from open_fdd.gateway.local_codex_cli import (
    build_chat_stdin,
    resolve_codex_executable,
    resolve_workdir,
    run_codex_exec,
    safe_int_from_env,
)
from open_fdd.gateway.openfdd_agent_context import build_agent_bootstrap_context, format_agent_context_markdown
from open_fdd.gateway.openfdd_agent_routing import classify_openfdd_task, routing_instructions_for_tier


def _openfdd_agent_identity() -> str:
    return """You are the **Open-FDD built-in agent** (Codex subscription on this host).

Mission: help operators with **FDD**, **AI-assisted data modeling**, **metrics cleaning**, ingest, rules, and Plots —
using the Open-FDD **bridge HTTP API**, **MCP RAG** (when up; optional `search_docs` / `search_api_capabilities` from the stack block), and the **repo / workdir** on disk.

Rules:
- Prefer **real API calls** (`curl` / `Invoke-RestMethod`), small **Python** helpers, or **PowerShell** one-liners against the URLs below.
- The bridge runs **`codex exec`** with **non-interactive** approval (`OFDD_CODEX_EXEC_APPROVAL`, default **never**) and a **configurable sandbox** (`OFDD_CODEX_EXEC_SANDBOX`, default **danger-full-access**) so you can reach **127.0.0.1** / the Open-FDD bridge and write scripts in the workdir. If an operator tightened sandbox and localhost fails, say which env vars to relax or use **Plots** for **clean-metrics** instead of guessing.
- For **how-to retrieval**, use MCP `POST …/tools/search_docs` with queries that name the task (e.g. *agent operator playbook*, *BACnet driver*, *clean-metrics*, *BRICK modeling*, *FDD rules run*, *readiness*) so RAG returns the indexed operator playbook and related docs.
- When changing data or rules, default to **preview** endpoints (`commit:false`) before destructive commits unless the human explicitly commits.
- Reference `GET /assistant/readiness` for UI-aligned deep links to paste back to humans.
- If MCP action tools are disabled, say what env vars to set instead of pretending writes succeeded.
- Never invent site IDs: use `GET /sites` or readiness output.
"""


def run_openfdd_agent_turn(
    *,
    message: str,
    workdir_raw: str | None,
    task_summary: str | None,
    force_class: str | None,
    system_context: str | None,
) -> dict[str, Any]:
    codex = resolve_codex_executable()
    if not codex:
        return {
            "ok": False,
            "error": "codex_cli_missing",
            "detail": "Install codex or set OFDD_CODEX_CMD (see /local-codex/diagnostics).",
        }

    workdir = resolve_workdir(workdir_raw)
    if not workdir.is_dir():
        return {"ok": False, "error": "bad_workdir", "detail": f"Not a directory: {workdir}"}

    summary = (task_summary or message or "").strip()[:8000]
    if force_class in ("simple", "complex"):
        tier: Any = force_class
        reason = "forced tier from client"
    else:
        default_raw = (os.environ.get("OFDD_AGENT_ROUTE_DEFAULT") or "simple").strip().lower()
        default = "complex" if default_raw == "complex" else "simple"
        tier, reason = classify_openfdd_task(summary, default=default)

    ctx = build_agent_bootstrap_context()
    ctx_md = format_agent_context_markdown(ctx)
    tier_md = routing_instructions_for_tier(tier)

    extra = (system_context or "").strip()
    system = "\n\n".join(
        part
        for part in (_openfdd_agent_identity(), ctx_md, tier_md, f"### Operator extra instructions\n{extra}" if extra else "")
        if part
    )

    stdin_text = build_chat_stdin(user_message=message, system_context=system)

    simple_timeout = safe_int_from_env("OFDD_CODEX_EXEC_TIMEOUT_SIMPLE", 420)
    complex_timeout = safe_int_from_env("OFDD_CODEX_EXEC_TIMEOUT_COMPLEX", 900)
    timeout_s = complex_timeout if tier == "complex" else simple_timeout

    out = run_codex_exec(codex, workdir, stdin_text=stdin_text, timeout_s=timeout_s)
    slim = {
        "bridge_base": ctx.get("bridge_base"),
        "mcp_rest_base": ctx.get("mcp_rest_base"),
        "ui_public_base": ctx.get("ui_public_base"),
    }
    return {
        **out,
        "ok": bool(out.get("ok")),
        "task_class": tier,
        "route_reason": reason,
        "timeout_seconds": timeout_s,
        "bootstrap_summary": slim,
    }
