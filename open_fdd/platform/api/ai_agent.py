"""AI assistant API: Overview chat (read-only, data-model driven).

Phase 1 goal: neat chat UI on Overview that can answer “what’s going on?”
questions (faults, rules, schedules, BACnet status, HVAC health summary)
WITHOUT mutating the system. This module exposes POST /ai/agent with
mode="overview_chat" and builds a small, read-only context from the DB
and unified data model for the LLM.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from open_fdd.platform.api.analytics import (
    fetch_fault_timeseries_data,
    fetch_fault_results_sample,
    fetch_faults_by_equipment_data,
    fetch_point_timeseries_data,
    get_point_ids_for_agent,
)
from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn
from open_fdd.platform.graph_model import get_serialization_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


class AiAgentRequest(BaseModel):
    """Request body for POST /ai/agent."""

    mode: str = Field(
        "overview_chat",
        description='Agent mode. Phase 1 supports only "overview_chat".',
    )
    message: str = Field(
        ...,
        description="User question, e.g. 'How is the HVAC running overall?'",
    )
    model: str = Field(
        "gpt-5-mini",
        description="OpenAI model to use (e.g. gpt-5-mini, gpt-5.4-pro).",
    )
    site_id: Optional[str] = Field(
        None,
        description="Optional site filter (UUID or name/description). When set, summaries focus on that site.",
    )
    include_context: bool = Field(
        False,
        description="If true, echo the structured context used for the answer back to the client (for debugging).",
    )
    plot_point_ids: Optional[List[str]] = Field(
        None,
        description="Optional list of point UUIDs to include as a point-timeseries chart (last 7 days).",
    )
    include_table_fault_results: Optional[int] = Field(
        None,
        ge=1,
        le=50,
        description="If set, include last N fault_results rows as tabular data (e.g. 10).",
    )


class AiAgentResponse(BaseModel):
    """Response body for POST /ai/agent."""

    mode: str = Field(..., description='Echoed mode (currently always "overview_chat").')
    answer: str = Field(
        ...,
        description="LLM answer for the operator, formatted as markdown-friendly text.",
    )
    context: Optional[dict[str, Any]] = Field(
        None,
        description="Optional structured context (counts, summaries). Present only when include_context=true.",
    )
    plots: Optional[dict[str, Any]] = Field(
        None,
        description="Optional fault-timeseries payload for inline chart (last 7 days).",
    )
    tables: Optional[dict[str, Any]] = Field(
        None,
        description="Optional faults-by-equipment payload for inline table (last 7 days).",
    )
    point_plots: Optional[dict[str, Any]] = Field(
        None,
        description="Optional point-timeseries payload when plot_point_ids was provided.",
    )
    table_fault_results: Optional[dict[str, Any]] = Field(
        None,
        description="Optional last N fault_results rows when include_table_fault_results was set.",
    )
    last_fdd_error: Optional[str] = Field(
        None,
        description="When the last FDD run failed, the raw error message for the UI to display.",
    )


def _safe_scalar(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


# Max characters of docs to include per call (~7k tokens). Full pdf/open-fdd-docs.txt is ~213k chars / ~56k tokens—too large to send every time.
DOCS_EXCERPT_MAX_CHARS = 28_000


def _load_docs_excerpt(max_chars: int = DOCS_EXCERPT_MAX_CHARS) -> str:
    """Load an excerpt of the Open-FDD docs so the agent can explain what the platform is. Returns empty string if file not found."""
    path = os.environ.get("OFDD_DOCS_PATH")
    if not path:
        # Try repo root: cwd or open_fdd/../.. (file is open_fdd/platform/api/ai_agent.py -> parents[3] = repo root)
        for base in [Path.cwd(), Path(__file__).resolve().parents[3]]:
            candidate = base / "pdf" / "open-fdd-docs.txt"
            if candidate.is_file():
                path = str(candidate)
                break
    if not path or not Path(path).is_file():
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        if len(content) >= max_chars:
            content += "\n\n[... documentation truncated ...]"
        return content.strip()
    except Exception as e:
        logger.warning("Could not load docs excerpt for AI agent: %s", e)
        return ""


def _build_overview_context(site_filter: str | None = None) -> dict[str, Any]:
    """Build a small, read-only context for the Overview assistant.

    The goal is to give the LLM enough structure to answer “what’s going on?”
    without loading full timeseries. Everything here is derived from the DB
    and unified data model and is safe to expose.
    """
    context: dict[str, Any] = {}

    # High-level data-model summary: sites, equipment, points, polling vs non-polling, rules.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM sites")
                sites_row = cur.fetchone() or {"c": 0}
                cur.execute("SELECT COUNT(*) AS c FROM equipment")
                equip_row = cur.fetchone() or {"c": 0}
                cur.execute("SELECT COUNT(*) AS c FROM points")
                points_row = cur.fetchone() or {"c": 0}
                cur.execute(
                    "SELECT COUNT(*) AS c FROM points WHERE COALESCE(polling, true) = true"
                )
                polling_row = cur.fetchone() or {"c": 0}
                cur.execute("SELECT COUNT(*) AS c FROM points WHERE COALESCE(polling, true) = false")
                non_polling_row = cur.fetchone() or {"c": 0}
                # Rules summary (count + basic definitions so the agent can see configured faults).
                cur.execute("SELECT COUNT(*) AS c FROM fault_definitions")
                rules_row = cur.fetchone() or {"c": 0}

                # Rough HVAC shape from the data model: equipment types and BRICK point types.
                cur.execute(
                    """
                    SELECT equipment_type, COUNT(*) AS c
                    FROM equipment
                    GROUP BY equipment_type
                    ORDER BY c DESC NULLS LAST
                    LIMIT 12
                    """
                )
                equip_type_rows = cur.fetchall() or []
                cur.execute(
                    """
                    SELECT brick_type, COUNT(*) AS c
                    FROM points
                    GROUP BY brick_type
                    ORDER BY c DESC NULLS LAST
                    LIMIT 20
                    """
                )
                brick_rows = cur.fetchall() or []

                # Configured fault definitions (YAML-backed rules) – same as /faults/definitions.
                cur.execute(
                    """
                    SELECT fault_id, name, category, equipment_types
                    FROM fault_definitions
                    ORDER BY name
                    LIMIT 50
                    """
                )
                rule_defs = cur.fetchall() or []

        context["data_model"] = {
            "site_count": _safe_scalar(sites_row.get("c")),
            "equipment_count": _safe_scalar(equip_row.get("c")),
            "point_count": _safe_scalar(points_row.get("c")),
            "polling_points": _safe_scalar(polling_row.get("c")),
            "non_polling_points": _safe_scalar(non_polling_row.get("c")),
            "rule_definitions": _safe_scalar(rules_row.get("c")),
            "equipment_by_type": [
                {
                    "equipment_type": row.get("equipment_type"),
                    "count": _safe_scalar(row.get("c")),
                }
                for row in equip_type_rows
            ],
            "points_by_brick_type": [
                {
                    "brick_type": row.get("brick_type"),
                    "count": _safe_scalar(row.get("c")),
                }
                for row in brick_rows
            ],
        }
        context["rules"] = {
            "definitions": [
                {
                    "fault_id": row.get("fault_id"),
                    "name": row.get("name"),
                    "category": row.get("category"),
                    "equipment_types": row.get("equipment_types"),
                }
                for row in rule_defs
            ]
        }
    except Exception:
        logger.exception("Failed to build data model summary for AI agent")
        context.setdefault("warnings", []).append(
            "Could not summarize data model (DB error); answer may be less detailed."
        )

    # Fault summary and last FDD run (high level) + basic schedule hints from graph status.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Active faults
                if site_filter:
                    cur.execute(
                        """
                        SELECT COUNT(*) AS active_faults
                        FROM fault_state fs
                        JOIN sites s ON s.id = fs.site_id
                        WHERE fs.active = true
                          AND (s.id::text = %s OR s.name ILIKE %s OR s.description ILIKE %s)
                        """,
                        (site_filter, site_filter, site_filter),
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*) AS active_faults FROM fault_state WHERE active = true"
                    )
                fault_row = cur.fetchone() or {"active_faults": 0}

                # Last FDD run (include error_message so the agent can explain failures)
                cur.execute(
                    """
                    SELECT run_ts, status, sites_processed, faults_written, error_message
                    FROM fdd_run_log
                    ORDER BY run_ts DESC
                    LIMIT 1
                    """
                )
                fdd_row = cur.fetchone()

        context["faults"] = {
            "active_faults": _safe_scalar(fault_row.get("active_faults")),
        }
        if fdd_row:
            run_ts = fdd_row.get("run_ts")
            context["fdd"] = {
                "last_run_ts": (
                    run_ts.isoformat() if hasattr(run_ts, "isoformat") else str(run_ts)
                ),
                "last_run_status": fdd_row.get("status"),
                "sites_processed": _safe_scalar(fdd_row.get("sites_processed")),
                "faults_written": _safe_scalar(fdd_row.get("faults_written")),
                "last_run_error_message": fdd_row.get("error_message"),
            }
        # Schedule-ish info: last graph serialization from in-memory status (background jobs).
        try:
            status = get_serialization_status()
            graph = status.get("graph_serialization") or {}
            context["schedules"] = {
                "last_graph_serialization_ok": bool(graph.get("last_ok")),
                "last_graph_serialization_at": graph.get("last_serialization_at"),
            }
        except Exception:
            # Non-fatal; just omit schedules if unavailable
            logger.debug(
                "Could not fetch graph serialization status", exc_info=True
            )
    except Exception:
        logger.exception("Failed to build fault/FDD summary for AI agent")
        context.setdefault("warnings", []).append(
            "Could not summarize faults/FDD run; answer may be less detailed."
        )

    # BACnet snapshot: number of devices and polling points with a BACnet device id.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT bacnet_device_id) AS device_count
                    FROM points
                    WHERE bacnet_device_id IS NOT NULL
                    """
                )
                devices_row = cur.fetchone() or {"device_count": 0}
                cur.execute(
                    """
                    SELECT COUNT(*) AS polling_bacnet_points
                    FROM points
                    WHERE bacnet_device_id IS NOT NULL
                      AND COALESCE(polling, true) = true
                    """
                )
                bacnet_points_row = cur.fetchone() or {"polling_bacnet_points": 0}

        context["bacnet"] = {
            "device_count": _safe_scalar(devices_row.get("device_count")),
            "polling_points": _safe_scalar(bacnet_points_row.get("polling_bacnet_points")),
        }
    except Exception:
        logger.exception("Failed to build BACnet snapshot for AI agent")
        context.setdefault("warnings", []).append(
            "Could not summarize BACnet devices; answer may be less detailed."
        )

    return context


