"""Tool registry the local Ollama agent can call to maintain the application.

Tools let the agent build the BRICK model, author/run FDD rules, and (only when
explicitly opted in) edit application files and rebuild the dashboard. Every
call is gated by the ``agent`` role at the route layer and written to the audit
log. App-editing tools additionally require ``OFDD_AGENT_ALLOW_APP_EDIT=1`` so
self-modification is off by default on an OT box.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from .building_alerts import replace_alerts
from .data_loader import load_demo_dataframe
from .fault_catalog import all_codes, is_valid_code
from .fdd_runner import run_batch
from .model_health import model_health_summary
from .model_service import ModelService
from .model_store import ModelStore
from .paths import repo_root, workspace_dir
from .rule_store import RuleStore


class ToolError(Exception):
    """Raised when a tool's arguments are invalid or an action is not permitted."""


def app_edit_enabled() -> bool:
    return os.environ.get("OFDD_AGENT_ALLOW_APP_EDIT", "").strip().lower() in {"1", "true", "yes"}


def _require(args: dict[str, Any], *names: str) -> None:
    missing = [n for n in names if not str(args.get(n, "")).strip()]
    if missing:
        raise ToolError(f"missing required argument(s): {', '.join(missing)}")


def _tool_model_add_site(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "name")
    site_id = str(args.get("id") or ModelStore.id_str())
    with ModelService().transaction() as model:
        model.setdefault("sites", [])
        if any(str(s.get("id")) == site_id for s in model["sites"] if isinstance(s, dict)):
            raise ToolError(f"site id already exists: {site_id}")
        model["sites"].append({"id": site_id, "name": str(args["name"])})
    return {"site_id": site_id}


def _tool_model_add_equipment(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "site_id", "name")
    eq_id = str(args.get("id") or ModelStore.id_str())
    with ModelService().transaction() as model:
        site_ids = {str(s.get("id")) for s in model.get("sites", []) if isinstance(s, dict)}
        if str(args["site_id"]) not in site_ids:
            raise ToolError(f"unknown site_id: {args['site_id']}")
        model.setdefault("equipment", []).append(
            {
                "id": eq_id,
                "site_id": str(args["site_id"]),
                "name": str(args["name"]),
                "equipment_type": str(args.get("equipment_type") or ""),
            }
        )
    return {"equipment_id": eq_id}


def _tool_model_add_point(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "site_id", "external_id")
    pt_id = str(args.get("id") or ModelStore.id_str())
    with ModelService().transaction() as model:
        site_ids = {str(s.get("id")) for s in model.get("sites", []) if isinstance(s, dict)}
        if str(args["site_id"]) not in site_ids:
            raise ToolError(f"unknown site_id: {args['site_id']}")
        model.setdefault("points", []).append(
            {
                "id": pt_id,
                "site_id": str(args["site_id"]),
                "equipment_id": str(args.get("equipment_id") or ""),
                "external_id": str(args["external_id"]),
                "brick_type": str(args.get("brick_type") or ""),
                "fdd_input": str(args.get("fdd_input") or args.get("external_id")),
            }
        )
    return {"point_id": pt_id}


def _tool_rules_save(args: dict[str, Any]) -> dict[str, Any]:
    fault_code = str(args.get("fault_code") or "").strip()
    if fault_code and not is_valid_code(fault_code):
        raise ToolError(
            f"unknown fault code '{fault_code}'. Pick a fixed code from the fault catalog "
            "(model_context().fault_codes); do not invent codes."
        )
    try:
        entry = RuleStore().upsert(args, saved_by="agent")
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return {"rule": entry}


def _tool_building_set_alerts(args: dict[str, Any]) -> dict[str, Any]:
    """Replace the agent-managed building alerts. Every code must exist in the catalog."""
    alerts = args.get("alerts")
    if not isinstance(alerts, list):
        raise ToolError("'alerts' must be a list of {severity,title,detail,code,equipment_family}")
    for alert in alerts:
        if not isinstance(alert, dict):
            raise ToolError("each alert must be an object")
        code = str(alert.get("code") or "").strip()
        if code and not is_valid_code(code):
            raise ToolError(
                f"unknown fault code '{code}'. Use a fixed code from the catalog; do not invent codes."
            )
    doc = replace_alerts(alerts, updated_by="agent", status=args.get("status"))
    return {"status": doc["status"], "alert_count": len(doc["alerts"])}


