"""Occupied zone temperature range (5.0.22): the Python twin of ``shared/zone-band.js``.

One low / high pair, stored in degC with the site's weekly occupancy calendar (``zone_band`` in the OCC-CALENDAR
document), read by the zone comfort analytics (``sql/analytics/zone_comfort.sql`` ``{lo}`` / ``{hi}``) and by the zone
comfort FDD rules (VAV-1 ``zone_t_lo`` / ``zone_t_hi``, SCHED-1 ``comfort_low`` / ``comfort_high``; the pandas runner's VAV-1 spells its pair ``zone_lo`` / ``zone_hi``).

Limits 65-80 degF (18.3333-26.6667 degC); default 70-75 degF (21.1111-23.8889 degC); minimum deadband 2 degF =
10/9 K between the handles. ``validate_band`` is STRICT (a save / API call: raises on a missing, non-numeric, NaN or
inverted band, clamps out-of-range values, widens a band narrower than the deadband). ``resolve_band`` is LENIENT (a
stored value being read: the validated band, else the 70-75 degF default). Precedence into a rule: shipped default <
site band < an explicit per-rule tuning override (``apply_to_params``).
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


def _f2c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


LIMIT_LO_C = _f2c(65.0)
LIMIT_HI_C = _f2c(80.0)
DEFAULT_LO_C = _f2c(70.0)
DEFAULT_HI_C = _f2c(75.0)
MIN_DEADBAND_K = 10.0 / 9.0
_EPS = 1e-9
#: rule parameter pairs that carry the zone comfort band (catalog keys, SI degC)
RULE_PAIRS: tuple[tuple[str, str], ...] = (("zone_t_lo", "zone_t_hi"), ("comfort_low", "comfort_high"), ("zone_lo", "zone_hi"))   # SQL VAV-1, SCHED-1, pandas VAV-1


def default_band() -> dict[str, float]:
    return {"lo_c": DEFAULT_LO_C, "hi_c": DEFAULT_HI_C}


def _num(v: Any) -> float | None:
    """A finite float from a number or numeric string; booleans, '', None, NaN and Infinity are None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str) and v.strip():
        try:
            n = float(v)
        except ValueError:
            return None
        return n if math.isfinite(n) else None
    return None


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def enforce_deadband(lo: float, hi: float) -> tuple[float, float]:
    """Widen lo..hi (inside the limits, lo <= hi) to the minimum deadband, keeping lo where possible."""
    if hi - lo >= MIN_DEADBAND_K - _EPS:
        return lo, hi
    if lo + MIN_DEADBAND_K <= LIMIT_HI_C + _EPS:
        return lo, min(LIMIT_HI_C, lo + MIN_DEADBAND_K)
    return LIMIT_HI_C - MIN_DEADBAND_K, LIMIT_HI_C


def validate_band(raw: Any) -> dict[str, float]:
    """The canonical ``{lo_c, hi_c}`` for a save. Raises ValueError on missing / non-numeric / NaN / inverted input."""
    if raw is None:
        raise ValueError("zone_band is missing (expected {lo_c, hi_c} in degC)")
    if not isinstance(raw, Mapping):
        raise ValueError("zone_band must be {lo_c, hi_c} in degC")
    lo, hi = _num(raw.get("lo_c")), _num(raw.get("hi_c"))
    if lo is None or hi is None:
        raise ValueError("zone_band lo_c and hi_c must both be finite numbers (degC)")
    if lo > hi:
        raise ValueError(f"zone_band is inverted: lo_c ({lo}) is above hi_c ({hi})")
    lo, hi = enforce_deadband(_clamp(lo, LIMIT_LO_C, LIMIT_HI_C), _clamp(hi, LIMIT_LO_C, LIMIT_HI_C))
    return {"lo_c": lo, "hi_c": hi}


def resolve_band(raw: Any) -> dict[str, Any]:
    """The band to USE when reading a stored value (never raises): validated, else the default. ``source`` says which."""
    if raw is None:
        return {**default_band(), "source": "default", "reason": "no saved band"}
    try:
        return {**validate_band(raw), "source": "saved"}
    except ValueError as exc:
        return {**default_band(), "source": "default", "reason": str(exc)}


def apply_to_params(params: dict[str, Any], band: Mapping[str, Any] | None, explicit: Iterable[str] = ()) -> dict[str, Any]:
    """Put the site band under explicit tuning. For each comfort pair present in ``params``, a key NOT in ``explicit``
    takes the band value; an explicit key always wins. With only one key of a pair explicit, the band's other value is
    used only if hi - lo stays >= the deadband. Returns a new dict (``params`` is not modified)."""
    out = dict(params)
    if not band:
        return out
    tuned = set(explicit)
    lo_c, hi_c = float(band["lo_c"]), float(band["hi_c"])
    for lo_k, hi_k in RULE_PAIRS:
        if lo_k not in out or hi_k not in out:
            continue
        lo_set, hi_set = lo_k in tuned, hi_k in tuned
        if lo_set and hi_set:
            continue
        if not lo_set and not hi_set:
            out[lo_k], out[hi_k] = lo_c, hi_c
        elif lo_set:
            if hi_c - float(out[lo_k]) >= MIN_DEADBAND_K - _EPS:
                out[hi_k] = hi_c
        elif float(out[hi_k]) - lo_c >= MIN_DEADBAND_K - _EPS:
            out[lo_k] = lo_c
    return out