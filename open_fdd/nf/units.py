"""SI conversion for NF point values (Python port of ``nf-app/static/units.js``).

FDD and analytics math run in SI only: temperature degC, pressure Pa, flow L/s, power kW,
energy kWh, percent % (0-100). Same table and same canonical units as the NF app, so the
pandas rules and the SQL pack see identical numbers. An unknown or empty unit returns ``None``
(the caller decides whether to keep the value as is or skip the role).
"""

from __future__ import annotations

from typing import Callable, NamedTuple


class SI(NamedTuple):
    value: float
    unit: str
    quantity: str


def norm_unit(unit: object) -> str:
    """Same normalisation as the JS ``norm``: trim, lower-case, drop spaces and underscores."""
    s = str(unit or "").strip().lower()
    for ch in (" ", "\t", "_"):
        s = s.replace(ch, "")
    return s.replace("₂", "2").replace("º", "°")


# unit -> (quantity, SI unit, to_si)
_TABLE: dict[str, tuple[str, str, Callable[[float], float]]] = {}


def _add(names: list[str], quantity: str, si: str, f: Callable[[float], float]) -> None:
    for n in names:
        _TABLE[norm_unit(n)] = (quantity, si, f)


def _ident(x: float) -> float:
    return x


_add(["°C", "degC", "C", "celsius", "deg_c"], "temperature", "°C", _ident)
_add(["°F", "degF", "F", "fahrenheit", "deg_f"], "temperature", "°C", lambda x: (x - 32) * 5 / 9)
_add(["K", "kelvin"], "temperature", "°C", lambda x: x - 273.15)
_add(["Pa", "pascal"], "pressure", "Pa", _ident)
_add(["kPa"], "pressure", "Pa", lambda x: x * 1000)
_add(["inH2O", "inWC", "in wc", "in. w.c.", "inH₂O", '"wc', "in_h2o"], "pressure", "Pa", lambda x: x * 249.0889)
_add(["psi", "psig", "psid"], "pressure", "Pa", lambda x: x * 6894.757)
_add(["bar"], "pressure", "Pa", lambda x: x * 1e5)
_add(["L/s", "l/s", "lps"], "flow", "L/s", _ident)
_add(["m³/s", "m3/s"], "flow", "L/s", lambda x: x * 1000)
_add(["m³/h", "m3/h", "cmh"], "flow", "L/s", lambda x: x / 3.6)
_add(["cfm", "ft³/min", "ft3/min"], "flow", "L/s", lambda x: x * 0.4719474)
_add(["gpm", "gal/min"], "flow", "L/s", lambda x: x * 0.0630902)
_add(["kW"], "power", "kW", _ident)
_add(["W"], "power", "kW", lambda x: x / 1000)
_add(["MW"], "power", "kW", lambda x: x * 1000)
_add(["Btu/h", "btuh", "btu/hr"], "power", "kW", lambda x: x * 0.00029307107)
_add(["ton", "tons", "tonref", "tr"], "power", "kW", lambda x: x * 3.5168525)
_add(["hp"], "power", "kW", lambda x: x * 0.7456999)
_add(["kWh"], "energy", "kWh", _ident)
_add(["Wh"], "energy", "kWh", lambda x: x / 1000)
_add(["MWh"], "energy", "kWh", lambda x: x * 1000)
_add(["kBtu"], "energy", "kWh", lambda x: x * 0.29307107)
_add(["MMBtu"], "energy", "kWh", lambda x: x * 293.07107)
_add(["therm", "therms"], "energy", "kWh", lambda x: x * 29.307107)
_add(["%", "%RH", "percent", "pct"], "percent", "%", _ident)
_add(["ppm"], "concentration", "ppm", _ident)


def to_si(value: float, unit: object) -> SI | None:
    """Value in canonical SI, or ``None`` when the unit is unknown/empty or the value not finite."""
    row = _TABLE.get(norm_unit(unit))
    if row is None or value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return SI(row[2](x), row[1], row[0])


def quantity_of(unit: object) -> str | None:
    row = _TABLE.get(norm_unit(unit))
    return row[0] if row else None


def si_unit_of(unit: object) -> str | None:
    row = _TABLE.get(norm_unit(unit))
    return row[1] if row else None


def convert_series(series, unit: object):
    """Vectorised ``to_si`` for a pandas Series; returns ``(series, si_unit, quantity)`` or ``None``.

    The conversion function of the table is applied to the whole Series (all are affine), so
    NaN stays NaN.
    """
    row = _TABLE.get(norm_unit(unit))
    if row is None:
        return None
    return row[2](series), row[1], row[0]
