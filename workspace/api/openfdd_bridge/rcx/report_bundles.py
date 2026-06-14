"""Data-model-driven RCx report bundles (AHU / HWS / VAV per equipment)."""

from __future__ import annotations

from typing import Any

from ..equipment_classify import report_family
from .trend_charts import ROLE_BRICK_CLASSES, historian_column_for_point, resolve_roles_on_tree

CHART_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "ahu": [
        {
            "suffix": "sat_vs_sp",
            "title": "Supply air temp vs setpoint",
            "brick_patterns": [
                ["supply_air_temperature", "Supply_Air_Temperature"],
                [
                    "discharge_air_temperature_setpoint",
                    "Discharge_Air_Temperature_Setpoint",
                    "supply_air_temperature_setpoint",
                    "Supply_Air_Temperature_Setpoint",
                ],
            ],
        },
        {
            "suffix": "duct_static",
            "title": "Duct static pressure vs setpoint",
            "brick_patterns": [
                ["duct_static", "Supply_Air_Static_Pressure", "static_pressure"],
                ["duct_static_pressure_setpoint", "Supply_Air_Static_Pressure_Setpoint", "static_setpoint"],
            ],
        },
        {
            "suffix": "oa_mat_rat",
            "title": "Outdoor / mixed / return air temps",
            "brick_patterns": [
                ["outside_air_temperature", "Outside_Air_Temperature", "oa-t", "outdoor_air"],
                ["mixed_air_temperature", "Mixed_Air_Temperature"],
                ["return_air_temperature", "Return_Air_Temperature"],
            ],
        },
    ],
    "vav": [
        {
            "suffix": "zone_temp",
            "title": "Zone temperature vs setpoints",
            "brick_patterns": [
                ["zone_air_temperature", "Zone_Air_Temperature", "space_temperature"],
                ["cooling_temperature_setpoint", "Cooling_Temperature_Setpoint", "active_cool"],
                ["heating_temperature_setpoint", "Heating_Temperature_Setpoint", "active_heat"],
            ],
        },
        {
            "suffix": "damper",
            "title": "Damper command vs position",
            "brick_patterns": [
                ["damper_position_command", "Damper_Position_Command", "air_valve_drive_command"],
                ["damper_position_sensor", "Damper_Position_Sensor", "air_valve_drive_status"],
            ],
        },
        {
            "suffix": "airflow",
            "title": "Discharge airflow vs setpoint",
            "brick_patterns": [
                ["supply_air_flow_sensor", "Supply_Air_Flow_Sensor", "discharge_air_flow"],
                ["supply_air_flow_setpoint", "Supply_Air_Flow_Setpoint", "air_flow_setpoint"],
            ],
        },
    ],
    "hws": [
        {
            "suffix": "hw_supply_temps",
            "title": "Hot water supply temperatures",
            "brick_patterns": [
                ["hot_water", "boiler", "hw_supply", "supply_temperature"],
            ],
        },
        {
            "suffix": "hw_pump",
            "title": "Pump / valve commands",
            "brick_patterns": [
                ["pump", "Pump", "valve_command", "Valve_Command"],
            ],
        },
    ],
    "chiller": [
        {
            "suffix": "chw_supply_temps",
            "title": "Chilled water supply / return temperatures",
            "brick_patterns": [
                ["chilled_water", "Chilled_Water", "chw_supply", "supply_temperature"],
                ["return_water", "Return_Water_Temperature"],
            ],
        },
        {
            "suffix": "chiller_load",
            "title": "Chiller load / status",
            "brick_patterns": [
                ["chiller", "Chiller", "compressor", "load"],
                ["Run_Status", "On_Off_Status"],
            ],
        },
    ],
}

BUILDING_CHARTS = [
    {"chart_id": "building_inventory", "title": "Building inventory & active faults"},
]


def _norm(s: str) -> str:
    return str(s or "").lower().replace("-", "_").replace(" ", "_")


def _point_haystack(pt: dict[str, Any]) -> str:
    return _norm(
        " ".join(
            str(pt.get(k) or "")
            for k in (
                "brick_class",
                "brick_type",
                "external_id",
                "fdd_input",
                "name",
                "description",
                "brick_tag",
            )
        )
    )


def _match_patterns(pt: dict[str, Any], patterns: list[str]) -> bool:
    hay = _point_haystack(pt)
    for pat in patterns:
        p = _norm(pat)
        if p and p in hay:
            return True
    return False


def _columns_for_template(
    points: list[dict[str, Any]],
    brick_patterns: list[list[str]],
    *,
    equipment_id: str | None = None,
) -> list[str]:
    """Resolve historian columns via BRICK chart roles (SPARQL tree), then pattern fallback."""
    tree = {"points": points}
    eq_ids = [equipment_id] if equipment_id else None
    cols: list[str] = []
    for group in brick_patterns:
        role_key = next((p for p in group if p in ROLE_BRICK_CLASSES), None)
        if role_key:
            resolved, _ = resolve_roles_on_tree(tree, [role_key], equipment_ids=eq_ids)
            if resolved:
                for col in resolved:
                    if col not in cols:
                        cols.append(col)
                continue
        for pt in points:
            if not isinstance(pt, dict):
                continue
            if not _match_patterns(pt, group):
                continue
            col = historian_column_for_point(
                {
                    "external_id": pt.get("external_id"),
                    "fdd_input": pt.get("fdd_input"),
                    "timeseries_column": pt.get("timeseries_column"),
                    "id": pt.get("point_id") or pt.get("id"),
                    "name": pt.get("name"),
                    "brick_type": pt.get("brick_type") or pt.get("brick_class"),
                }
            )
            if col and col not in cols:
                cols.append(col)
                break
    return cols


