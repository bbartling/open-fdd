from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from typing import Annotated, Any

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .retrieval import RagIndex

INDEX_PATH = Path(os.getenv("OFDD_MCP_RAG_INDEX_PATH", "./stack/mcp-rag/index/rag_index.json"))
OFDD_API_URL = os.getenv("OFDD_MCP_OFDD_API_URL", "http://127.0.0.1:8765").rstrip("/")
OFDD_API_KEY = os.getenv("OFDD_MCP_OFDD_API_KEY", "")


def _loopback_typo_warning(url: str) -> str | None:
    """
    Detect the common typo ``127.0.1`` (missing ``.0`` before the final octet).

    Valid loopback is ``127.0.0.1``. ``http://127.0.1:8090`` fails DNS/connect in most setups.
    """
    u = str(url or "").strip()
    if not u:
        return None
    # e.g. http://127.0.1:8765 — third octet is "1" immediately followed by :port (not .0.1)
    if re.search(r"://127\.0\.1:\d", u):
        return (
            "bridge_url looks like a typo: use 127.0.0.1 (four octets), "
            "e.g. http://127.0.0.1:8765 — not http://127.0.1:8765"
        )
    return None


def mcp_listen_host() -> str:
    """Bind host for MCP (must match ``run_mcp_rag`` / health hint)."""
    h = os.getenv("OFDD_MCP_LISTEN_HOST", "127.0.0.1").strip()
    return h or "127.0.0.1"


def mcp_listen_port() -> int:
    raw = os.getenv("OFDD_MCP_LISTEN_PORT", "8090")
    try:
        return int(raw)
    except ValueError:
        return 8090


ENABLE_ACTION_TOOLS = os.getenv("OFDD_MCP_ENABLE_ACTION_TOOLS", "false").lower() == "true"
_timeout_value = os.getenv("OFDD_MCP_HTTP_TIMEOUT_SEC")
try:
    TIMEOUT = float(_timeout_value) if _timeout_value is not None else 20.0
except ValueError:
    TIMEOUT = 20.0

app = FastAPI(title="Open-FDD MCP RAG Service", version="1.0.0")
_idx: RagIndex | None = None


class SearchDocsRequest(BaseModel):
    query: str
    top_k: int = Field(default=6, ge=1, le=25)
    tags: list[str] | None = None


class SearchApiCapabilitiesRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str
    top_k: int = Field(default=6, ge=1, le=25)


class GetSectionRequest(BaseModel):
    path_or_id: str


class DriverConfigRequest(BaseModel):
    payload: dict[str, Any]


class IngestRequest(BaseModel):
    site_id: str


class ImportRequest(BaseModel):
    payload: dict[str, Any]
    replace: bool = True


class ApplySiteProfilesBridgeRequest(BaseModel):
    """Absolute path to ``site_profiles.yaml`` under the repo ``examples/`` tree."""

    profiles_yaml: str
    reset: bool = True


class SparqlRequest(BaseModel):
    query: str


class OpenClawCronValidateRequest(BaseModel):
    expression: str


class OpenClawOpsTemplateRequest(BaseModel):
    shell: str = "posix"
    name: str = "Open-FDD Site Sweep"
    cron: str = "0 */6 * * *"
    tz: str = "America/Chicago"
    session: str = "isolated"
    message: str = "Run Open-FDD health checks, ingest checks, and FDD summary for active sites."
    failure_destination: str = "ops-alerts"
    alert_on_skipped: bool = True
    idempotency_key: str = "open-fdd-site-sweep-v1"
    reconcile_tag: str = "portfolio-default"
    correlation_id_prefix: str = "ofdd"

    @field_validator("shell", mode="before")
    @classmethod
    def _normalize_shell(cls, value: Any) -> str:
        shell = str(value or "posix").strip().lower()
        aliases = {"pwsh": "powershell", "powershell": "powershell", "posix": "posix"}
        normalized = aliases.get(shell)
        if normalized is None:
            raise ValueError("shell must be one of: posix, powershell, pwsh")
        return normalized

    @field_validator("session", mode="before")
    @classmethod
    def _normalize_session(cls, value: Any) -> str:
        session = str(value or "isolated").strip().lower()
        aliases = {"isolated": "isolated", "main": "main", "shared": "main"}
        normalized = aliases.get(session)
        if normalized is None:
            raise ValueError("session must be one of: isolated, main, shared")
        return normalized


