"""Sensor sweep quantity catalog (pandas oracle twin of ``fdd_core::sensor_sweep``)."""

from __future__ import annotations

from typing import Final

# SI only: temperature degC (spike = delta-degC), humidity %, air pressure Pa. The same numbers
# are the literals in sql/fdd/postgres/rules/sv_range.sql and sv_spike.sql.
QUANTITY_LIMITS: Final[dict[str, dict[str, float]]] = {
    "absolute_temperature": {"lo": -51.111111, "hi": 54.444444, "spike": 20.0},
    "relative_humidity": {"lo": 0.0, "hi": 100.0, "spike": 25.0},
    "air_pressure": {"lo": -248.84, "hi": 1990.72, "spike": 497.68},
}

_ROLE_LIMITS: Final[dict[str, dict[str, float]]] = {
    "outside-air-temp": {"lo": -51.111111, "hi": 54.444444, "spike": 20.0},
    "return-air-temp": {"lo": 4.444444, "hi": 37.777778, "spike": 6.666667},
    "mixed-air-temp": {"lo": -28.888889, "hi": 43.333333, "spike": 13.888889},
    "discharge-air-temp": {"lo": -1.111111, "hi": 65.555556, "spike": 22.222222},
    "zone-air-temp": {"lo": 4.444444, "hi": 37.777778, "spike": 6.666667},
    "chilled-water-supply-temp": {"lo": -1.111111, "hi": 26.666667, "spike": 11.111111},
    "chilled-water-return-temp": {"lo": -1.111111, "hi": 32.222222, "spike": 11.111111},
    "hot-water-supply-temp": {"lo": 4.444444, "hi": 104.444444, "spike": 33.333333},
    "hot-water-return-temp": {"lo": 4.444444, "hi": 104.444444, "spike": 33.333333},
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


# Flatline tolerance per quantity. Temperature roles use the tuned ``flatline_tol``
# (a temperature difference in delta-degC).
# %RH tolerance is a declared %RH constant matching
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
    """True only for the SI unit of ``quantity`` (degC, %, Pa); anything else is not assessed, never converted."""
    if unit is None or not str(unit).strip():
        return False
    raw = str(unit).strip()
    t = _norm_unit(raw)
    if quantity == "absolute_temperature":
        return t in {"c", "degc", "celsius"}
    if quantity == "relative_humidity":
        return t in {"pct", "percent", "rh", "percentrelativehumidity"} or "%" in raw
    if quantity == "air_pressure":
        return t in {"pa", "pascal"}
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