def _tool_rules_run_batch(args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit") or 1000)
    return run_batch(limit=max(1, min(limit, 5000)))


def _safe_workspace_path(rel: str) -> Path:
    raw = Path(rel)
    ws = workspace_dir().resolve()
    target = (raw if raw.is_absolute() else ws / raw).resolve()
    try:
        target.relative_to(ws)
    except ValueError as exc:
        raise ToolError(f"path must be inside workspace/: {rel}") from exc
    return target


def _tool_app_edit_file(args: dict[str, Any]) -> dict[str, Any]:
    if not app_edit_enabled():
        raise ToolError("app editing disabled — set OFDD_AGENT_ALLOW_APP_EDIT=1 to enable")
    _require(args, "path")
    if "contents" not in args:
        raise ToolError("missing required argument: contents")
    target = _safe_workspace_path(str(args["path"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.is_file()
    target.write_text(str(args["contents"]), encoding="utf-8")
    return {"path": str(target), "existed": existed, "bytes": len(str(args["contents"]))}


def _tool_app_rebuild_dashboard(_args: dict[str, Any]) -> dict[str, Any]:
    if not app_edit_enabled():
        raise ToolError("app rebuild disabled — set OFDD_AGENT_ALLOW_APP_EDIT=1 to enable")
    script = repo_root() / "scripts" / "build_operator_dashboard.sh"
    if not script.is_file():
        raise ToolError(f"build script not found: {script}")
    try:
        proc = subprocess.run(  # noqa: S603 - fixed in-repo script, opt-in only
            ["bash", str(script)],
            cwd=str(repo_root()),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError("dashboard rebuild timed out after 600s") from exc
    return {
        "returncode": proc.returncode,
        "ok": proc.returncode == 0,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


_TOOLS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "model.add_site": _tool_model_add_site,
    "model.add_equipment": _tool_model_add_equipment,
    "model.add_point": _tool_model_add_point,
    "rules.save": _tool_rules_save,
    "rules.run_batch": _tool_rules_run_batch,
    "building.set_alerts": _tool_building_set_alerts,
    "app.edit_file": _tool_app_edit_file,
    "app.rebuild_dashboard": _tool_app_rebuild_dashboard,
}


def tool_specs() -> list[dict[str, Any]]:
    """Human/LLM-readable description of the available tools."""
    return [
        {"name": "model.add_site", "args": ["name", "id?"], "writes": "model.json"},
        {"name": "model.add_equipment", "args": ["site_id", "name", "equipment_type?", "id?"], "writes": "model.json"},
        {
            "name": "model.add_point",
            "args": ["site_id", "external_id", "equipment_id?", "brick_type?", "fdd_input?", "id?"],
            "writes": "model.json",
        },
        {
            "name": "rules.save",
            "args": ["name", "code", "fault_code?", "mode?", "config?", "applies_to?", "severity?"],
            "writes": "rules_store.json",
        },
        {"name": "rules.run_batch", "args": ["limit?"], "writes": "fdd_results.json"},
        {
            "name": "building.set_alerts",
            "args": ["alerts[{severity,title,detail,code,equipment_family}]", "status?"],
            "writes": "building_alerts.json (codes validated against catalog)",
        },
        {
            "name": "app.edit_file",
            "args": ["path", "contents"],
            "writes": "workspace/* (requires OFDD_AGENT_ALLOW_APP_EDIT=1)",
        },
        {
            "name": "app.rebuild_dashboard",
            "args": [],
            "writes": "static SPA (requires OFDD_AGENT_ALLOW_APP_EDIT=1)",
        },
    ]


def run_tool(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    fn = _TOOLS.get(name)
    if fn is None:
        raise ToolError(f"unknown tool: {name}")
    return fn(args or {})


def model_context() -> dict[str, Any]:
    """Compact, LLM-friendly snapshot of the model, data, and saved rules."""
    model = ModelService().load()
    health = model_health_summary(model)
    rules = RuleStore().list_rules()
    try:
        sample_columns = list(load_demo_dataframe().columns)
    except Exception:  # noqa: BLE001 - context is best-effort
        sample_columns = []
    return {
        "model_summary": {
            "sites": health["counts"]["sites"],
            "equipment": health["counts"]["equipment"],
            "points": health["counts"]["points"],
            "score": health["score"],
            "status": health["status"],
        },
        "sample_columns": sample_columns,
        "saved_rules": [
            {"id": r.get("id"), "name": r.get("name"), "mode": r.get("mode"), "enabled": r.get("enabled")}
            for r in rules
        ],
        "fault_codes": [
            {"code": c, "family": e["family"], "category": e["category"], "title": e["title"]}
            for c, e in all_codes().items()
        ],
        "tools": tool_specs(),
        "app_edit_enabled": app_edit_enabled(),
    }
