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


class NonSiCatalogControls(ValueError):
    """Rule SQL is not SI-render ready: its catalog still declares non-SI controls."""

    def __init__(self, rule_id: str, controls: list[tuple[str, str]]) -> None:
        self.rule_id = rule_id
        self.controls = controls
        detail = ", ".join(f"{rule_id}.{key} ({unit!r})" for key, unit in controls)
        super().__init__(
            f"tuning catalog declares non-SI units for {detail}; "
            "SQL SI render requires SI parameters"
        )


def catalog_overrides_for_si_render(
    rule: dict[str, Any],
    params_si: dict[str, float],
    metric: dict[str, Any],
) -> dict[str, float]:
    """SI registry params -> render overrides for SQL that computes in SI.

    No SI -> imperial conversion: every overridden catalog control must declare an
    SI (identity-conversion) or unit-invariant unit, otherwise this raises.
    """
    from scripts.ci import unit_contract_lib as uc

    rule_id = str(rule["rule_id"])
    tuning_rules = json.loads(TUNING_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]
    tuning = next(r for r in tuning_rules if str(r.get("rule_id")) == rule_id)
    controls: dict[str, Any] = tuning.get("parameters") or {}
    by_token = uc.build_conversion_index(metric)
    out = catalog_overrides_from_registry(rule, params_si)
    non_si: list[tuple[str, str]] = []
    for key in out:
        unit = str((controls.get(key) or {}).get("unit") or "")
        row = by_token.get(uc.normalize_alias(unit))
        if row is None:
            continue
        if float(row["scale"]) != 1.0 or float(row["offset"]) != 0.0:
            non_si.append((key, unit))
    if non_si:
        raise NonSiCatalogControls(rule_id, non_si)
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
