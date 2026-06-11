from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .bridge import BridgeClient
from .config import McpConfig
from .errors import HumanApprovalRequired, McpError
from .rag import DocSearch
from .sites import SiteRegistry

_CONFIG = McpConfig.from_env()
_REGISTRY = SiteRegistry(
    _CONFIG.portfolio_sites_path,
    edge_base_url=_CONFIG.bridge_base_url,
    default_site_id=_CONFIG.default_site_id,
)
_BRIDGE = BridgeClient(_CONFIG, _REGISTRY)
_DOCS = DocSearch(_CONFIG.rag_index_path)

mcp = FastMCP(
    "open-fdd",
    instructions=(
        "Open-FDD MCP server — query buildings, BRICK models, FDD diagnostics, and rule cookbooks. "
        "Writes, tuning, batch runs, and rule saves require human_approved=true. "
        "Never invent fault codes; use list_fault_catalog."
    ),
)


def _require_human(human_approved: bool, action: str) -> None:
    if not human_approved:
        raise HumanApprovalRequired(action)


def _err_text(exc: Exception) -> str:
    return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def health_check(site_id: str | None = None) -> str:
    """Bridge /health for one site (edge default) or local edge."""
    try:
        if _CONFIG.mode == "portfolio" and site_id is None:
            out = []
            for site in _REGISTRY.list_sites():
                try:
                    out.append({"site_id": site.site_id, **_BRIDGE.get(site.site_id, "/health", auth_required=False)})
                except McpError as exc:
                    out.append({"site_id": site.site_id, "ok": False, "error": str(exc)})
            return json.dumps({"ok": True, "mode": "portfolio", "sites": out})
        payload = _BRIDGE.get(site_id, "/health", auth_required=False)
        return json.dumps({"ok": True, "site_id": site_id or _REGISTRY.get(site_id).site_id, **payload})
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def portfolio_rollup(site_id: str | None = None) -> str:
    """Portfolio or single-site rollup: traffic, poll health, faults, overrides."""
    try:
        if _CONFIG.mode == "portfolio" and site_id is None:
            rows = []
            for site in _REGISTRY.list_sites():
                try:
                    rows.append(
                        {
                            "site_id": site.site_id,
                            **_BRIDGE.get(site.site_id, "/api/building/portfolio-rollup"),
                        }
                    )
                except McpError as exc:
                    rows.append({"site_id": site.site_id, "ok": False, "error": str(exc)})
            return json.dumps({"ok": True, "rollups": rows})
        payload = _BRIDGE.get(site_id, "/api/building/portfolio-rollup")
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def building_agent_checkin(
    site_id: str,
    run_fdd_batch: bool = False,
    window_minutes: int = 180,
    write_memory: bool = False,
) -> str:
    """Run building-agent check-in (safe defaults: no batch, no memory write)."""
    try:
        wm = _BRIDGE.cap_window(window_minutes)
        payload = _BRIDGE.post(
            site_id,
            "/api/building-agent/checkin",
            {
                "site_id": site_id,
                "run_fdd_batch": run_fdd_batch,
                "write_memory": write_memory,
                "window_minutes": wm,
            },
        )
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def get_tuning_brief(site_id: str, window_minutes: int = 180) -> str:
    """Proposed rule/bounds changes — read-only."""
    try:
        wm = _BRIDGE.cap_window(window_minutes)
        payload = _BRIDGE.get(
            site_id,
            "/api/building-agent/tuning-brief",
            params={"site_id": site_id, "window_minutes": wm},
        )
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def preview_fdd_tuning(site_id: str, rule_ids: list[str] | None = None) -> str:
    """Dry-run apply-tuning (apply=false)."""
    try:
        payload = _BRIDGE.post(
            site_id,
            "/api/building-agent/apply-tuning",
            {"site_id": site_id, "apply": False, "rule_ids": rule_ids, "run_fdd_batch": False},
        )
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def apply_fdd_tuning(
    site_id: str,
    rule_ids: list[str] | None = None,
    run_fdd_batch: bool = True,
    human_approved: bool = False,
) -> str:
    """Apply tuning patches — requires human_approved=true."""
    try:
        _require_human(human_approved, "apply_fdd_tuning")
        payload = _BRIDGE.post(
            site_id,
            "/api/building-agent/apply-tuning",
            {
                "site_id": site_id,
                "apply": True,
                "rule_ids": rule_ids,
                "run_fdd_batch": run_fdd_batch,
            },
        )
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def list_fault_catalog(site_id: str | None = None) -> str:
    """Fixed fault code catalog — source of truth."""
    try:
        payload = _BRIDGE.get(site_id, "/api/faults/catalog", auth_required=False)
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def get_fdd_results(
    site_id: str,
    fault_code: str | None = None,
    equipment_id: str | None = None,
    window_minutes: int = 180,
) -> str:
    """Latest FDD batch results with optional client-side filter."""
    try:
        payload = _BRIDGE.get(
            site_id,
            "/api/fdd/results",
            params={"site_id": site_id, "limit": 200},
        )
        runs = payload.get("runs") or []
        if fault_code:
            fc = fault_code.strip().upper()
            runs = [
                r
                for r in runs
                if isinstance(r, dict)
                and any(
                    str(x.get("fault_code") or x.get("code") or "").upper() == fc
                    for x in (r.get("rules") or r.get("results") or [r])
                    if isinstance(x, dict)
                )
            ]
        if equipment_id:
            eid = equipment_id.strip()
            runs = [
                r
                for r in runs
                if isinstance(r, dict) and str(r.get("equipment_id") or "") == eid
            ]
        payload["runs"] = runs[-50:]
        payload["window_minutes"] = _BRIDGE.cap_window(window_minutes)
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def run_fdd_batch(site_id: str, window_minutes: int = 180, human_approved: bool = False) -> str:
    """Run FDD rules batch — requires human_approved=true."""
    try:
        _require_human(human_approved, "run_fdd_batch")
        wm = _BRIDGE.cap_window(window_minutes)
        payload = _BRIDGE.post(
            site_id,
            "/api/rules/batch",
            {"site_id": site_id, "window_minutes": wm},
        )
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def search_model(site_id: str, query: str, brick_class: str | None = None) -> str:
    """Search BRICK model graph/scope for equipment and points."""
    try:
        graph = _BRIDGE.get(site_id, "/api/model/graph", params={"site_id": site_id})
        scope = _BRIDGE.get(
            site_id,
            "/api/model/scope",
            params={"site_id": site_id, "brick_type": brick_class},
        )
        q = query.strip().lower()
        hits: list[dict[str, Any]] = []
        for bucket, label in ((graph, "graph"), (scope, "scope")):
            text = json.dumps(bucket).lower()
            if q in text:
                hits.append({"source": label, "match": True, "preview": text[:1200]})
        return json.dumps({"ok": True, "query": query, "brick_class": brick_class, "hits": hits, "graph": graph, "scope": scope})
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def get_equipment_context(site_id: str, equipment_id: str) -> str:
    """Equipment BRICK scope, rules, and recent faults."""
    try:
        scope = _BRIDGE.get(
            site_id,
            "/api/model/scope",
            params={"site_id": site_id, "equipment_id": equipment_id},
        )
        rules = _BRIDGE.get(site_id, "/api/rules/saved")
        saved = rules.get("rules") or []
        bound = [
            r
            for r in saved
            if isinstance(r, dict)
            and equipment_id in (r.get("bindings") or {}).get("equipment_ids", [])
        ]
        fdd = _BRIDGE.get(site_id, "/api/fdd/results", params={"site_id": site_id, "limit": 50})
        return json.dumps(
            {
                "ok": True,
                "site_id": site_id,
                "equipment_id": equipment_id,
                "scope": scope,
                "bound_rules": bound,
                "recent_fdd": fdd,
            }
        )
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def recommend_rules_for_equipment(site_id: str, equipment_id: str) -> str:
    """Candidate FDD rules from applicable catalog + cookbook search — does not save."""
    try:
        applicable = _BRIDGE.get(
            site_id,
            "/api/faults/applicable",
            params={"site_id": site_id},
            auth_required=False,
        )
        scope = _BRIDGE.get(
            site_id,
            "/api/model/scope",
            params={"site_id": site_id, "equipment_id": equipment_id},
        )
        brick = ""
        for row in (scope.get("equipment") or scope.get("equipment_rows") or []):
            if isinstance(row, dict):
                brick = str(row.get("brick_type") or row.get("equipment_type") or "")
                break
        cookbook = _DOCS.search(
            f"{brick} {equipment_id} fault detection",
            top_k=8,
            tags=None,
        )
        return json.dumps(
            {
                "ok": True,
                "site_id": site_id,
                "equipment_id": equipment_id,
                "applicable_faults": applicable,
                "scope": scope,
                "cookbook_matches": cookbook,
                "note": "Review bindings before save_rule; human approval required.",
            }
        )
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def search_rule_cookbook(query: str, equipment_class: str | None = None) -> str:
    """Search expression cookbook, Arrow recipes, and fault docs."""
    try:
        q = query if not equipment_class else f"{query} {equipment_class}"
        payload = _DOCS.search(q, top_k=8)
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def draft_arrow_rule(
    site_id: str,
    equipment_id: str,
    fault_goal: str,
    point_bindings: dict[str, str] | None = None,
) -> str:
    """Draft apply_faults_arrow rule skeleton — does not save."""
    try:
        scope = _BRIDGE.get(
            site_id,
            "/api/model/scope",
            params={"site_id": site_id, "equipment_id": equipment_id},
        )
        bindings = point_bindings or {}
        code = '''"""Draft Arrow-native rule — review before save."""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc


def apply_faults_arrow(table: pa.Table, cfg: dict, context: dict | None = None) -> pa.Array:
    col = str(cfg.get("value_column") or "zone_t")
    if col not in table.column_names:
        return pa.array([False] * table.num_rows)
    vals = table[col]
    low = float(cfg.get("bounds_low", 65))
    high = float(cfg.get("bounds_high", 80))
    return pc.and_(pc.greater(vals, high), pc.less(vals, low))
'''
        cfg = {
            "bounds_low": 65,
            "bounds_high": 80,
            "value_column": next(iter(bindings.values()), "zone_t"),
        }
        return json.dumps(
            {
                "ok": True,
                "site_id": site_id,
                "equipment_id": equipment_id,
                "fault_goal": fault_goal,
                "point_bindings": bindings,
                "scope": scope,
                "draft": {"code": code, "config": cfg, "mode": "rule"},
                "tests": [{"description": "synthetic high temp flags", "cfg": cfg}],
            }
        )
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def lint_rule(code: str, config: dict[str, Any] | None = None) -> str:
    """Lint rule via Rule Lab API."""
    try:
        site = _REGISTRY.list_sites()[0] if _REGISTRY.list_sites() else None
        sid = site.site_id if site else None
        lint = _BRIDGE.post(sid, "/api/playground/lint", {"code": code, "mode": "rule"})
        out: dict[str, Any] = {"lint": lint}
        if config is not None:
            out["config"] = config
        return json.dumps(out)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def save_rule(
    site_id: str,
    rule_id: str,
    code: str,
    config: dict[str, Any],
    human_approved: bool = False,
) -> str:
    """Save rule — requires human_approved=true; fetches current source when present."""
    try:
        _require_human(human_approved, "save_rule")
        backup = None
        try:
            backup = _BRIDGE.get(site_id, f"/api/rules/saved/{rule_id}/source")
        except McpError:
            backup = None
        payload = _BRIDGE.post(
            site_id,
            "/api/rules/save",
            {
                "id": rule_id,
                "code": code,
                "config": config,
                "mode": "rule",
            },
        )
        return json.dumps({"ok": True, "backup": backup, "result": payload})
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def bacnet_override_status(site_id: str) -> str:
    """BACnet P8 operator override scan status."""
    try:
        payload = _BRIDGE.get(site_id, "/api/bacnet/overrides/status")
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def search_docs(query: str, top_k: int = 6, tags: list[str] | None = None) -> str:
    """RAG doc search (preserves legacy mcp-rag behavior)."""
    try:
        return json.dumps(_DOCS.search(query, top_k=top_k, tags=tags))
    except Exception as exc:
        return _err_text(exc)


