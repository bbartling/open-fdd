"""BUG-ECM-018 — measure honesty status (FITTED vs BALLPARK)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class MeasureHonestyStatus(StrEnum):
    """Honesty labels for sheet ↔ EnergyPlus measure rows."""

    FITTED = "FITTED"
    BALLPARK = "BALLPARK"
    NO_EP = "NO_EP"
    FAIL_SIGN = "FAIL_SIGN"


_FITTED_PROVENANCE = frozenset(
    {
        "FITTED_FROM_EPLUS",
        "FITTED",
        "fitted_from_eplus",
        "fitted",
    }
)


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_diff(a: float | None, b: float | None) -> float | None:
    """(a - b) / max(|b|, 1)."""
    if a is None or b is None:
        return None
    return (a - b) / max(abs(b), 1.0)


def wiring_echo_pct(fitted_kwh: float | None, eplus_kwh: float | None) -> float | None:
    """Audit % when FLH was reverse-solved so fitted ≈ E+ (not validation)."""
    return pct_diff(fitted_kwh, eplus_kwh)


def pct_diff_industry_vs_eplus(
    industry_kwh: float | None, eplus_kwh: float | None
) -> float | None:
    """Real 2nd-eyes %: independent industry screen vs EnergyPlus."""
    return pct_diff(industry_kwh, eplus_kwh)


def classify_measure_status(
    *,
    hours_provenance: str | None = None,
    eplus_kwh: float | None = None,
    industry_kwh: float | None = None,
    fitted_kwh: float | None = None,
    eplus_source: str | None = None,
    sign_ok: bool | None = None,
) -> MeasureHonestyStatus:
    """Classify honesty status.

    Hard rule: reverse-solved FLH → FITTED (never BALLPARK), even when
    ``wiring_echo_pct`` ≈ 0. ``wiring_echo_pct`` is an audit, not validation.
    """
    ep = _num(eplus_kwh)
    industry = _num(industry_kwh)
    fitted = _num(fitted_kwh)
    src = (eplus_source or "").strip().upper()
    prov = (hours_provenance or "").strip()

    if src in {"NO_EP", "NONE", "N/A"} or (ep is None and not src):
        return MeasureHonestyStatus.NO_EP
    if ep is None:
        return MeasureHonestyStatus.NO_EP

    if sign_ok is False:
        return MeasureHonestyStatus.FAIL_SIGN
    if fitted is not None and fitted * ep < 0:
        return MeasureHonestyStatus.FAIL_SIGN
    if industry is not None and industry * ep < 0:
        return MeasureHonestyStatus.FAIL_SIGN

    if prov in _FITTED_PROVENANCE:
        return MeasureHonestyStatus.FITTED

    return MeasureHonestyStatus.BALLPARK
