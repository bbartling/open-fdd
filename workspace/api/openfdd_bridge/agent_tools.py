"""Tool registry the local Ollama agent can call to maintain the application.

Tools let the agent build the BRICK model, author/run FDD rules, and (only when
explicitly opted in) edit application files and rebuild the dashboard. Every
Read-only tools are available to the ``operator`` role; writes require integrator/agent. Calls are audited.
log. App-editing tools additionally require ``OFDD_AGENT_ALLOW_APP_EDIT=1`` so
self-modification is off by default on an OT box.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from .building_alerts import replace_alerts
from .device_poll_health import get_device_poll_snapshot
from .operational_analytics import (
    analytics_lookback_days,
    analytics_methodology,
    methodology_prompt_blurb,
    trim_frame_to_lookback,
)
from .zone_temp_analytics import get_zone_temp_snapshot
from .data_loader import load_demo_dataframe, load_frame_for_run
from .site_defaults import ensure_default_site
from .timeseries_api import resolve_plot_columns
from .ttl_service import TtlService
from .brick_model_context import (
    api_query_guide,
    catalog_entries_for_codes,
    slim_brick_graph,
)
from .fault_catalog import all_codes, catalog_graph, entry_for_code, is_valid_code
from .fault_catalog_scope import build_applicable_payload, validate_scope_with_ollama
from .building_agent import run_checkin
from .fdd_results import load_results
from .fdd_runner import run_batch
from .ops_logs import collect_ops_logs
from .poll_throughput import compute_poll_throughput
from .site_memory import get_site_memory, put_site_memory
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
    codes_raw: list[str] = []
    if isinstance(args.get("fault_codes"), list):
        codes_raw.extend(str(c).strip() for c in args["fault_codes"] if str(c).strip())
    if not codes_raw and args.get("fault_code"):
        codes_raw.append(str(args.get("fault_code") or "").strip())
    for raw in codes_raw:
        code = raw.upper()
        if not is_valid_code(code):
            raise ToolError(
                f"unknown fault code '{raw}'. Pick a fixed code from the fault catalog "
                "(model_context().fault_codes); do not invent codes."
            )
    if codes_raw:
        args = {**args, "fault_codes": [c.upper() for c in codes_raw]}
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
        "lookback_days": snap.get("lookback_days"),
        "methodology": snap.get("methodology"),
        "worst_zones": snap.get("worst_zones") or [],
        "struggling_zones": snap.get("struggling_zones") or [],
        "systems": snap.get("systems") or [],
        "zones": snap.get("zones") or [],
        "generated_at": snap.get("generated_at"),
        "data_source": snap.get("data_source"),
    }


def _tool_building_device_health(args: dict[str, Any]) -> dict[str, Any]:
    """Refresh per-equipment poll/FDD health from feather (online, flaky, offline)."""
    force = str(args.get("force") or "true").strip().lower() in {"1", "true", "yes"}
    site_id = str(args.get("site_id") or "").strip() or None
    snap = get_device_poll_snapshot(site_id=site_id, force=force)
    return {
        "summary_sentence": snap.get("summary_sentence"),
        "lookback_days": snap.get("lookback_days"),
        "healthy_count": snap.get("healthy_count"),
        "offline_equipment": snap.get("offline_equipment") or [],
        "flaky_equipment": snap.get("flaky_equipment") or [],
        "degraded_equipment": snap.get("degraded_equipment") or [],
        "equipment": snap.get("equipment") or [],
        "generated_at": snap.get("generated_at"),
        "data_source": snap.get("data_source"),
    }


def _tool_building_operational_brief(args: dict[str, Any]) -> dict[str, Any]:
    from .building_insight import get_operational_brief

    force = str(args.get("force") or "false").strip().lower() in {"1", "true", "yes"}
    return get_operational_brief(force=force)


def _tool_model_graph(args: dict[str, Any]) -> dict[str, Any]:
    """BRICK site graph: equipment, brick:feeds chains, sensors (SPARQL / TTL)."""
    site_id = str(args.get("site_id") or "").strip() or None
    return slim_brick_graph(site_id, max_equipment=32, max_feeds=24, max_points_per_equipment=12)


def _tool_model_scope(args: dict[str, Any]) -> dict[str, Any]:
    """BRICK scope for one equipment — sensors with historian column names."""
    from .model_sparql import scope_bundle

    site_id = str(args.get("site_id") or "").strip() or ensure_default_site(ModelService(), TtlService())
    equipment_id = str(args.get("equipment_id") or "").strip() or None
    brick_type = str(args.get("brick_type") or "").strip() or None
    return scope_bundle(site_id, equipment_id=equipment_id, brick_type=brick_type)


def _tool_timeseries_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    """Summarize feather historian columns (mean/min/max/last) — not full traces."""
    import pandas as pd

    site_id = str(args.get("site_id") or "").strip() or ensure_default_site(ModelService(), TtlService())
    raw_cols = args.get("columns")
    if isinstance(raw_cols, list):
        columns = [str(c).strip() for c in raw_cols if str(c).strip()]
    else:
        columns = [c.strip() for c in str(raw_cols or "").split(",") if c.strip()]
    if args.get("hours") is None:
        hours = analytics_lookback_days() * 24
    else:
        try:
            hours = int(args.get("hours"))
        except (TypeError, ValueError) as exc:
            raise ToolError(f"invalid hours value: {args.get('hours')!r}") from exc
    hours = max(1, min(hours, 24 * 90))
    df, origin = load_frame_for_run(site_id)
    df = trim_frame_to_lookback(df, hours=float(hours))
    if not columns:
        model = ModelService().load()
        columns = resolve_plot_columns([], model, site_id)[:8]
    if df.empty:
        return {"site_id": site_id, "hours": hours, "data_source": origin, "series": [], "note": "no data"}
    series: list[dict[str, Any]] = []
    for col in columns:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        series.append(
            {
                "column": col,
                "samples": int(len(s)),
                "last": round(float(s.iloc[-1]), 3),
                "mean": round(float(s.mean()), 3),
                "min": round(float(s.min()), 3),
                "max": round(float(s.max()), 3),
            }
        )
    return {"site_id": site_id, "hours": hours, "data_source": origin, "series": series}


def _tool_faults_lookup(args: dict[str, Any]) -> dict[str, Any]:
    """Official fault catalog entry for one code (VAV-C, AHU-B, …)."""
    code = str(args.get("code") or "").strip()
    if not code:
        raise ToolError("code is required")
    entries = catalog_entries_for_codes([code], limit=1)
    if not entries:
        raise ToolError(f"unknown fault code: {code}")
    return entries[0]


def _tool_faults_applicable_scope(args: dict[str, Any]) -> dict[str, Any]:
    """Fault catalog families applicable to BRICK equipment on a site (SPARQL-scoped)."""
    site_id = str(args.get("site_id") or "").strip() or None
    payload = build_applicable_payload(site_id)
    return {
        "site_id": payload["site_id"],
        "query_engine": payload["query_engine"],
        "equipment_count": payload["equipment_count"],
        "applicable_families": payload["applicable_families"],
        "hidden_families": payload["hidden_families"],
        "assigned_rules": payload["assigned_rules"],
        "family_count": payload.get("family_count"),
    }


def _tool_faults_validate_scope(args: dict[str, Any]) -> dict[str, Any]:
    """Ollama sanity-check of applicable fault families for the site."""
    site_id = str(args.get("site_id") or "").strip() or None
    return validate_scope_with_ollama(site_id)


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


def _tool_analytics_poll_throughput(args: dict[str, Any]) -> dict[str, Any]:
    window = args.get("window_minutes")
    try:
        window_i = int(window) if window is not None else 60
    except (TypeError, ValueError) as exc:
        raise ToolError(f"invalid window_minutes: {window!r}") from exc
    return compute_poll_throughput(window_minutes=window_i)


def _tool_fdd_results(args: dict[str, Any]) -> dict[str, Any]:
    doc = load_results()
    site_id = str(args.get("site_id") or "").strip() or None
    limit = args.get("limit")
    try:
        lim = int(limit) if limit is not None else 50
    except (TypeError, ValueError) as exc:
        raise ToolError(f"invalid limit: {limit!r}") from exc
    runs = [r for r in doc.get("runs", []) if isinstance(r, dict)]
    if site_id:
        runs = [r for r in runs if str(r.get("site_id") or "") in {"", site_id}]
    runs = runs[-max(1, min(lim, 200)) :]
    return {"generated_at": doc.get("generated_at"), "runs": runs, "count": len(runs)}


def _tool_ops_logs(args: dict[str, Any]) -> dict[str, Any]:
    tail = args.get("tail")
    try:
        tail_i = int(tail) if tail is not None else 80
    except (TypeError, ValueError) as exc:
        raise ToolError(f"invalid tail: {tail!r}") from exc
    return collect_ops_logs(
        tail=tail_i,
        service=str(args.get("service") or "bridge"),
        include_docker=str(args.get("include_docker") or "true").strip().lower() not in {"0", "false", "no"},
    )


def _tool_site_memory_get(args: dict[str, Any]) -> dict[str, Any]:
    site_id = str(args.get("site_id") or "").strip() or ensure_default_site(ModelService(), TtlService())
    kind = str(args.get("kind") or "memory").strip().lower()
    return get_site_memory(site_id=site_id, kind=kind)


def _tool_site_memory_put(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "site_id", "content")
    kind = str(args.get("kind") or "memory").strip().lower()
    mode = str(args.get("mode") or "replace").strip().lower()
    return put_site_memory(
        site_id=str(args["site_id"]),
        content=str(args["content"]),
        kind=kind,
        mode=mode,
    )


def _tool_building_checkin(args: dict[str, Any]) -> dict[str, Any]:
    site_id = str(args.get("site_id") or "").strip() or None
    run_batch_flag = str(args.get("run_fdd_batch") or "true").strip().lower() in {"1", "true", "yes"}
    write_memory = str(args.get("write_memory") or "true").strip().lower() not in {"0", "false", "no"}
    window = args.get("window_minutes")
    try:
        window_i = int(window) if window is not None else 60
    except (TypeError, ValueError) as exc:
        raise ToolError(f"invalid window_minutes: {window!r}") from exc
    return run_checkin(
        site_id=site_id,
        run_fdd_batch=run_batch_flag,
        write_memory=write_memory,
        window_minutes=window_i,
    )


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


_READ_ONLY_TOOLS = frozenset(
    {
        "model.graph",
        "model.scope",
        "timeseries.snapshot",
        "faults.lookup",
        "faults.applicable_scope",
        "faults.validate_scope",
        "building.zone_temps",
        "building.device_health",
        "building.operational_brief",
        "analytics.poll_throughput",
        "fdd.results",
        "ops.logs",
        "site.memory_get",
    }
)

_WRITE_TOOLS = frozenset(
    {
        "model.add_site",
        "model.add_equipment",
        "model.add_point",
        "rules.save",
        "rules.bind",
        "rules.run_batch",
        "building.set_alerts",
        "building.checkin",
        "site.memory_put",
        "app.edit_file",
        "app.rebuild_dashboard",
    }
)


_TOOLS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "model.add_site": _tool_model_add_site,
    "model.add_equipment": _tool_model_add_equipment,
    "model.add_point": _tool_model_add_point,
    "model.graph": _tool_model_graph,
    "model.scope": _tool_model_scope,
    "timeseries.snapshot": _tool_timeseries_snapshot,
    "faults.lookup": _tool_faults_lookup,
    "faults.applicable_scope": _tool_faults_applicable_scope,
    "faults.validate_scope": _tool_faults_validate_scope,
    "rules.save": _tool_rules_save,
    "rules.bind": _tool_rules_bind,
    "rules.run_batch": _tool_rules_run_batch,
    "building.set_alerts": _tool_building_set_alerts,
    "building.zone_temps": _tool_building_zone_temps,
    "building.device_health": _tool_building_device_health,
    "building.operational_brief": _tool_building_operational_brief,
    "building.checkin": _tool_building_checkin,
    "analytics.poll_throughput": _tool_analytics_poll_throughput,
    "fdd.results": _tool_fdd_results,
    "ops.logs": _tool_ops_logs,
    "site.memory_get": _tool_site_memory_get,
    "site.memory_put": _tool_site_memory_put,
    "app.edit_file": _tool_app_edit_file,
    "app.rebuild_dashboard": _tool_app_rebuild_dashboard,
}


def tool_requires_write_role(name: str) -> bool:
    return name in _WRITE_TOOLS or (name.startswith("app.") and name not in _READ_ONLY_TOOLS)


def tool_specs_for_role(role: str | None) -> list[dict[str, Any]]:
    specs = tool_specs()
    if role in ("integrator", "agent"):
        return specs
    allowed = _READ_ONLY_TOOLS
    return [s for s in specs if s.get("name") in allowed]


def operator_model_context() -> dict[str, Any]:
    """Slim building summary for operator role (no write tool specs or repo detail)."""
    model = ModelService().load()
    health = model_health_summary(model)
    try:
        zone = get_zone_temp_snapshot(force=False)
        zone_summary = {
            "summary_sentence": zone.get("summary_sentence"),
            "topology_mode": zone.get("topology_mode"),
            "zone_sensor_count": zone.get("zone_sensor_count"),
        }
    except Exception:
        zone_summary = {"summary_sentence": None, "topology_mode": None, "zone_sensor_count": None}
    try:
        devices = get_device_poll_snapshot(force=False)
        device_summary = {
            "summary_sentence": devices.get("summary_sentence"),
            "healthy_count": devices.get("healthy_count"),
        }
    except Exception:
        device_summary = {"summary_sentence": None, "healthy_count": None}
    return {
        "model_summary": {
            "sites": health["counts"]["sites"],
            "equipment": health["counts"]["equipment"],
            "points": health["counts"]["points"],
            "score": health["score"],
            "status": health["status"],
        },
        "zone_temp_levers": zone_summary,
        "device_poll_health": device_summary,
        "tools": tool_specs_for_role("operator"),
        "read_only_tools": sorted(_READ_ONLY_TOOLS),
        "app_edit_enabled": False,
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
            "args": [
                "name",
                "code",
                "fault_code?",
                "fault_codes?",
                "mode?",
                "config?",
                "applies_to?",
                "severity?",
                "bindings?",
            ],
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
            "writes": "in-memory cache — zone day/night + fan-on recovery (OFDD_ANALYTICS_LOOKBACK_DAYS)",
        },
        {
            "name": "building.device_health",
            "args": ["site_id?", "force?"],
            "writes": "in-memory cache — equipment online/flaky from feather poll gaps",
        },
        {
            "name": "building.operational_brief",
            "args": ["force?"],
            "writes": "read-only — zone temps + device health + fault sentences JSON",
        },
        {
            "name": "building.checkin",
            "args": ["site_id?", "run_fdd_batch?", "write_memory?", "window_minutes?"],
            "writes": "building_agent_checkin.json + site MEMORY.md append",
        },
        {
            "name": "analytics.poll_throughput",
            "args": ["window_minutes?"],
            "writes": "read-only — expected vs observed BACnet samples/min",
        },
        {"name": "fdd.results", "args": ["site_id?", "limit?"], "writes": "read-only — fdd_results.json runs"},
        {
            "name": "ops.logs",
            "args": ["tail?", "service?", "include_docker?"],
            "writes": "read-only — bridge error/audit + optional docker compose tail",
        },
        {
            "name": "site.memory_get",
            "args": ["site_id?", "kind?"],
            "writes": "read-only — workspace/memory/sites/<id>.md or SKILLS.md",
        },
        {
            "name": "site.memory_put",
            "args": ["site_id", "content", "kind?", "mode?"],
            "writes": "workspace/memory/sites/",
        },
        {
            "name": "model.graph",
            "args": ["site_id?"],
            "writes": "read-only — BRICK equipment, feeds, sensors (SPARQL)",
        },
        {
            "name": "model.scope",
            "args": ["site_id?", "equipment_id?", "brick_type?"],
            "writes": "read-only — sensors + plot columns for equipment",
        },
        {
            "name": "timeseries.snapshot",
            "args": ["site_id?", "columns", "hours?"],
            "writes": "read-only — historian mean/min/max/last",
        },
        {"name": "faults.lookup", "args": ["code"], "writes": "read-only — fault catalog definition"},
        {
            "name": "faults.applicable_scope",
            "args": ["site_id?"],
            "writes": "read-only — SPARQL-scoped fault families for site",
        },
        {
            "name": "faults.validate_scope",
            "args": ["site_id?"],
            "writes": "read-only — Ollama validates fault family scope",
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


def run_tool(name: str, args: dict[str, Any] | None, *, role: str | None = None) -> dict[str, Any]:
    fn = _TOOLS.get(name)
    if fn is None:
        raise ToolError(f"unknown tool: {name}")
    if tool_requires_write_role(name) and role not in ("integrator", "agent"):
        raise ToolError(f"tool {name} requires integrator or agent role (got {role!r})")
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
            "lookback_days": zone.get("lookback_days"),
            "worst_zones": (zone.get("worst_zones") or [])[:6],
            "struggling_zones": (zone.get("struggling_zones") or [])[:6],
            "refresh_tool": "building.zone_temps",
        }
    except Exception as exc:  # noqa: BLE001 - context must not fail whole endpoint
        zone_levers = {
            "summary_sentence": None,
            "topology_mode": None,
            "zone_sensor_count": None,
            "worst_zones": [],
            "struggling_zones": [],
            "refresh_tool": "building.zone_temps",
            "error": str(exc)[:200],
        }
    try:
        devices = get_device_poll_snapshot(force=False)
        device_levers = {
            "summary_sentence": devices.get("summary_sentence"),
            "healthy_count": devices.get("healthy_count"),
            "offline": (devices.get("offline_equipment") or [])[:6],
            "flaky": (devices.get("flaky_equipment") or [])[:6],
            "refresh_tool": "building.device_health",
        }
    except Exception as exc:  # noqa: BLE001
        device_levers = {
            "summary_sentence": None,
            "healthy_count": None,
            "offline": [],
            "flaky": [],
            "refresh_tool": "building.device_health",
            "error": str(exc)[:200],
        }
    return {
        "analytics_methodology": analytics_methodology(),
        "methodology_blurb": methodology_prompt_blurb(),
        "data_pipeline": [
            "BACnet poll → feather_store/",
            "load_frame_for_run → zone_temp_analytics + zone_energy_research + device_poll_health",
            "building_insight / operational-brief for dashboard (LLM uses zone_research tasks)",
        ],
        "zone_temp_levers": zone_levers,
        "device_poll_health": device_levers,
        "operational_brief_tool": "building.operational_brief",
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
            {
                "code": c,
                "family": e["family"],
                "category": e["category"],
                "title": e["title"],
                "suffix": e.get("suffix"),
                "cookbook_patterns": e.get("cookbook_patterns") or [],
            }
            for c, e in all_codes().items()
        ],
        "fault_code_graph": catalog_graph(),
        "brick_model": slim_brick_graph(max_equipment=12, max_feeds=10),
        "api_query_guide": api_query_guide(),
        "tools": tool_specs(),
        "read_only_tools": sorted(_READ_ONLY_TOOLS),
        "app_edit_enabled": app_edit_enabled(),
    }