@mcp.tool()
def get_doc_section(path_or_id: str) -> str:
    """Fetch one RAG doc section by path or chunk id."""
    try:
        return json.dumps(_DOCS.get_section(path_or_id))
    except Exception as exc:
        return _err_text(exc)


# --- Resources ---


@mcp.resource("openfdd://sites")
def resource_sites() -> str:
    return json.dumps(_REGISTRY.redacted_payload())


@mcp.resource("openfdd://memory")
def resource_memory() -> str:
    path = _CONFIG.memory_path
    if path.is_file():
        return path.read_text(encoding="utf-8")[:12000]
    example = path.parent / "MEMORY.md.example"
    if example.is_file():
        return example.read_text(encoding="utf-8")[:12000]
    return "# No workspace memory yet\n"


@mcp.resource("openfdd://skills")
def resource_skills() -> str:
    skills_dir = _CONFIG.skills_dir
    names = sorted(p.name for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()) if skills_dir.is_dir() else []
    return json.dumps({"skills_dir": str(skills_dir), "skills": names})


@mcp.resource("openfdd://fault-catalog/{site_id}")
def resource_fault_catalog(site_id: str) -> str:
    return list_fault_catalog(site_id)


@mcp.resource("openfdd://model/{site_id}")
def resource_model(site_id: str) -> str:
    try:
        payload = _BRIDGE.get(site_id, "/api/model/graph", params={"site_id": site_id})
        return json.dumps(payload)
    except Exception as exc:
        return _err_text(exc)


