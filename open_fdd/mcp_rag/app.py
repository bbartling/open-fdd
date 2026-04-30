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
from pydantic import BaseModel, ConfigDict, Field

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
    hints = [
        "5-field cron: minute hour day month weekday."
        if len(fields) == 5
        else "6-field cron: seconds minute hour day month weekday."
    ]
    return {"valid": True, "hints": hints}


def _build_openclaw_ops_templates(req: OpenClawOpsTemplateRequest) -> dict[str, Any]:
    shell = str(req.shell or "posix").strip().lower()
    cont = " `" if shell == "powershell" else " \\"
    cron_cmd = [
        "openclaw cron add",
        f'--name "{req.name}"',
        f'--cron "{req.cron}"',
        f'--tz "{req.tz}"',
        f"--session {req.session}",
    ]
    if str(req.session).strip().lower() == "main":
        cron_cmd += [f'--system-event "{req.message}"', "--wake now"]
    else:
        cron_cmd += [f'--message "{req.message}"', "--announce"]
    joined = f"{cont}\n  ".join(cron_cmd)
    memory = (
        "Set-Content \"$HOME/.openclaw/workspace/MEMORY.md\" -Value \"\"\n"
        "Remove-Item \"$HOME/.openclaw/workspace/memory/*.md\" -ErrorAction SilentlyContinue"
        if shell == "powershell"
        else "truncate -s 0 ~/.openclaw/workspace/MEMORY.md\nrm -f ~/.openclaw/workspace/memory/*.md"
    )
    return {
        "cron_add": joined,
        "cron_cleanup": "openclaw cron list\n# remove one:\nopenclaw cron remove <job-id>",
        "skills_refresh": (
            "openclaw skills list --eligible\nopenclaw skills update --all\n"
            "# optional clean reinstall path\n# rm -rf ~/.openclaw/workspace/skills/<skill-name>\n"
            "# openclaw skills install <skill-slug>"
        ),
        "memory_cleanup": memory,
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
    return payload


def run_mcp_rag(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    bind_host = host if host is not None else mcp_listen_host()
    bind_port = port if port is not None else mcp_listen_port()
    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")


