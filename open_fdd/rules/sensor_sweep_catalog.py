"""Sensor sweep quantity catalog (pandas oracle twin of ``fdd_core::sensor_sweep``)."""

from __future__ import annotations

from typing import Final

from open_fdd.units.convert import ip_bound_to_si

QUANTITY_LIMITS: Final[dict[str, dict[str, float]]] = {
    "absolute_temperature": {"lo": -60.0, "hi": 130.0, "spike": 36.0},
    "relative_humidity": {"lo": 0.0, "hi": 100.0, "spike": 25.0},
    "air_pressure": {"lo": -1.0, "hi": 8.0, "spike": 2.0},
}

_ROLE_LIMITS: Final[dict[str, dict[str, float]]] = {
    "outside-air-temp": {"lo": -60.0, "hi": 130.0, "spike": 36.0},
    "return-air-temp": {"lo": 40.0, "hi": 100.0, "spike": 12.0},
    "mixed-air-temp": {"lo": -20.0, "hi": 110.0, "spike": 25.0},
    "discharge-air-temp": {"lo": 30.0, "hi": 150.0, "spike": 40.0},
    "zone-air-temp": {"lo": 40.0, "hi": 100.0, "spike": 12.0},
    "chilled-water-supply-temp": {"lo": 30.0, "hi": 80.0, "spike": 20.0},
    "chilled-water-return-temp": {"lo": 30.0, "hi": 90.0, "spike": 20.0},
    "hot-water-supply-temp": {"lo": 40.0, "hi": 220.0, "spike": 60.0},
    "hot-water-return-temp": {"lo": 40.0, "hi": 220.0, "spike": 60.0},
    "outside-air-humidity": QUANTITY_LIMITS["relative_humidity"],
    "return-air-humidity": QUANTITY_LIMITS["relative_humidity"],
    "zone-air-humidity": QUANTITY_LIMITS["relative_humidity"],
    "mixed-air-humidity": QUANTITY_LIMITS["relative_humidity"],
    "supply-air-humidity": QUANTITY_LIMITS["relative_humidity"],
    "duct-static-pressure": QUANTITY_LIMITS["air_pressure"],
}

_EXPECTED_CONSTANT_TOKENS: Final[tuple[str, ...]] = (
    "status",
    "cmd",
    "command",
    "setpoint",
    "occupied",
    "occupancy",
    "loop-enabled",
)


def quantity_for_haystack_role(role: str) -> str | None:
    r = (role or "").strip().lower()
    if not r:
        return None
    if "humid" in r or r.endswith("-rh"):
        return "relative_humidity"
    if "static" in r or "pressure" in r or r.endswith("-dp"):
        return "air_pressure"
    if "temp" in r or "wetbulb" in r or "dewpoint" in r:
        return "absolute_temperature"
    return None


def limits_for_haystack_role(role: str) -> dict[str, float] | None:
    if role in _ROLE_LIMITS:
        return dict(_ROLE_LIMITS[role])
    q = quantity_for_haystack_role(role)
    if q and q in QUANTITY_LIMITS:
        return dict(QUANTITY_LIMITS[q])
    return None


# Declared imperial units of the limit table above (SV-RANGE / SV-SPIKE source).
_QUANTITY_IP_UNITS: Final[dict[str, tuple[str, str] | None]] = {
    "absolute_temperature": ("degF", "degF_delta"),
    "air_pressure": ("inH2O", "inH2O"),
    "relative_humidity": None,
}


def limits_for_haystack_role_si(role: str) -> dict[str, float] | None:
    """Same limit table as :func:`limits_for_haystack_role`, in canonical SI storage units."""
    lim = limits_for_haystack_role(role)
    if lim is None:
        return None
    q = quantity_for_haystack_role(role)
    if q is None or q not in _QUANTITY_IP_UNITS:
        raise ValueError(f"sensor limit role {role!r} has no declared quantity unit")
    units = _QUANTITY_IP_UNITS[q]
    if units is None:
        return lim
    abs_unit, delta_unit = units
    return {
        "lo": float(ip_bound_to_si(lim["lo"], abs_unit)),
        "hi": float(ip_bound_to_si(lim["hi"], abs_unit)),
        "spike": float(ip_bound_to_si(lim["spike"], delta_unit)),
    }


# Flatline tolerance per quantity. Temperature roles use the tuned ``flatline_tol``
# (a temperature difference, so it is unit-system invariant up to the K/delta-F scale).
# %RH is identical in IP and SI, so its tolerance is a declared %RH constant matching
# ``sv_flatline.sql``; it must never inherit a temperature tolerance.
HUMIDITY_FLATLINE_TOL_PCT: Final[float] = 0.1


def flatline_tolerance_for_role(role: str, temperature_tol: float) -> float:
    """Flatline span tolerance for ``role`` in the frame's storage units."""
    q = quantity_for_haystack_role(role)
    if q == "relative_humidity":
        return HUMIDITY_FLATLINE_TOL_PCT
    if q == "absolute_temperature":
        return float(temperature_tol)
    raise ValueError(f"flatline role {role!r} has no declared tolerance quantity ({q!r})")


def is_expected_constant_role(role: str) -> bool:
    r = (role or "").strip().lower()
    if not r:
        return False
    if r.endswith("-sp") or r.endswith("_sp") or "setpoint" in r:
        return True
    return any(tok in r for tok in _EXPECTED_CONSTANT_TOKENS)


def _norm_unit(unit: str) -> str:
    return "".join(ch for ch in unit.strip().lower() if ch.isalnum())


def unit_declares_quantity(unit: str | None, quantity: str) -> bool:
    if unit is None or not str(unit).strip():
        return False
    raw = str(unit).strip()
    t = _norm_unit(raw)
    if quantity == "absolute_temperature":
        return t in {"f", "degf", "fahrenheit", "c", "degc", "celsius"}
    if quantity == "relative_humidity":
        return t in {"pct", "percent", "rh", "percentrelativehumidity"} or "%" in raw
    if quantity == "air_pressure":
        return t in {"inwc", "inh2o", "pa", "pascal"} or "w.c" in raw
    return False


def sweep_assessable_role(role: str, unit: str | None, units_map: dict[str, str] | None = None) -> bool:
    if is_expected_constant_role(role):
        return False
    lim = limits_for_haystack_role(role)
    if lim is None:
        return False
    resolved = (units_map or {}).get(role) or unit
    if not resolved or resolved in {"bool", "0/1"}:
        return False
    q = quantity_for_haystack_role(role)
    if not q:
        return False
    return unit_declares_quantity(resolved, q)


def flatline_quantity_allowed(quantity: str) -> bool:
    return quantity != "air_pressure"