def _build_overview_prompt(context: dict[str, Any], user_message: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for overview_chat."""
    docs_excerpt = _load_docs_excerpt()
    system_prompt = (
        "You are the Overview assistant for the Open-FDD HVAC fault detection platform. "
        "You have read-only access to summaries of the building data model, BACnet devices, "
        "faults, FDD runs, and the list of configured fault rules (context.rules.definitions). "
        "Use ONLY the structured context provided and general HVAC knowledge; do not invent data. "
        "Explain in concise, operator-friendly language. Never claim to have mutated configuration. "
        "When the last FDD run status is 'error', use last_run_error_message to explain what went wrong. "
        "Your reply is shown together with inline charts and tables (fault timeseries, point timeseries, "
        "faults by equipment, fault result rows). Describe what that data shows; do NOT say you cannot "
        "generate plots or tables—they are attached automatically to your response. "
        "The human is an engineer most likely always generate plots with units on different axes."
    )
    if docs_excerpt:
        system_prompt += (
            "\n\nBelow is an excerpt of the Open-FDD documentation. Use it to answer questions about what Open-FDD is, "
            "how it works, and where to find things (endpoints, concepts). Do not invent details beyond this excerpt and the context.\n\n"
            "--- Open-FDD documentation (excerpt) ---\n\n"
            f"{docs_excerpt}\n\n"
            "--- End excerpt ---"
        )
    context_str = json.dumps(context, indent=2, default=str)
    user_prompt = (
        "Here is the current Open-FDD overview context as JSON (data model, rules, faults, BACnet):\n\n"
        f"{context_str}\n\n"
        "User question:\n"
        f"{user_message}\n\n"
        "Answer using this context. Mention configured faults by name from context.rules.definitions when relevant. "
        "Charts and tables are attached below your answer; describe what they show."
    )
    return system_prompt, user_prompt


class AiAgentError(Exception):
    """Service-layer error mapped to HTTPException in the router."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _call_openai_chat(
    api_key: str,
    base_url: str | None,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float = 60.0,
) -> str:
    """Call OpenAI-compatible chat completion API and return the answer text."""
    if not api_key or not api_key.strip():
        raise AiAgentError(400, "LLM API key is required.")

    try:
        openai_mod = import_module("openai")
    except ImportError:
        raise AiAgentError(
            500,
            "openai package is not installed. Add it with: pip install 'openai>=1.0'",
        ) from None

    OpenAI = getattr(openai_mod, "OpenAI", None)
    AuthenticationError = getattr(openai_mod, "AuthenticationError", Exception)
    RateLimitError = getattr(openai_mod, "RateLimitError", Exception)
    APITimeoutError = getattr(openai_mod, "APITimeoutError", Exception)
    BadRequestError = getattr(openai_mod, "BadRequestError", Exception)
    if OpenAI is None:
        raise AiAgentError(
            500,
            "openai package is present but OpenAI client is unavailable.",
        )

    try:
        client_kwargs: dict[str, Any] = {"api_key": api_key.strip(), "timeout": timeout}
        if base_url:
            client_kwargs["base_url"] = base_url.strip()
        client = OpenAI(**client_kwargs)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=1,  # Some models (e.g. gpt-5-mini) only support default 1
        )
    except AuthenticationError as err:
        raise AiAgentError(
            401, "Invalid OpenAI API key. Check your key and try again."
        ) from err
    except RateLimitError as err:
        raise AiAgentError(
            429, "OpenAI rate limit exceeded. Wait a moment and try again."
        ) from err
    except APITimeoutError as err:
        raise AiAgentError(504, f"OpenAI API timed out after {int(timeout)}s.") from err
    except BadRequestError as err:
        raise AiAgentError(400, f"OpenAI rejected the request: {err}") from err
    except Exception as exc:
        logger.error("OpenAI chat call failed: %s", type(exc).__name__, exc_info=False)
        raise AiAgentError(502, f"OpenAI API error: {type(exc).__name__}") from exc

    if not response.choices:
        raise AiAgentError(
            502,
            "OpenAI returned no response choices. Try again or check the model name.",
        )
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise AiAgentError(
            502,
            "OpenAI returned an empty response. Try again with a simpler question or check the model name.",
        )
    return content


