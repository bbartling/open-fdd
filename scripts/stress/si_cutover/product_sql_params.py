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


def legacy_param_key(name: str) -> str:
    """Pre-SI parameter key for a renamed SI key (identity when not renamed)."""
    return _si_rename_to_legacy().get(name, name)


@lru_cache(maxsize=1)
def _legacy_unit_tuning_parameters() -> dict[str, dict[str, Any]]:
    """Base-branch tuning controls for rules whose parameter units were cut over to SI.

    A rule qualifies when any parameter's declared unit on the base ref differs from
    the current catalog; its base controls are the imperial (IP) render inputs.
    """
    from scripts.ci.unit_contract_lib import ensure_origin_master_ref

    ref = ensure_origin_master_ref()
    proc = subprocess.run(
        ["git", "show", f"{ref}:sql/fdd/tuning_catalog.json"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git show {ref}:sql/fdd/tuning_catalog.json failed: {proc.stderr}")
    legacy = _si_rename_to_legacy()
    current = {
        str(r["rule_id"]): dict(r.get("parameters") or {})
        for r in json.loads(TUNING_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]
    }
    out: dict[str, dict[str, Any]] = {}
    for rule in json.loads(proc.stdout).get("rules") or []:
        rid = str(rule["rule_id"])
        base_params = dict(rule.get("parameters") or {})
        cur_params = current.get(rid)
        if cur_params is None:
            continue
        for key, cur in cur_params.items():
            base = base_params.get(key) or base_params.get(legacy.get(key, key))
            if base is not None and base.get("unit") != cur.get("unit"):
                out[rid] = base_params
                break
    return out


def ip_parameter_controls(rule_id: str) -> dict[str, Any] | None:
    """Imperial tuning_catalog controls for SI-cutover rules on IP SQL / P0 paths.

    Rules still cutting over on this branch use the base ref's imperial controls.
    Rules already SI on the base ref have no imperial base, so their imperial
    controls are converted from the current SI catalog declarations.
    """
    legacy = _legacy_unit_tuning_parameters().get(rule_id)
    if legacy is not None:
        return legacy
    return _si_catalog_controls_as_ip(rule_id)


# Declared SI catalog unit -> (metric quantity, imperial target) per parameter kind.
_SI_TO_IP_UNITS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("degC", "absolute_temperature"): ("absolute_temperature", "degC", "degF"),
    ("degC", "temperature_difference"): ("temperature_difference", "degC_delta", "degF_delta"),
    ("degC_delta", "temperature_difference"): ("temperature_difference", "degC_delta", "degF_delta"),
    ("Pa", "air_pressure"): ("air_pressure", "Pa", "in_wc"),
    ("kPa", "hydronic_pressure"): ("hydronic_pressure", "kPa", "psi"),
}
_SI_FLOW_UNITS = frozenset({"L_per_s", "L/s"})


def _si_control_as_ip(rule_id: str, key: str, ctrl: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any]:
    from scripts.ci import unit_contract_lib as uc

    unit = str(ctrl.get("unit") or "")
    kind = str(ctrl.get("kind") or "")
    if unit in _SI_FLOW_UNITS:
        raise ValueError(
            f"{rule_id}.{key}: SI flow control has no declared imperial base (air cfm vs water gpm)"
        )
    conv = _SI_TO_IP_UNITS.get((unit, kind))
    if conv is None:
        return dict(ctrl)
    quantity, si_unit, ip_unit = conv
    delta = (
        "temperature_difference" if quantity == "absolute_temperature" else quantity,
        "degC_delta" if quantity == "absolute_temperature" else si_unit,
        "degF_delta" if quantity == "absolute_temperature" else ip_unit,
    )

    def level(v: float) -> float:
        return uc.convert_from_canonical(metric, quantity, uc.convert_to_canonical(metric, quantity, float(v), si_unit), ip_unit)

    def span(v: float) -> float:
        q, su, iu = delta
        return uc.convert_from_canonical(metric, q, uc.convert_to_canonical(metric, q, float(v), su), iu)

    out = dict(ctrl)
    out["unit"] = ip_unit
    for field in ("default", "min", "max"):
        if field in ctrl:
            out[field] = level(ctrl[field])
    if "step" in ctrl:
        out["step"] = span(ctrl["step"])
    return out


@lru_cache(maxsize=None)
def _si_catalog_controls_as_ip(rule_id: str) -> dict[str, Any] | None:
    """Imperial controls for a catalog rule whose parameters are declared in SI units."""
    from scripts.ci import unit_contract_lib as uc

    si_units = {u for u, _k in _SI_TO_IP_UNITS} | _SI_FLOW_UNITS
    rules = json.loads(TUNING_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]
    rule = next((r for r in rules if str(r.get("rule_id")) == rule_id), None)
    if rule is None:
        return None
    params = dict(rule.get("parameters") or {})
    if not any(str(c.get("unit") or "") in si_units for c in params.values()):
        return None
    metric = uc.load_json(uc.METRIC_UNITS)
    return {k: _si_control_as_ip(rule_id, k, c, metric) for k, c in params.items()}


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
    """Product effective holdoff: runtime MODE_DELAY_MIN vs registry startup (shared rule)."""
    from open_fdd.rules.mode_delay import effective_mode_delay_min

    defaults = runtime_defaults()
    return effective_mode_delay_min(
        {"mode_delay_min": defaults["MODE_DELAY_MIN"], "startup_delay_min": params["startup_delay_min"]}
    )


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
