"""FDD rules & analytics visibility for RCx Central (read-only Edge queries)."""

from __future__ import annotations

from typing import Any

from portfolio.central.chart_specs import CHART_SPECS
from portfolio.central.fault_code_lookup import lookup_fault_description
from portfolio.central.edge_registry import resolve_site_config, resolve_token
from portfolio.collector.edge_client import EdgeClient


def _charts_for_rule(rule: dict[str, Any]) -> list[str]:
    code = str(rule.get("fault_code") or rule.get("code") or "").upper()
    name = str(rule.get("name") or "").lower()
    out: list[str] = []
    for spec in CHART_SPECS:
        related = [str(c).upper() for c in (spec.get("related_fault_codes") or [])]
        if code and any(code in r or r in code for r in related):
            out.append(spec["chart_id"])
        elif "sat" in name and "sat" in spec["chart_id"]:
            out.append(spec["chart_id"])
        elif "duct" in name and "duct" in spec["chart_id"]:
            out.append(spec["chart_id"])
        elif "zone" in name and "vav" in spec["chart_id"]:
            out.append(spec["chart_id"])
    return out


def build_fdd_analytics(site_id: str, *, hours: int = 24) -> dict[str, Any]:
    site = resolve_site_config(site_id)
    client = EdgeClient(site.base_url)
    token = resolve_token(site)

    rules_raw = client.get_fdd_rules(token=token)
    rules_list = rules_raw.get("rules") if isinstance(rules_raw.get("rules"), list) else []
    if not rules_list and isinstance(rules_raw.get("saved"), list):
        rules_list = rules_raw["saved"]

    faults = client.get_analytics_faults(hours=hours, token=token)
    fault_rows = faults.get("faults") if isinstance(faults.get("faults"), list) else []
    warnings: list[str] = []
    if not fault_rows:
        try:
            status = client.get_faults_status(token=token)
            for fam in status.get("families") or []:
                if not isinstance(fam, dict):
                    continue
                for f in fam.get("faults") or []:
                    if isinstance(f, dict):
                        fault_rows.append(
                            {
                                "rule_id": f.get("rule_id"),
                                "fault_code": f.get("code"),
                                "fault_name": f.get("title"),
                                "severity": f.get("severity"),
                            }
                        )
            if fault_rows and not faults:
                warnings.append("Using /api/faults/status — /api/analytics/faults not on this Edge build.")
        except RuntimeError:
            pass
    by_rule: dict[str, dict[str, Any]] = {}
    for row in fault_rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("rule_id") or row.get("fault_code") or "")
        if not rid:
            continue
        bucket = by_rule.setdefault(rid, {"active_count": 0, "elapsed_hours": 0.0})
        bucket["active_count"] += 1
        bucket["elapsed_hours"] += float(row.get("elapsed_hours") or 0)

    rules_out: list[dict[str, Any]] = []
    for rule in rules_list:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or rule.get("rule_id") or rule.get("name") or "")
        stats = by_rule.get(rid) or by_rule.get(str(rule.get("fault_code") or "")) or {}
        cfg = rule.get("config") if isinstance(rule.get("config"), dict) else {}
        rules_out.append(
            {
                "rule_id": rid,
                "fault_code": rule.get("fault_code") or rule.get("code"),
                "fault_name": rule.get("name") or rule.get("title"),
                "fault_description": lookup_fault_description(str(rule.get("fault_code") or rule.get("code") or "")),
                "equipment_type": rule.get("equipment_type") or cfg.get("equipment_type"),
                "severity": rule.get("severity") or cfg.get("severity"),
                "required_roles": cfg.get("required_roles") or rule.get("required_roles") or [],
                "optional_roles": cfg.get("optional_roles") or [],
                "enabled": rule.get("enabled", True),
                "active_fault_count": stats.get("active_count", 0),
                "elapsed_fault_hours": stats.get("elapsed_hours", 0.0),
                "chart_pack": _charts_for_rule(rule),
            }
        )

    presets = client.get_fdd_query_presets(token=token)
    preset_list = presets.get("presets") if isinstance(presets.get("presets"), list) else []

    return {
        "site_id": site_id,
        "site_name": site.name,
        "lookback_hours": hours,
        "rules": rules_out,
        "rules_configured": len(rules_out),
        "active_faults": len(fault_rows),
        "model_query_presets": preset_list[:30],
        "warnings": warnings
        + ([] if rules_out else ["No FDD rules returned from Edge — check Rule Lab export."]),
    }
