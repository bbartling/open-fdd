"""Product SQL parameter path for CI Timescale renders (#1284 W3).

Uses ``sql/fdd/render_rule.render`` (same max(MODE_DELAY_MIN, STARTUP_DELAY_MIN) as
``sql/fdd/reference/params.rs`` / ``runtime_defaults.json``). No harness alignment.
"""

from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]

RUNTIME_DEFAULTS_PATH = REPO / "sql" / "fdd" / "runtime_defaults.json"
TUNING_CATALOG_PATH = REPO / "sql" / "fdd" / "tuning_catalog.json"
RENAME_MAP_PATH = REPO / "sql" / "contract" / "parameter_si_rename_map.json"

MODE_DELAY_DEFAULT_VS_STARTUP = "mode_delay_default_vs_startup_delay"


def runtime_defaults() -> dict[str, float]:
    doc = json.loads(RUNTIME_DEFAULTS_PATH.read_text(encoding="utf-8"))
    return {str(k): float(v) for k, v in doc.items()}


def catalog_param_keys(rule_id: str) -> set[str]:
    rules = json.loads(TUNING_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]
    row = next(r for r in rules if str(r.get("rule_id")) == rule_id)
    return set((row.get("parameters") or {}).keys())


@lru_cache(maxsize=1)
def _si_rename_to_legacy() -> dict[str, str]:
    doc = json.loads(RENAME_MAP_PATH.read_text(encoding="utf-8"))
    return {str(new): str(old) for old, new in (doc.get("renames") or {}).items()}


@lru_cache(maxsize=1)
def _master_w4d_tuning_parameters() -> dict[str, dict[str, Any]]:
    from scripts.ci.unit_contract_lib import W4D_SI_PLANT_RULES, ensure_origin_master_ref

    ref = ensure_origin_master_ref()
    proc = subprocess.run(
        ["git", "show", f"{ref}:sql/fdd/tuning_catalog.json"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {}
    rules = json.loads(proc.stdout).get("rules") or []
    return {
        str(r["rule_id"]): dict(r.get("parameters") or {})
        for r in rules
        if str(r.get("rule_id")) in W4D_SI_PLANT_RULES
    }


def ip_parameter_controls(rule_id: str) -> dict[str, Any] | None:
    """Imperial tuning_catalog controls for W4d rules on IP SQL / P0 paths."""
    return _master_w4d_tuning_parameters().get(rule_id)


def catalog_overrides_from_registry(
    rule: dict[str, Any], params: dict[str, float]
) -> dict[str, float]:
    """Map registry.yaml defaults to tuning_catalog override keys (render_rule input)."""
    rule_id = str(rule["rule_id"])
    keys = catalog_param_keys(rule_id)
    legacy = _si_rename_to_legacy()
    out: dict[str, float] = {}
    for name, val in params.items():
        key = name if name in keys else legacy.get(name)
        if key and key in keys:
            out[key] = float(val)
        elif name == "confirm_seconds" and "confirm_min" in keys:
            out["confirm_min"] = float(val) / 60.0
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
