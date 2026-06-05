"""
Temperature units for Rule Lab and dashboard.

- Site default: imperial (°F), env VIBE12_TEMP_UNIT=metric for °C.
- Per-rule override: cfg["temp_unit"] = "imperial" | "metric".
- MQTT rows always include degF and degC; rules use row["temp"] in the rule's unit.
"""

from __future__ import annotations

import os
from typing import Any

TEMP_UNITS = ("imperial", "metric")
_F_TO_C = 5.0 / 9.0
_C_TO_F = 9.0 / 5.0


def normalize_temp_unit(value: Any | None = None) -> str:
    if value is None:
        value = os.environ.get("VIBE12_TEMP_UNIT", "imperial")
    s = str(value).strip().lower()
    if s in ("c", "celsius", "metric", "degc", "°c"):
        return "metric"
    return "imperial"


def effective_temp_unit(cfg: dict[str, Any] | None = None, default: Any | None = None) -> str:
    if cfg and cfg.get("temp_unit") is not None:
        return normalize_temp_unit(cfg["temp_unit"])
    return normalize_temp_unit(default)


def temp_unit_symbol(unit: str) -> str:
    return "°C" if normalize_temp_unit(unit) == "metric" else "°F"


def temp_rate_suffix(unit: str, period: str) -> str:
    """period: 'hour' | '15min' | 'minute'."""
    sym = temp_unit_symbol(unit)
    if period == "hour":
        return f"{sym}/hr"
    if period == "15min":
        return f"{sym}/15m"
    return f"{sym}/min"


def temp_from_row(row: dict[str, Any], unit: str) -> float:
    u = normalize_temp_unit(unit)
    if u == "metric":
        if row.get("degC") is not None:
            return float(row["degC"])
        return (float(row["degF"]) - 32.0) * _F_TO_C
    return float(row["degF"])


def f_to_c(deg_f: float) -> float:
    return (deg_f - 32.0) * _F_TO_C


def c_to_f(deg_c: float) -> float:
    return deg_c * _C_TO_F + 32.0


def resolve_cfg_threshold(cfg: dict[str, Any], base_key: str, unit: str) -> float:
    """
    Config value in the rule's unit. Tries neutral key first, then legacy suffixes.

    base_key examples: bounds_low, bounds_high, flatline_tolerance, max_temp_per_hour
    Legacy: bounds_low_f / bounds_low_c, flatline_tolerance_f, max_f_per_hour, etc.
    """
    cfg = cfg or {}
    u = normalize_temp_unit(unit)
    if base_key in cfg:
        return float(cfg[base_key])

    legacy_f = f"{base_key}_f" if not base_key.endswith("_f") else base_key
    legacy_c = f"{base_key}_c" if not base_key.endswith("_c") else base_key

    # Map old names -> neutral base
    aliases: dict[str, tuple[str, ...]] = {
        "bounds_low": ("bounds_low_f", "bounds_low_c"),
        "bounds_high": ("bounds_high_f", "bounds_high_c"),
        "flatline_tolerance": ("flatline_tolerance_f",),
        "max_temp_per_hour": ("max_f_per_hour",),
        "max_temp_per_15min": ("max_f_per_15min",),
        "max_temp_per_minute": ("max_f_per_minute",),
        "max_spread": ("max_spread_f",),
        "max_spread_15min": ("max_spread_f_15min",),
        "max_spread_24h": ("max_spread_f_24h",),
    }
    f_keys = (legacy_f,)
    c_keys = (legacy_c,)
    if base_key in aliases:
        f_keys = aliases[base_key][:1]
        c_keys = aliases[base_key][1:2] if len(aliases[base_key]) > 1 else (legacy_c,)

    if u == "metric":
        for k in c_keys:
            if k in cfg:
                return float(cfg[k])
        for k in f_keys:
            if k in cfg:
                return f_to_c(float(cfg[k]))
    else:
        for k in f_keys:
            if k in cfg:
                return float(cfg[k])
        for k in c_keys:
            if k in cfg:
                return c_to_f(float(cfg[k]))

    raise KeyError(f"config missing {base_key} (unit={u})")