@router.post(
    "/agent",
    response_model=AiAgentResponse,
    summary="AI assistant for Overview (read-only)",
    response_description="Read-only Overview assistant answer and optional context.",
)
def ai_agent(body: AiAgentRequest) -> AiAgentResponse:
    """AI assistant entrypoint.

    Currently supports only mode=\"overview_chat\": builds a read-only context from the
    data model and FDD state, calls Open‑Claw (OpenAI-compatible) once, and returns a natural-language answer.
    """
    if body.mode != "overview_chat":
        raise HTTPException(
            400,
            f"Unsupported mode {body.mode!r}. Phase 1 supports only mode='overview_chat'.",
        )

    settings = get_platform_settings()
    open_claw_ready = bool(getattr(settings, "open_claw_base_url", None)) and bool(
        getattr(settings, "open_claw_api_key", None)
    )
    if not open_claw_ready:
        raise HTTPException(
            503,
            "AI disabled: Open‑Claw is not configured. Bootstrap with --with-open-claw and set OFDD_OPEN_CLAW_BASE_URL + OFDD_OPEN_CLAW_API_KEY.",
        )

    context = _build_overview_context(site_filter=body.site_id)
    system_prompt, user_prompt = _build_overview_prompt(context, body.message)

    # Validate model: gpt-5-mini is the only guaranteed chat/completions model here.
    model = body.model
    supported_chat_models = {"gpt-5-mini"}
    if model not in supported_chat_models:
        logger.warning(
            "Requested model %s is not supported for chat/completions; "
            "falling back to gpt-5-mini for overview_chat.",
            model,
        )
        model = "gpt-5-mini"

    api_key = settings.open_claw_api_key or ""
    base_url = settings.open_claw_base_url

    try:
        answer = _call_openai_chat(
            api_key=api_key,
            base_url=base_url,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
    except AiAgentError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    # Default window for plots/tables: today and yesterday (2-day date range).
    # Short enough for quick troubleshooting but still useful for “what just happened?” questions.
    end_date = date.today()
    start_date = end_date - timedelta(days=1)
    try:
        plots = fetch_fault_timeseries_data(
            site_id=body.site_id,
            start_date=start_date,
            end_date=end_date,
            bucket="day",
        )
        tables = fetch_faults_by_equipment_data(
            site_id=body.site_id,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception:
        logger.exception("Failed to attach plots/tables for overview_chat")
        plots = None
        tables = None

    # Always attach point plots: use requested IDs or auto-select up to 20 points.
    point_plots = None
    try:
        point_ids = body.plot_point_ids if body.plot_point_ids else get_point_ids_for_agent(body.site_id, limit=20)
        if point_ids:
            point_plots = fetch_point_timeseries_data(
                point_ids=point_ids,
                start_date=start_date,
                end_date=end_date,
            )
    except Exception:
        logger.exception("Failed to attach point_plots for overview_chat")

    # Always attach fault results table (default 20 rows) so the agent can show tabular data.
    table_fault_results = None
    try:
        limit = body.include_table_fault_results if body.include_table_fault_results is not None else 20
        table_fault_results = fetch_fault_results_sample(
            site_id=body.site_id,
            limit=limit,
        )
    except Exception:
        logger.exception("Failed to attach table_fault_results for overview_chat")

    fdd = context.get("fdd") or {}
    last_fdd_error = None
    if fdd.get("last_run_status") == "error" and fdd.get("last_run_error_message"):
        last_fdd_error = str(fdd.get("last_run_error_message"))

    return AiAgentResponse(
        mode="overview_chat",
        answer=answer,
        context=context if body.include_context else None,
        plots=plots,
        tables=tables,
        point_plots=point_plots,
        table_fault_results=table_fault_results,
        last_fdd_error=last_fdd_error,
    )