@mcp.resource("openfdd://rules/{site_id}")
def resource_rules(site_id: str) -> str:
    try:
        payload = _BRIDGE.get(site_id, "/api/rules/saved")
        rules = payload.get("rules") or []
        slim = [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "mode": r.get("mode"),
                "fault_codes": r.get("fault_codes"),
            }
            for r in rules
            if isinstance(r, dict)
        ]
        return json.dumps({"site_id": site_id, "rules": slim})
    except Exception as exc:
        return _err_text(exc)


@mcp.resource("openfdd://docs/rag-index")
def resource_rag_index() -> str:
    return json.dumps(_DOCS.metadata())


# --- Prompts ---


@mcp.prompt()
def commission_building_fdd(site_id: str, equipment_class: str = "VAV") -> str:
    return (
        f"Commission FDD for site {site_id}, equipment class {equipment_class}. "
        "Steps: search_model → get_equipment_context → recommend_rules_for_equipment → "
        "search_rule_cookbook → draft_arrow_rule → lint_rule → ask human before save_rule/apply."
    )


@mcp.prompt()
def diagnose_fault_trend(site_id: str, fault_code: str, equipment_id: str = "") -> str:
    return (
        f"Diagnose fault {fault_code} on site {site_id} equipment {equipment_id or 'any'}. "
        "Use get_fdd_results, portfolio_rollup poll health, bacnet_override_status, "
        "get_equipment_context, and search_docs."
    )


@mcp.prompt()
def tune_fdd_thresholds(site_id: str, rule_id: str = "") -> str:
    return (
        f"Tune thresholds for site {site_id} rule {rule_id or 'noisy rule'}. "
        "Check poll health → get_tuning_brief → preview_fdd_tuning → human approval → apply_fdd_tuning."
    )


@mcp.prompt()
def portfolio_morning_check() -> str:
    return (
        "Portfolio morning check: portfolio_rollup for all sites, rank traffic colors, "
        "top fault deltas, P8 overrides, run-hour spikes, recommend human actions."
    )


@mcp.prompt()
def write_rule_from_cookbook(hvac_system: str, fault_goal: str) -> str:
    return (
        f"Author Arrow rule for {hvac_system} fault goal: {fault_goal}. "
        "search_rule_cookbook → search_model → draft_arrow_rule → lint_rule → human before save."
    )
