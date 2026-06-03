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
from .zone_temp_analytics import get_zone_temp_snapshot
from .data_loader import load_demo_dataframe
from .fault_catalog import all_codes, is_valid_code
from .fdd_runner import run_batch
from .model_health import model_health_summary
from .model_service import ModelService
from .model_store import ModelStore
from .paths import repo_root, workspace_dir
from .rule_bindings import apply_bind_op
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


def _tool_building_zone_temps(args: dict[str, Any]) -> dict[str, Any]:
    """Refresh cached zone temperature analytics (BRICK sensors + feather trends)."""
    force = str(args.get("force") or "true").strip().lower() in {"1", "true", "yes"}
    site_id = str(args.get("site_id") or "").strip() or None
    snap = get_zone_temp_snapshot(site_id=site_id, force=force)
    return {
        "summary_sentence": snap.get("summary_sentence"),
        "topology_mode": snap.get("topology_mode"),
        "zone_sensor_count": snap.get("zone_sensor_count"),
        "struggling_zones": snap.get("struggling_zones") or [],
        "systems": snap.get("systems") or [],
        "zones": snap.get("zones") or [],
        "generated_at": snap.get("generated_at"),
        "data_source": snap.get("data_source"),
    }


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


def _tool_rules_bind(args: dict[str, Any]) -> dict[str, Any]:
    """Add or remove a point/equipment/brick_type binding on a saved rule (merge semantics)."""
    _require(args, "rule_id", "op", "kind", "target_id")
    op = str(args["op"]).strip().lower()
    kind = str(args["kind"]).strip().lower()
    if op not in {"add", "remove"}:
        raise ToolError("op must be 'add' or 'remove'")
    if kind not in {"point", "equipment", "brick_type"}:
        raise ToolError("kind must be point, equipment, or brick_type")
    store = RuleStore()
    rule = store.get(str(args["rule_id"]))
    if not rule:
        raise ToolError(f"rule not found: {args['rule_id']}")
    point_ids = [str(x) for x in args.get("point_ids") or [] if str(x).strip()]
    bindings = apply_bind_op(
        rule,
        op=op,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        target_id=str(args["target_id"]),
        point_ids=point_ids,
    )
    entry = store.upsert({**rule, "bindings": bindings}, saved_by="agent")
    return {"rule_id": entry.get("id"), "bindings": entry.get("bindings")}


def _tool_rules_run_batch(args: dict[str, Any]) -> dict[str, Any]:
    raw = args.get("limit")
    try:
        limit = int(raw if raw is not None else 1000)
    except (TypeError, ValueError) as exc:
        raise ToolError("invalid limit — must be an integer") from exc
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
    content = str(args["contents"])
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "existed": existed, "bytes": len(content.encode("utf-8"))}


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
    "rules.bind": _tool_rules_bind,
    "rules.run_batch": _tool_rules_run_batch,
    "building.set_alerts": _tool_building_set_alerts,
    "building.zone_temps": _tool_building_zone_temps,
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
            "args": ["name", "code", "fault_code?", "mode?", "config?", "applies_to?", "severity?", "bindings?"],
            "writes": "rules_store.json",
        },
        {
            "name": "rules.bind",
            "args": ["rule_id", "op", "kind", "target_id", "point_ids?"],
            "writes": "rules_store.json bindings (merge add/remove)",
        },
        {"name": "rules.run_batch", "args": ["limit?"], "writes": "fdd_results.json"},
        {
            "name": "building.set_alerts",
            "args": ["alerts[{severity,title,detail,code,equipment_family}]", "status?"],
            "writes": "building_alerts.json (codes validated against catalog)",
        },
        {
            "name": "building.zone_temps",
            "args": ["site_id?", "force?"],
            "writes": "in-memory cache only — refreshes pandas zone lever snapshot",
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
    try:
        zone = get_zone_temp_snapshot(force=False)
        zone_levers = {
            "summary_sentence": zone.get("summary_sentence"),
            "topology_mode": zone.get("topology_mode"),
            "zone_sensor_count": zone.get("zone_sensor_count"),
            "struggling_zones": (zone.get("struggling_zones") or [])[:6],
            "refresh_tool": "building.zone_temps",
        }
    except Exception as exc:  # noqa: BLE001 - context must not fail whole endpoint
        zone_levers = {
            "summary_sentence": None,
            "topology_mode": None,
            "zone_sensor_count": None,
            "struggling_zones": [],
            "refresh_tool": "building.zone_temps",
            "error": str(exc)[:200],
        }
    return {
        "zone_temp_levers": zone_levers,
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