class OpenClawObservabilityRequest(BaseModel):
    gateway_url: str = "http://127.0.0.1:18789"
    bridge_url: str = "http://127.0.0.1:8765"
    mcp_url: str = "http://127.0.0.1:8090"


class OpenClawMemoryGovernanceRequest(BaseModel):
    site_name: str = "Site A"
    timezone: str = "America/Chicago"


class OpenClawSubagentLanesRequest(BaseModel):
    lane_count: int = Field(default=2, ge=1, le=16)
    class_prefix: str = "simple"
    complex_prefix: str = "complex"


def _load_index() -> RagIndex:
    global _idx
    if _idx is None:
        if not INDEX_PATH.exists():
            raise HTTPException(status_code=503, detail=f"RAG index missing: {INDEX_PATH}")
        try:
            _idx = RagIndex.from_path(INDEX_PATH)
        except (OSError, json.JSONDecodeError) as err:
            raise HTTPException(status_code=503, detail=f"RAG index unreadable: {INDEX_PATH} - {err}") from err
    return _idx


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if OFDD_API_KEY:
        headers["Authorization"] = f"Bearer {OFDD_API_KEY}"
    return headers


def require_action_tools_auth(authorization: Annotated[str | None, Header()] = None) -> None:
    if not ENABLE_ACTION_TOOLS:
        raise HTTPException(status_code=403, detail="Action tools disabled.")
    expected = OFDD_API_KEY.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Action tools enabled but OFDD_MCP_OFDD_API_KEY is empty.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=403, detail="Authorization Bearer token required for action tools.")
    _scheme, _sep, rest = authorization.partition(" ")
    token = rest.strip() if rest else ""
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid API key for action tools.")