def to_display_temp(value: float, from_unit: str, display_unit: str) -> float:
    """Convert a threshold or sample from rule/storage unit to chart display unit."""
    fu = normalize_temp_unit(from_unit)
    du = normalize_temp_unit(display_unit)
    if fu == du:
        return float(value)
    if du == "metric":
        return f_to_c(float(value))
    return c_to_f(float(value))


def config_field_meta_for_unit(unit: str) -> dict[str, dict[str, Any]]:
    sym = temp_unit_symbol(unit)
    rate_hr = temp_rate_suffix(unit, "hour")
    rate_15 = temp_rate_suffix(unit, "15min")
    rate_min = temp_rate_suffix(unit, "minute")
    return {
        "temp_unit": {
            "label": "Temp unit",
            "type": "choice",
            "choices": list(TEMP_UNITS),
            "default": "imperial",
        },
        "humidity_low": {
            "label": "Low %RH",
            "type": "float",
            "step": 0.1,
            "default": 30.0,
        },
        "humidity_high": {
            "label": "High %RH",
            "type": "float",
            "step": 0.1,
            "default": 60.0,
        },
        "rolling_avg_minutes": {
            "label": "Rolling avg (min)",
            "type": "choice",
            "choices": [1, 5, 10],
            "default": 1,
        },
        "bounds_low": {
            "label": f"Low {sym}",
            "type": "float",
            "step": 0.1,
            "default": 18.0 if unit == "metric" else 65.0,
        },
        "bounds_high": {
            "label": f"High {sym}",
            "type": "float",
            "step": 0.1,
            "default": 27.0 if unit == "metric" else 80.0,
        },
        "flatline_tolerance": {
            "label": f"Flatline tol {sym}",
            "type": "float",
            "step": 0.01,
            "default": 0.03 if unit == "metric" else 0.05,
        },
        "flatline_window": {"label": "Flatline win (samples)", "type": "int", "step": 1},
        "max_temp_per_hour": {
            "label": f"Max {rate_hr}",
            "type": "float",
            "step": 0.1,
            "default": 3.0 if unit == "metric" else 5.0,
        },
        "max_temp_per_15min": {
            "label": f"Max {rate_15}",
            "type": "float",
            "step": 0.1,
            "default": 1.1 if unit == "metric" else 2.0,
        },
        "max_temp_per_minute": {
            "label": f"Max {rate_min}",
            "type": "float",
            "step": 0.1,
            "default": 1.1 if unit == "metric" else 2.0,
        },
        "max_spread": {
            "label": f"Max spread {sym} (1h)",
            "type": "float",
            "step": 0.1,
            "default": 2.2 if unit == "metric" else 4.0,
        },
        "max_spread_15min": {
            "label": f"Max spread {sym} (15m)",
            "type": "float",
            "step": 0.1,
            "default": 1.4 if unit == "metric" else 2.5,
        },
        "max_spread_24h": {
            "label": f"Max peak spread {sym} (24h)",
            "type": "float",
            "step": 0.1,
            "default": 6.7 if unit == "metric" else 12.0,
        },
        # Legacy keys (still shown when editing old rules)
        "bounds_low_f": {"label": f"Low {sym} (legacy key)", "type": "float", "step": 0.1},
        "bounds_high_f": {"label": f"High {sym} (legacy key)", "type": "float", "step": 0.1},
        "flatline_tolerance_f": {"label": f"Flatline tol {sym} (legacy)", "type": "float", "step": 0.01},
        "max_f_per_hour": {"label": f"Max {rate_hr} (legacy)", "type": "float", "step": 0.1},
        "max_f_per_15min": {"label": f"Max {rate_15} (legacy)", "type": "float", "step": 0.1},
        "max_f_per_minute": {"label": f"Max {rate_min} (legacy)", "type": "float", "step": 0.1},
        "max_spread_f": {"label": f"Max spread {sym} (legacy)", "type": "float", "step": 0.1},
        "max_spread_f_15min": {"label": f"Max spread {sym} 15m (legacy)", "type": "float", "step": 0.1},
        "max_spread_f_24h": {"label": f"Max peak spread {sym} 24h (legacy)", "type": "float", "step": 0.1},
    }
