"""ASHRAE Guideline 14 calibration metrics (clean-room).

NMBE / CVRMSE for measured vs modeled energy. Used for twin calibration
honesty and IPMVP Option C baseline fit quality — not product FDD.

Monthly calibrated-simulation gate (G14): |NMBE| ≤ 5% and CVRMSE ≤ 15%.
Hourly gate: |NMBE| ≤ 10% and CVRMSE ≤ 30%.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal, Sequence

Granularity = Literal["monthly", "hourly"]

# ASHRAE Guideline 14 acceptance thresholds (percent).
G14_MONTHLY_NMBE_PCT = 5.0
G14_MONTHLY_CVRMSE_PCT = 15.0
G14_HOURLY_NMBE_PCT = 10.0
G14_HOURLY_CVRMSE_PCT = 30.0


@dataclass(frozen=True)
class G14Score:
    """Calibration score for one fuel / meter series."""

    nmbe_pct: float
    cvrmse_pct: float
    n: int
    n_params: int
    mean_measured: float
    pass_: bool
    granularity: Granularity
    fuel: str = "energy"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["pass"] = d.pop("pass_")
        return d


def _pairs(
    measured: Sequence[float],
    predicted: Sequence[float],
) -> tuple[list[float], list[float]]:
    if len(measured) != len(predicted):
        raise ValueError("measured and predicted must have the same length")
    m_out: list[float] = []
    p_out: list[float] = []
    for m, p in zip(measured, predicted, strict=True):
        try:
            mf = float(m)
            pf = float(p)
        except (TypeError, ValueError):
            continue
        if math.isfinite(mf) and math.isfinite(pf):
            m_out.append(mf)
            p_out.append(pf)
    if not m_out:
        raise ValueError("no finite measured/predicted pairs")
    return m_out, p_out


def nmbe_pct(
    measured: Sequence[float],
    predicted: Sequence[float],
    *,
    n_params: int = 1,
) -> float:
    """Normalized mean bias error in percent (ASHRAE G14 form).

    ``NMBE = 100 * Σ(m − p) / ((n − p) * mean(m))``
    """
    m, p = _pairs(measured, predicted)
    n = len(m)
    denom_n = max(n - max(int(n_params), 0), 1)
    mean_m = sum(m) / n
    if mean_m == 0.0:
        raise ValueError("mean measured energy is zero; NMBE undefined")
    return 100.0 * sum(mi - pi for mi, pi in zip(m, p, strict=True)) / (denom_n * mean_m)


def cvrmse_pct(
    measured: Sequence[float],
    predicted: Sequence[float],
    *,
    n_params: int = 1,
) -> float:
    """Coefficient of variation of RMSE in percent (ASHRAE G14 form).

    ``CV(RMSE) = 100 * sqrt(Σ(m − p)² / (n − p)) / mean(m)``
    """
    m, p = _pairs(measured, predicted)
    n = len(m)
    denom_n = max(n - max(int(n_params), 0), 1)
    mean_m = sum(m) / n
    if mean_m == 0.0:
        raise ValueError("mean measured energy is zero; CVRMSE undefined")
    sse = sum((mi - pi) ** 2 for mi, pi in zip(m, p, strict=True))
    rmse = math.sqrt(sse / denom_n)
    return 100.0 * rmse / mean_m


def g14_thresholds(granularity: Granularity) -> tuple[float, float]:
    """Return (|NMBE| max %, CVRMSE max %) for the given granularity."""
    if granularity == "monthly":
        return G14_MONTHLY_NMBE_PCT, G14_MONTHLY_CVRMSE_PCT
    if granularity == "hourly":
        return G14_HOURLY_NMBE_PCT, G14_HOURLY_CVRMSE_PCT
    raise ValueError("granularity must be 'monthly' or 'hourly'")


def score_g14(
    measured: Sequence[float],
    predicted: Sequence[float],
    *,
    granularity: Granularity = "monthly",
    n_params: int = 1,
    fuel: str = "energy",
) -> G14Score:
    """Score one measured vs predicted series against G14 thresholds."""
    m, p = _pairs(measured, predicted)
    n = len(m)
    nmbe = nmbe_pct(m, p, n_params=n_params)
    cvrmse = cvrmse_pct(m, p, n_params=n_params)
    nmbe_max, cvrmse_max = g14_thresholds(granularity)
    passed = abs(nmbe) <= nmbe_max and cvrmse <= cvrmse_max
    return G14Score(
        nmbe_pct=nmbe,
        cvrmse_pct=cvrmse,
        n=n,
        n_params=max(int(n_params), 0),
        mean_measured=sum(m) / n,
        pass_=passed,
        granularity=granularity,
        fuel=str(fuel),
    )


def score_g14_monthly(
    measured: Sequence[float],
    predicted: Sequence[float],
    *,
    n_params: int = 1,
    fuel: str = "energy",
) -> G14Score:
    """Convenience wrapper for monthly calibrated-simulation gate."""
    return score_g14(
        measured,
        predicted,
        granularity="monthly",
        n_params=n_params,
        fuel=fuel,
    )


def score_g14_fuels(
    *,
    elec_measured: Sequence[float] | None = None,
    elec_predicted: Sequence[float] | None = None,
    gas_measured: Sequence[float] | None = None,
    gas_predicted: Sequence[float] | None = None,
    granularity: Granularity = "monthly",
    n_params: int = 1,
) -> dict[str, Any]:
    """Score electric and/or gas series; overall pass requires every fuel pass."""
    scores: dict[str, G14Score] = {}
    if elec_measured is not None and elec_predicted is not None:
        scores["elec"] = score_g14(
            elec_measured,
            elec_predicted,
            granularity=granularity,
            n_params=n_params,
            fuel="elec",
        )
    if gas_measured is not None and gas_predicted is not None:
        scores["gas"] = score_g14(
            gas_measured,
            gas_predicted,
            granularity=granularity,
            n_params=n_params,
            fuel="gas",
        )
    if not scores:
        raise ValueError("provide at least one elec or gas measured/predicted pair")
    return {
        "pass": all(s.pass_ for s in scores.values()),
        "granularity": granularity,
        "fuels": {k: v.to_dict() for k, v in scores.items()},
    }