def _json_request(method: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{OFDD_API_URL}{path}"
    try:
        response = requests.request(
            method.upper(),
            url,
            headers={**_headers(), "Content-Type": "application/json"},
            json=body if body is not None else None,
            timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=503, detail=f"Upstream request failed: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    if not (response.text or "").strip():
        return {"ok": True}
    try:
        return response.json()
    except ValueError:
        return {"ok": True, "text": response.text}


def _serialize_results(query: str, rows: list[Any]) -> dict[str, Any]:
    return {
        "query": query,
        "count": len(rows),
        "results": [
            {
                "chunk_id": r.chunk_id,
                "score": round(r.score, 5),
                "source": r.source,
                "section": r.section,
                "content": r.content,
                "endpoint_refs": r.endpoint_refs,
                "tags": r.tags,
            }
            for r in rows
        ],
    }


def _validate_cron_expression(expr: str) -> dict[str, Any]:
    def _validate_numeric_token(
        token: str,
        *,
        low: int,
        high: int,
        names: dict[str, int] | None = None,
    ) -> bool:
        raw_parts = token.split(",")
        if not raw_parts:
            return False
        if any(not p.strip() for p in raw_parts):
            return False
        for part in raw_parts:
            if not _validate_part(part.strip(), low=low, high=high, names=names):
                return False
        return True

    def _parse_atom(raw: str, *, names: dict[str, int] | None, low: int, high: int) -> int | None:
        text = raw.strip()
        if text == "":
            return None
        if names and text.lower() in names:
            return names[text.lower()]
        if text.lstrip("+-").isdigit():
            try:
                value = int(text, 10)
            except ValueError:
                return None
            if low <= value <= high:
                return value
        return None

    def _validate_part(part: str, *, low: int, high: int, names: dict[str, int] | None) -> bool:
        if part in {"*", "?"}:
            return True
        base = part
        step_value: int | None = None
        if "/" in part:
            base, step = part.split("/", 1)
            if not step.isdigit():
                return False
            step_value = int(step, 10)
            if step_value <= 0:
                return False
        if base == "*" or base == "?":
            return True
        if "-" in base:
            left, right = base.split("-", 1)
            left_value = _parse_atom(left, names=names, low=low, high=high)
            right_value = _parse_atom(right, names=names, low=low, high=high)
            if left_value is None or right_value is None:
                return False
            return left_value <= right_value
        atom = _parse_atom(base, names=names, low=low, high=high)
        return atom is not None

    value = str(expr or "").strip()
    if not value:
        return {"valid": False, "hints": ["Cron expression is required."]}
    if value.startswith("@"):
        ok = {"@yearly", "@annually", "@monthly", "@weekly", "@daily", "@hourly", "@reboot"}
        if value.lower() in ok:
            return {"valid": True, "hints": ["Shorthand schedule detected."]}
        return {"valid": False, "hints": ["Unknown shorthand. Try @hourly, @daily, or a 5-field cron."]}
    fields = value.split()
    if len(fields) not in {5, 6}:
        return {"valid": False, "hints": ["Use 5 fields (or 6 fields with seconds)."]}
    allowed = re.compile(r"^[\d*/,\-?A-Za-z#L]+$")
    for token in fields:
        if not allowed.match(token):
            return {"valid": False, "hints": [f"Invalid token '{token}'. Use digits, *, /, -, commas, ?, names."]}
    month_names = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    weekday_names = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
    if len(fields) == 5:
        specs = [
            ("minute", 0, 59, None),
            ("hour", 0, 23, None),
            ("day", 1, 31, None),
            ("month", 1, 12, month_names),
            ("weekday", 0, 6, weekday_names),
        ]
    else:
        specs = [
            ("seconds", 0, 59, None),
            ("minute", 0, 59, None),
            ("hour", 0, 23, None),
            ("day", 1, 31, None),
            ("month", 1, 12, month_names),
            ("weekday", 0, 6, weekday_names),
        ]
    for idx, (label, low, high, names) in enumerate(specs):
        token = fields[idx]
        if not _validate_numeric_token(token, low=low, high=high, names=names):
            return {
                "valid": False,
                "hints": [f"Invalid {label} token '{token}'. Expected values in {low}-{high} for {label}."],
            }
    hints = [
        "5-field cron: minute hour day month weekday."
        if len(fields) == 5
        else "6-field cron: seconds minute hour day month weekday."
    ]
    return {"valid": True, "hints": hints}


def _build_openclaw_ops_templates(req: OpenClawOpsTemplateRequest) -> dict[str, Any]:
    shell = req.shell
    session = req.session

    def _quote_for_shell(value: object, current_shell: str) -> str:
        text = str(value or "")
        if current_shell == "powershell":
            return "'" + text.replace("'", "''") + "'"
        return "'" + text.replace("'", "'\"'\"'") + "'"

    cont = " `" if shell == "powershell" else " \\"
    cron_cmd = [
        "openclaw cron add",
        f"--name {_quote_for_shell(req.name, shell)}",
        f"--cron {_quote_for_shell(req.cron, shell)}",
        f"--tz {_quote_for_shell(req.tz, shell)}",
        f"--session {session}",
    ]
    if session == "main":
        cron_cmd += [f"--system-event {_quote_for_shell(req.message, shell)}", "--wake now"]
    else:
        cron_cmd += [f"--message {_quote_for_shell(req.message, shell)}", "--announce"]
    if str(req.failure_destination or "").strip():
        cron_cmd += [f"--failure-destination {_quote_for_shell(req.failure_destination, shell)}"]
    if bool(req.alert_on_skipped):
        cron_cmd += ["--alert-on-skipped"]
    if str(req.idempotency_key or "").strip():
        cron_cmd += [f"--idempotency-key {_quote_for_shell(req.idempotency_key, shell)}"]
    if str(req.reconcile_tag or "").strip():
        cron_cmd += [f"--reconcile-tag {_quote_for_shell(req.reconcile_tag, shell)}"]
    if str(req.correlation_id_prefix or "").strip():
        cron_cmd += [f"--correlation-prefix {_quote_for_shell(req.correlation_id_prefix, shell)}"]
    joined = f"{cont}\n  ".join(cron_cmd)
    memory = (
        "Set-Content \"$HOME/.openclaw/workspace/MEMORY.md\" -Value \"\"\n"
        "Remove-Item \"$HOME/.openclaw/workspace/memory/*.md\" -ErrorAction SilentlyContinue"
        if shell == "powershell"
        else "truncate -s 0 ~/.openclaw/workspace/MEMORY.md\nrm -f ~/.openclaw/workspace/memory/*.md"
    )
    skills_refresh = (
        "openclaw skills list --eligible\nopenclaw skills update --all\n"
        "# optional clean reinstall path\n"
        "# Remove-Item -Recurse -Force ~/.openclaw/workspace/skills/<skill-name>\n"
        "# openclaw skills install <skill-slug>"
        if shell == "powershell"
        else "openclaw skills list --eligible\nopenclaw skills update --all\n"
        "# optional clean reinstall path\n"
        "# rm -rf ~/.openclaw/workspace/skills/<skill-name>\n"
        "# openclaw skills install <skill-slug>"
    )
    return {
        "cron_add": joined,
        "cron_cleanup": (
            "openclaw cron list\n"
            "# run reconciliation / skipped-run visibility:\n"
            "openclaw cron runs --recent 20\n"
            "# remove one:\n"
            "openclaw cron remove <job-id>"
        ),
        "skills_refresh": skills_refresh,
        "memory_cleanup": memory,
    }


def _build_observability_baseline(req: OpenClawObservabilityRequest) -> dict[str, Any]:
    gateway = str(req.gateway_url or "").rstrip("/")
    bridge = str(req.bridge_url or "").rstrip("/")
    mcp = str(req.mcp_url or "").rstrip("/")
    checks = [
        {"name": "openclaw_gateway_health", "url": f"{gateway}/health", "interval_sec": 30},
        {"name": "openfdd_bridge_health", "url": f"{bridge}/health", "interval_sec": 30},
        {"name": "openfdd_mcp_health", "url": f"{mcp}/health", "interval_sec": 30},
    ]
    return {
        "checks": checks,
        "slo_targets": {
            "cron_success_rate_7d": ">=99%",
            "skipped_run_rate_7d": "<1%",
            "p95_tool_latency_ms": "<5000",
        },
        "run_reconciliation": {
            "required_fields": ["job_id", "scheduled_at", "started_at", "finished_at", "status", "correlation_id"],
            "query_hint": "openclaw cron runs --recent 200 --json",
        },
    }


def _build_memory_governance_profile(req: OpenClawMemoryGovernanceRequest) -> dict[str, Any]:
    site = str(req.site_name or "Site A")
    tz = str(req.timezone or "America/Chicago")
    memory_md = "\n".join(
        [
            f"# {site} HVAC Memory",
            "",
            "## Durable Facts (long-lived truths)",
            "- Equipment inventory (AHUs, RTUs, boilers, chillers, pumps, VAV groups).",
            "- Controls topology (BAS points, overrides, schedules, lockouts).",
            "- Known quirks with evidence (sensor offsets, bad relays, recurring nuisance faults).",
            "",
            "## Daily Notes (transient incidents)",
            "- Date/time-localized events, alarms, weather anomalies, maintenance actions.",
            "- Close or roll up stale notes weekly into durable facts only when verified.",
            "",
            "## Claim Governance",
            "- Every claim includes: source, timestamp, confidence, and contradiction links.",
            "- Drift policy: if a claim is not reconfirmed in 30 days, mark as stale.",
            "",
            "## Correlation",
            "- Record correlation IDs from OpenClaw run -> Open-FDD tools -> stored logs.",
            f"- Default timezone: {tz}.",
        ]
    )
    return {
        "memory_md_template": memory_md,
        "daily_note_template": (
            "## Incident note\n"
            "- when:\n- site:\n- equipment:\n- symptoms:\n- actions:\n- outcome:\n- correlation_id:\n"
        ),
        "freshness_policy": {"stale_days": 30, "review_cadence": "weekly"},
    }


def _build_subagent_lanes(req: OpenClawSubagentLanesRequest) -> dict[str, Any]:
    count = int(req.lane_count)
    simple = [f"{req.class_prefix}-{idx + 1}" for idx in range(count)]
    complex_lanes = [f"{req.complex_prefix}-{idx + 1}" for idx in range(count)]
    return {
        "env": {
            "OFDD_OPENCLAW_ROUTE_SIMPLE_LANES": ",".join(simple),
            "OFDD_OPENCLAW_ROUTE_COMPLEX_LANES": ",".join(complex_lanes),
        },
        "notes": [
            "Route by site_id for deterministic lane selection.",
            "Keep lane count small first (2-4) and scale after observing queue pressure.",
        ],
    }


@app.get("/health", response_model=None)
def health() -> dict[str, Any] | JSONResponse:
    body: dict[str, Any] = {
        "index_exists": INDEX_PATH.exists(),
        "index_path": str(INDEX_PATH),
        "action_tools_enabled": ENABLE_ACTION_TOOLS,
        "bridge_url": OFDD_API_URL,
        # Hint uses OFDD_MCP_LISTEN_HOST / OFDD_MCP_LISTEN_PORT (defaults 127.0.0.1:8090).
        "mcp_listen_hint": (
            f"This MCP service: curl http://{mcp_listen_host()}:{mcp_listen_port()}/health "
            "(use 127.0.0.1 in URLs, not 127.0.1)."
        ),
    }
    typo = _loopback_typo_warning(OFDD_API_URL)
    if typo:
        body["url_warnings"] = [typo]
    try:
        _load_index()
    except HTTPException as exc:
        err_body = {"ok": False, **body, "error": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=err_body)
    return {"ok": True, **body}


@app.get("/manifest")
def manifest() -> dict[str, Any]:
    return {
        "name": "open-fdd-mcp-rag",
        "version": "1.0.0",
        "tools": [
            {"name": "search_docs", "route": "/tools/search_docs", "mode": "read"},
            {"name": "get_doc_section", "route": "/tools/get_doc_section", "mode": "read"},
            {"name": "search_api_capabilities", "route": "/tools/search_api_capabilities", "mode": "read"},
            {"name": "bridge_health", "route": "/tools/bridge_health", "mode": "write_guarded"},
            {"name": "bridge_readiness", "route": "/tools/bridge_readiness", "mode": "write_guarded"},
            {"name": "bridge_apply_site_profiles", "route": "/tools/bridge_apply_site_profiles", "mode": "write_guarded"},
            {"name": "drivers_health", "route": "/tools/drivers_health", "mode": "write_guarded"},
            {"name": "drivers_export", "route": "/tools/drivers_export", "mode": "read"},
            {"name": "drivers_validate", "route": "/tools/drivers_validate", "mode": "read"},
            {"name": "weather_config_get", "route": "/tools/weather_config_get", "mode": "write_guarded"},
            {"name": "weather_config_set", "route": "/tools/weather_config_set", "mode": "write_guarded"},
            {"name": "weather_ingest_run", "route": "/tools/weather_ingest_run", "mode": "write_guarded"},
            {"name": "onboard_config_get", "route": "/tools/onboard_config_get", "mode": "write_guarded"},
            {"name": "onboard_config_set", "route": "/tools/onboard_config_set", "mode": "write_guarded"},
            {"name": "onboard_ingest_run", "route": "/tools/onboard_ingest_run", "mode": "write_guarded"},
            {"name": "bacnet_config_get", "route": "/tools/bacnet_config_get", "mode": "write_guarded"},
            {"name": "bacnet_config_set", "route": "/tools/bacnet_config_set", "mode": "write_guarded"},
            {"name": "bacnet_ingest_run", "route": "/tools/bacnet_ingest_run", "mode": "write_guarded"},
            {"name": "data_model_export", "route": "/tools/data_model_export", "mode": "write_guarded"},
            {"name": "data_model_import", "route": "/tools/data_model_import", "mode": "write_guarded"},
            {"name": "sparql_validate", "route": "/tools/sparql_validate", "mode": "write_guarded"},
            {"name": "openclaw_cron_validate", "route": "/tools/openclaw_cron_validate", "mode": "read"},
            {"name": "openclaw_ops_templates", "route": "/tools/openclaw_ops_templates", "mode": "read"},
            {"name": "openclaw_observability_baseline", "route": "/tools/openclaw_observability_baseline", "mode": "read"},
            {"name": "openclaw_memory_governance", "route": "/tools/openclaw_memory_governance", "mode": "read"},
            {"name": "openclaw_subagent_lanes", "route": "/tools/openclaw_subagent_lanes", "mode": "read"},
        ],
    }


@app.post("/tools/search_docs")
def search_docs(req: SearchDocsRequest) -> dict[str, Any]:
    idx = _load_index()
    return _serialize_results(req.query, idx.search(req.query, top_k=req.top_k, tags=req.tags))


@app.post("/tools/get_doc_section")
def get_doc_section(req: GetSectionRequest) -> dict[str, Any]:
    idx = _load_index()
    data = idx.get_section(req.path_or_id)
    if not data:
        raise HTTPException(status_code=404, detail="Section not found.")
    return data


@app.post("/tools/search_api_capabilities")
def search_api_capabilities(req: SearchApiCapabilitiesRequest) -> dict[str, Any]:
    idx = _load_index()
    return _serialize_results(req.query, idx.search(req.query, top_k=req.top_k, tags=["api"]))


@app.post("/tools/drivers_export")
def drivers_export() -> dict[str, Any]:
    """Sanitized driver bundle from bridge (read-only; for LLM-assisted driver setup)."""
    return _json_request("GET", "/config/drivers/export")


@app.post("/tools/drivers_validate")
def drivers_validate(req: DriverConfigRequest) -> dict[str, Any]:
    """Validate a proposed driver bundle JSON without applying (dry-run)."""
    return _json_request("POST", "/config/drivers/validate", body=req.payload)


@app.post("/tools/bridge_health", dependencies=[Depends(require_action_tools_auth)])
def bridge_health() -> dict[str, Any]:
    return _json_request("GET", "/health")


@app.post("/tools/bridge_readiness", dependencies=[Depends(require_action_tools_auth)])
def bridge_readiness() -> dict[str, Any]:
    """Handoff payload for chat: UI links, site summary, markdown snippet, suggested yes/no follow-up."""
    return _json_request("GET", "/assistant/readiness")


@app.post("/tools/bridge_apply_site_profiles", dependencies=[Depends(require_action_tools_auth)])
def bridge_apply_site_profiles(req: ApplySiteProfilesBridgeRequest) -> dict[str, Any]:
    """Run a declarative ``site_profiles.yaml`` pack (CSV ingest + BRICK mapping + optional rules copy)."""
    return _json_request(
        "POST",
        "/assistant/apply-site-profiles",
        body={"profiles_yaml": req.profiles_yaml, "reset": bool(req.reset)},
    )


@app.post("/tools/drivers_health", dependencies=[Depends(require_action_tools_auth)])
def drivers_health() -> dict[str, Any]:
    return _json_request("GET", "/config/drivers/health")


@app.post("/tools/weather_config_get", dependencies=[Depends(require_action_tools_auth)])
def weather_config_get() -> dict[str, Any]:
    return _json_request("GET", "/config/weather")


@app.post("/tools/weather_config_set", dependencies=[Depends(require_action_tools_auth)])
def weather_config_set(req: DriverConfigRequest) -> dict[str, Any]:
    return _json_request("POST", "/config/weather", body=req.payload)


@app.post("/tools/weather_ingest_run", dependencies=[Depends(require_action_tools_auth)])
def weather_ingest_run(req: IngestRequest) -> dict[str, Any]:
    return _json_request("POST", "/ingest/weather", body={"site_id": req.site_id, "days_back": 7})


@app.post("/tools/onboard_config_get", dependencies=[Depends(require_action_tools_auth)])
def onboard_config_get() -> dict[str, Any]:
    return _json_request("GET", "/config/onboard")


@app.post("/tools/onboard_config_set", dependencies=[Depends(require_action_tools_auth)])
def onboard_config_set(req: DriverConfigRequest) -> dict[str, Any]:
    return _json_request("POST", "/config/onboard", body=req.payload)


@app.post("/tools/onboard_ingest_run", dependencies=[Depends(require_action_tools_auth)])
def onboard_ingest_run(req: IngestRequest) -> dict[str, Any]:
    return _json_request("POST", "/ingest/onboard", body={"site_id": req.site_id})


@app.post("/tools/bacnet_config_get", dependencies=[Depends(require_action_tools_auth)])
def bacnet_config_get() -> dict[str, Any]:
    return _json_request("GET", "/config/bacnet")


@app.post("/tools/bacnet_config_set", dependencies=[Depends(require_action_tools_auth)])
def bacnet_config_set(req: DriverConfigRequest) -> dict[str, Any]:
    return _json_request("POST", "/config/bacnet", body=req.payload)


@app.post("/tools/bacnet_ingest_run", dependencies=[Depends(require_action_tools_auth)])
def bacnet_ingest_run(req: IngestRequest) -> dict[str, Any]:
    return _json_request("POST", "/ingest/bacnet", body={"site_id": req.site_id})


@app.post("/tools/data_model_export", dependencies=[Depends(require_action_tools_auth)])
def export_data_model() -> dict[str, Any]:
    return _json_request("GET", "/model/export")


@app.post("/tools/data_model_import", dependencies=[Depends(require_action_tools_auth)])
def import_data_model(req: ImportRequest) -> dict[str, Any]:
    return _json_request("POST", "/model/import", body={"payload": req.payload, "replace": bool(req.replace)})


@app.post("/tools/sparql_validate", dependencies=[Depends(require_action_tools_auth)])
def sparql_validate(req: SparqlRequest) -> dict[str, Any]:
    return _json_request("POST", "/data-model/sparql", body={"query": req.query})


@app.post("/tools/openclaw_cron_validate")
def openclaw_cron_validate(req: OpenClawCronValidateRequest) -> dict[str, Any]:
    return _validate_cron_expression(req.expression)


@app.post("/tools/openclaw_ops_templates")
def openclaw_ops_templates(req: OpenClawOpsTemplateRequest) -> dict[str, Any]:
    payload = _build_openclaw_ops_templates(req)
    payload["shell"] = req.shell
    payload["session"] = req.session
    return payload


@app.post("/tools/openclaw_observability_baseline")
def openclaw_observability_baseline(req: OpenClawObservabilityRequest) -> dict[str, Any]:
    return _build_observability_baseline(req)


@app.post("/tools/openclaw_memory_governance")
def openclaw_memory_governance(req: OpenClawMemoryGovernanceRequest) -> dict[str, Any]:
    return _build_memory_governance_profile(req)


@app.post("/tools/openclaw_subagent_lanes")
def openclaw_subagent_lanes(req: OpenClawSubagentLanesRequest) -> dict[str, Any]:
    return _build_subagent_lanes(req)


def run_mcp_rag(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    bind_host = host if host is not None else mcp_listen_host()
    bind_port = port if port is not None else mcp_listen_port()
    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")