def _chart_id(equipment_id: str, suffix: str) -> str:
    return f"eq:{equipment_id}:{suffix}"


def _equipment_label(eq: dict[str, Any], equipment_id: str) -> str:
    return str(eq.get("name") or eq.get("equipment_name") or equipment_id)


def build_equipment_charts(
    equipment_id: str,
    *,
    family: str,
    equipment_name: str,
    points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    for tmpl in CHART_TEMPLATES.get(family) or []:
        cols = _columns_for_template(points, tmpl["brick_patterns"], equipment_id=equipment_id)
        if len(cols) < 1:
            continue
        suffix = str(tmpl["suffix"])
        charts.append(
            {
                "chart_id": _chart_id(equipment_id, suffix),
                "title": f"{equipment_name} — {tmpl['title']}",
                "equipment_id": equipment_id,
                "equipment_name": equipment_name,
                "family": family,
                "columns": cols,
                "suffix": suffix,
            }
        )
    return charts


def build_report_bundles(
    *,
    equipment_rows: list[dict[str, Any]],
    equipment_meta: dict[str, dict[str, Any]] | None = None,
    fault_rows: list[dict[str, Any]] | None = None,
    include_fault_charts: bool = True,
) -> dict[str, Any]:
    """Build selectable report packages from equipment_to_points + model metadata."""
    meta = equipment_meta or {}
    by_eq: dict[str, list[dict[str, Any]]] = {}
    for row in equipment_rows:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("equipment_id") or "").strip()
        if not eid:
            continue
        by_eq.setdefault(eid, []).append(row)

    bundles: list[dict[str, Any]] = []
    all_equipment_charts: list[dict[str, Any]] = []

    building_chart_ids = [c["chart_id"] for c in BUILDING_CHARTS]
    if include_fault_charts and fault_rows:
        building_chart_ids = ["fault_hours_by_severity", "fault_hours_by_equipment", *building_chart_ids]

    bundles.append(
        {
            "bundle_id": "building",
            "family": "building",
            "label": "Building overview",
            "equipment_id": None,
            "equipment_name": None,
            "chart_ids": building_chart_ids,
            "chart_count": len(building_chart_ids),
            "default_selected": True,
        }
    )

    families: dict[str, dict[str, Any]] = {
        "building": {"label": "Building overview", "count": 0},
        "ahu": {"label": "AHU reports", "count": 0},
        "vav": {"label": "VAV reports", "count": 0},
        "hws": {"label": "HWS / boiler plant reports", "count": 0},
        "chiller": {"label": "Chiller plant reports", "count": 0},
    }

    ahu_first = True
    for eid in sorted(by_eq.keys()):
        pts = by_eq[eid]
        eq = dict(meta.get(eid) or {})
        eq.setdefault("equipment_id", eid)
        eq.setdefault("id", eid)
        if not eq.get("name"):
            eq["name"] = pts[0].get("equipment_type") or eid

        family = report_family(eq)
        if family not in ("ahu", "hws", "vav", "chiller"):
            continue

        name = _equipment_label(eq, eid)
        charts = build_equipment_charts(eid, family=family, equipment_name=name, points=pts)
        if not charts:
            continue

        all_equipment_charts.extend(charts)
        families[family]["count"] = int(families[family]["count"]) + 1

        default = False
        if family == "ahu" and ahu_first:
            default = True
            ahu_first = False

        family_label = {"ahu": "AHU", "hws": "HWS", "vav": "VAV", "chiller": "Chiller"}.get(
            family, family.upper()
        )
        bundles.append(
            {
                "bundle_id": f"{family}:{eid}",
                "family": family,
                "label": f"{family_label} report — {name}",
                "equipment_id": eid,
                "equipment_name": name,
                "chart_ids": [c["chart_id"] for c in charts],
                "chart_count": len(charts),
                "default_selected": default,
            }
        )

    default_bundle_ids = [b["bundle_id"] for b in bundles if b.get("default_selected")]

    return {
        "bundles": bundles,
        "equipment_charts": all_equipment_charts,
        "families": families,
        "default_bundle_ids": default_bundle_ids,
    }


def chart_ids_for_bundles(bundles: list[dict[str, Any]], selected_ids: list[str]) -> list[str]:
    selected = set(selected_ids or [])
    if not selected:
        selected = {b["bundle_id"] for b in bundles if b.get("default_selected")}
    out: list[str] = []
    for bundle in bundles:
        if bundle.get("bundle_id") not in selected:
            continue
        for cid in bundle.get("chart_ids") or []:
            if cid not in out:
                out.append(str(cid))
    return out


def equipment_charts_for_ids(
    equipment_charts: list[dict[str, Any]],
    chart_ids: list[str],
) -> list[dict[str, Any]]:
    wanted = set(chart_ids or [])
    return [c for c in equipment_charts if c.get("chart_id") in wanted]
