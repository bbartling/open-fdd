"""Product SQL parameter path for CI Timescale renders (#1284 W3).

Uses ``sql/fdd/render_rule.render`` (same max(MODE_DELAY_MIN, STARTUP_DELAY_MIN) as
``sql/fdd/reference/params.rs`` / ``runtime_defaults.json``). No harness alignment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]

RUNTIME_DEFAULTS_PATH = REPO / "sql" / "fdd" / "runtime_defaults.json"
TUNING_CATALOG_PATH = REPO / "sql" / "fdd" / "tuning_catalog.json"

MODE_DELAY_DEFAULT_VS_STARTUP = "mode_delay_default_vs_startup_delay"


def runtime_defaults() -> dict[str, float]:
    doc = json.loads(RUNTIME_DEFAULTS_PATH.read_text(encoding="utf-8"))
    return {str(k): float(v) for k, v in doc.items()}


def catalog_param_keys(rule_id: str) -> set[str]:
    rules = json.loads(TUNING_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]
    row = next(r for r in rules if str(r.get("rule_id")) == rule_id)
    return set((row.get("parameters") or {}).keys())


def catalog_overrides_from_registry(
    rule: dict[str, Any], params: dict[str, float]
) -> dict[str, float]:
    """Map registry.yaml defaults to tuning_catalog override keys (render_rule input)."""
    keys = catalog_param_keys(str(rule["rule_id"]))
    out: dict[str, float] = {}
    for name, val in params.items():
        if name in keys:
            out[name] = float(val)
        elif name == "confirm_seconds" and "confirm_min" in keys:
            out["confirm_min"] = float(val) / 60.0
    return out


def _quantity_for_param_spec(spec: dict[str, Any]) -> str | None:
    kind = str(spec.get("kind") or "")
    unit = str(spec.get("unit") or "")
    if kind == "absolute_temperature":
        return "absolute_temperature"
    if kind == "temperature_difference":
        return "temperature_difference"
    if kind == "air_pressure":
        return "air_pressure"
    if kind == "hydronic_pressure":
        return "hydronic_pressure"
    if kind in ("duration_minutes", "duration_seconds"):
        return "duration"
    if kind == "percent":
        return "dimensionless"
    if unit in ("degF", "degC", "°F", "°C"):
        return "absolute_temperature"
    if unit in ("degF_delta", "degC_delta"):
        return "temperature_difference"
    if unit in ("Pa", "inWC", "inH2O", "psi", "kPa"):
        return "air_pressure"
    return None


def _source_unit_for_convert(unit: str, quantity: str) -> str:
    if quantity == "temperature_difference" and unit == "degF":
        return "degF_delta"
    if quantity == "temperature_difference" and unit in ("degC", "°C"):
        return "degC_delta"
    if unit == "pct":
        return "percent"
    if unit.lower() in ("inwc", "in_wc"):
        return "inWC"
    return unit


def catalog_overrides_for_si_render(
    rule: dict[str, Any],
    params_si: dict[str, float],
    metric: dict[str, Any],
) -> dict[str, float]:
    """SI canonical registry params → render overrides in tuning_catalog units."""
    from scripts.ci import unit_contract_lib as uc

    rule_id = str(rule["rule_id"])
    tuning_rules = json.loads(TUNING_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]
    tuning = next(r for r in tuning_rules if str(r.get("rule_id")) == rule_id)
    controls: dict[str, Any] = tuning.get("parameters") or {}
    keys = catalog_param_keys(rule_id)
    filtered: dict[str, float] = {}
    reg_params = rule.get("parameters") or {}

    for name, val in params_si.items():
        catalog_key = name
        canon = float(val)
        if name == "confirm_seconds" and "confirm_min" in keys:
            catalog_key = "confirm_min"
            canon = float(val) / 60.0
        if catalog_key not in keys:
            continue
        ctrl = controls.get(catalog_key) or {}
        lo = float(ctrl.get("min", float("-inf")))
        hi = float(ctrl.get("max", float("inf")))
        spec = reg_params.get(name) if isinstance(reg_params.get(name), dict) else {}
        kind = str(spec.get("kind") or ctrl.get("kind") or "")
        unit = str(spec.get("unit") or ctrl.get("unit") or "")
        quantity = _quantity_for_param_spec({**ctrl, **spec})
        render_val = canon
        if quantity and unit and kind not in (
            "duration_minutes",
            "duration_seconds",
            "boolean",
            "percent",
        ):
            src = _source_unit_for_convert(unit, quantity)
            if unit in ("degC", "degC_delta", "Pa", "kPa", "L/s"):
                render_val = canon
            else:
                render_val = uc.convert_from_canonical(metric, quantity, canon, src)
            in_range = lo <= render_val <= hi
        else:
            in_range = lo <= canon <= hi
            render_val = canon
        if in_range:
            filtered[name] = float(val) if name != "confirm_seconds" else float(val)
            # store render-facing value under registry name; map below
            filtered[f"__render__{name}"] = render_val
        elif ctrl.get("effect_in_sql", True):
            raise ValueError(
                f"{rule_id}.{catalog_key} SI render value {render_val} outside [{lo}, {hi}]"
            )

    # Build overrides dict keyed for render_rule (catalog keys, catalog-unit values)
    out: dict[str, float] = {}
    for name, val in params_si.items():
        if name == "confirm_seconds" and "confirm_min" in keys:
            rk = "__render__confirm_seconds"
            ck = "confirm_min"
        else:
            rk = f"__render__{name}"
            ck = name
        if rk in filtered:
            out[ck if ck != "confirm_seconds" else "confirm_min"] = filtered[rk]
    return out


def product_effective_mode_delay_min(params: dict[str, float]) -> float:
    """Mirror render_rule.py + params.rs: max(runtime MODE_DELAY_MIN, STARTUP_DELAY_MIN)."""
    defaults = runtime_defaults()
    mode = float(defaults.get("MODE_DELAY_MIN", 10.0))
    startup = float(params.get("startup_delay_min", defaults.get("STARTUP_DELAY_MIN", 0.0)))
    return max(mode, startup)


def p0_value_mismatch_reason(rule_id: str, params: dict[str, float]) -> str | None:
    """Classify pandas IP vs SQL IP mismatch root cause (no site-specific allowlist)."""
    if "mode_delay_min" not in catalog_param_keys(rule_id):
        return None
    startup = float(params.get("startup_delay_min", 0.0))
    effective = product_effective_mode_delay_min(params)
    if effective > startup + 1e-9:
        return MODE_DELAY_DEFAULT_VS_STARTUP
    return None


def render_rule_sql_product(
    rule_id: str,
    poll_seconds: float,
    *,
    registry_params: dict[str, float],
) -> str:
    import sys

    sys.path.insert(0, str(REPO / "sql" / "fdd"))
    from render_rule import render  # type: ignore

    rule_stub = {"rule_id": rule_id}
    overrides = catalog_overrides_from_registry(rule_stub, registry_params)
    return render(rule_id, poll_seconds=poll_seconds, overrides=overrides, dialect="postgres")
