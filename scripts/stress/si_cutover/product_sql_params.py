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


def product_effective_mode_delay_min(params: dict[str, float]) -> float:
    """Mirror render_rule.py + params.rs: max(mode_delay_min, startup_delay_min)."""
    mode = float(params.get("mode_delay_min", 10.0))
    startup = float(params.get("startup_delay_min", runtime_defaults().get("STARTUP_DELAY_MIN", 0.0)))
    return max(mode, startup)


def p0_value_mismatch_reason(rule_id: str, params: dict[str, float]) -> str | None:
    """Classify pandas IP vs SQL IP mismatch root cause (no site-specific allowlist)."""
    if "mode_delay_min" not in catalog_param_keys(rule_id):
        return None
    effective = product_effective_mode_delay_min(params)
    mode = float(params.get("mode_delay_min", 10.0))
    startup = float(params.get("startup_delay_min", 0.0))
    if abs(effective - max(mode, startup)) > 1e-9:
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
