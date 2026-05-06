"""Built-in Open-FDD agent: Codex CLI + stack context + SIMPLE/COMPLEX routing."""

from __future__ import annotations

import os
from typing import Any, cast

from open_fdd.gateway.local_codex_cli import (
    DEFAULT_CODEX_MODEL_COMPLEX_FALLBACK,
    DEFAULT_CODEX_MODEL_COMPLEX_PRIMARY,
    DEFAULT_CODEX_MODEL_SIMPLE,
    build_chat_stdin,
    resolve_codex_executable,
    resolve_workdir,
    run_codex_exec,
    run_codex_route_classify_llm,
    safe_int_from_env,
    stderr_suggests_unknown_codex_model,
)
from open_fdd.gateway.local_codex_cli import _env_bool as _codex_env_bool
from open_fdd.gateway.local_codex_cli import _env_trim as _codex_env_trim
from open_fdd.gateway.openfdd_agent_context import build_agent_bootstrap_context, format_agent_context_markdown
from open_fdd.gateway.openfdd_agent_routing import TaskTier, classify_openfdd_task, routing_instructions_for_tier


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

Model routing (bridge-injected): SIMPLE work uses a lighter Codex model; COMPLEX uses the strong default with automatic fallback if the primary model is unavailable on this account. The system block includes a **Routing mode** section (SIMPLE vs COMPLEX) for behavior — do not confuse that with the underlying model name shown in Codex diagnostics.
"""


def run_openfdd_agent_turn(
    *,
    message: str,
    workdir_raw: str | None,
    task_summary: str | None,
    force_class: str | None,
    system_context: str | None,
    conversation_history: list[tuple[str, str]] | None = None,
    human_requested_complex: bool = False,
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
    human_route = False
    if force_class == "simple":
        tier: TaskTier = "simple"
        reason = "forced SIMPLE from client"
    elif force_class == "complex":
        tier = "complex"
        if human_requested_complex:
            reason = "human-requested COMPLEX evaluation"
            human_route = True
        else:
            reason = "forced COMPLEX from client"
    elif human_requested_complex:
        tier = "complex"
        reason = "human-requested COMPLEX evaluation"
        human_route = True
    else:
        default_raw = (os.environ.get("OFDD_AGENT_ROUTE_DEFAULT") or "simple").strip().lower()
        default: TaskTier = "complex" if default_raw == "complex" else "simple"
        tier, reason = classify_openfdd_task(summary, default=default)
        if _codex_env_bool("OFDD_CODEX_LLM_CLASSIFY", False):
            router_model = _codex_env_trim("OFDD_CODEX_MODEL_SIMPLE", DEFAULT_CODEX_MODEL_SIMPLE)
            llm_tier, llm_note = run_codex_route_classify_llm(
                codex,
                workdir,
                task_summary=summary,
                classify_model=router_model,
            )
            if llm_tier is not None:
                tier = llm_tier
                reason = f"{reason}; {llm_note} ({router_model})"

    model_simple = _codex_env_trim("OFDD_CODEX_MODEL_SIMPLE", DEFAULT_CODEX_MODEL_SIMPLE)
    model_complex_primary = _codex_env_trim("OFDD_CODEX_MODEL_COMPLEX", DEFAULT_CODEX_MODEL_COMPLEX_PRIMARY)
    model_complex_fallback = _codex_env_trim("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", DEFAULT_CODEX_MODEL_COMPLEX_FALLBACK)

    ctx = build_agent_bootstrap_context()
    ctx_md = format_agent_context_markdown(ctx)
    slim = {
        "bridge_base": ctx.get("bridge_base"),
        "mcp_rest_base": ctx.get("mcp_rest_base"),
        "ui_public_base": ctx.get("ui_public_base"),
    }
    extra = (system_context or "").strip()

    simple_timeout = safe_int_from_env("OFDD_CODEX_EXEC_TIMEOUT_SIMPLE", 420)
    complex_timeout = safe_int_from_env("OFDD_CODEX_EXEC_TIMEOUT_COMPLEX", 900)

    def _tier_bundle(t: TaskTier) -> tuple[str, str, str, int]:
        tier_md = routing_instructions_for_tier(t)
        system_inner = "\n\n".join(
            part
            for part in (
                _openfdd_agent_identity(),
                ctx_md,
                tier_md,
                f"### Operator extra instructions\n{extra}" if extra else "",
            )
            if part
        )
        std_in = build_chat_stdin(
            user_message=message,
            system_context=system_inner,
            conversation_history=conversation_history,
        )
        m_complex = model_complex_primary
        m_simple = model_simple
        chosen = m_simple if t == "simple" else m_complex
        tout = simple_timeout if t == "simple" else complex_timeout
        return system_inner, std_in, chosen, tout

    _, stdin_text, chosen_model, timeout_s = _tier_bundle(cast(TaskTier, tier))
    escalation_eligible = (
        tier == "simple"
        and force_class is None
        and not human_requested_complex
        and _codex_env_bool("OFDD_AGENT_ESCALATE_ON_FAILURE", True)
    )
    route_reason_before_turn = reason

    out = run_codex_exec(codex, workdir, stdin_text=stdin_text, timeout_s=timeout_s, model=chosen_model)
    model_attempts: list[str] = [chosen_model]
    escalated_simple_failure = False
    critic_used = False
    critic_model: str | None = None

    if escalation_eligible and not out.get("ok"):
        escalated_simple_failure = True
        tier = cast(TaskTier, "complex")
        reason = (
            f"{route_reason_before_turn}; escalated after SIMPLE codex failed "
            f"(returncode={out.get('returncode')})"
        )
        _, stdin_text, chosen_model, timeout_s = _tier_bundle("complex")
        out = run_codex_exec(codex, workdir, stdin_text=stdin_text, timeout_s=timeout_s, model=chosen_model)
        model_attempts = [model_attempts[0], chosen_model]

    if (
        tier == "complex"
        and not out.get("ok")
        and chosen_model == model_complex_primary
        and model_complex_fallback.strip()
        and model_complex_fallback.strip() != model_complex_primary.strip()
        and stderr_suggests_unknown_codex_model(str(out.get("stderr") or ""), str(out.get("stdout") or ""))
    ):
        out = run_codex_exec(
            codex,
            workdir,
            stdin_text=stdin_text,
            timeout_s=timeout_s,
            model=model_complex_fallback.strip(),
        )
        model_attempts.append(model_complex_fallback.strip())
        out["codex_model_fallback_used"] = True

    critic_enabled = _codex_env_bool("OFDD_AGENT_SIMPLE_COMPLEX_CRITIC", False)
    if (
        critic_enabled
        and tier == "simple"
        and force_class != "simple"
        and bool(out.get("ok"))
        and not human_requested_complex
    ):
        critic_prompt = (
            "You are a strict final reviewer. Review the draft answer below for correctness, safety, "
            "and concrete actionability for Open-FDD operators. If needed, provide a corrected final answer.\n\n"
            f"User message:\n{message}\n\n"
            f"Draft answer:\n{str(out.get('stdout') or '').strip()}\n\n"
            "Return only the final answer to show the human (no rubric, no preamble)."
        )
        critic_stdin = build_chat_stdin(
            user_message=critic_prompt,
            system_context="\n\n".join(
                part for part in (_openfdd_agent_identity(), ctx_md, routing_instructions_for_tier("complex")) if part
            ),
            conversation_history=None,
        )
        critic_timeout = safe_int_from_env("OFDD_CODEX_EXEC_TIMEOUT_CRITIC", complex_timeout)
        critic_out = run_codex_exec(
            codex,
            workdir,
            stdin_text=critic_stdin,
            timeout_s=critic_timeout,
            model=model_complex_primary,
        )
        critic_model = model_complex_primary
        if (
            not critic_out.get("ok")
            and model_complex_fallback.strip()
            and model_complex_fallback.strip() != model_complex_primary.strip()
            and stderr_suggests_unknown_codex_model(
                str(critic_out.get("stderr") or ""), str(critic_out.get("stdout") or "")
            )
        ):
            critic_out = run_codex_exec(
                codex,
                workdir,
                stdin_text=critic_stdin,
                timeout_s=critic_timeout,
                model=model_complex_fallback.strip(),
            )
            critic_model = model_complex_fallback.strip()
        if critic_out.get("ok") and str(critic_out.get("stdout") or "").strip():
            out["stdout"] = str(critic_out.get("stdout") or "").strip()
            critic_used = True
            model_attempts.append(str(critic_model or model_complex_primary))

    return {
        **out,
        "ok": bool(out.get("ok")),
        "task_class": tier,
        "route_reason": reason,
        "timeout_seconds": timeout_s,
        "codex_model": out.get("codex_model") or chosen_model,
        "codex_model_attempts": model_attempts,
        "bootstrap_summary": slim,
        **({"critic_used": True, "critic_model": critic_model} if critic_used else {}),
        **({"human_route": True} if human_route else {}),
        **({"simple_failure_escalated": True} if escalated_simple_failure else {}),
    }
