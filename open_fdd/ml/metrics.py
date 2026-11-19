"""Detection metrics in the style of the LBNL / NREL FDD evaluation framework (Frank, Lin, Granderson et al. 2019).

An *evaluation sample* is a fixed window (default one hour) in which the unit was operating for at least
``min_active`` (default 0.5) of the window's ELAPSED time. Coverage is measured against the window length at the
data cadence (declared, or the median sample spacing), never against the rows that happen to be present, so one
5-minute sample cannot make a whole hour an evaluation sample. A detector's flags become one decision per sample:
the sample is *flagged* when at least ``persistence`` (default 0.25) of its ACTIVE samples are flagged. That is a
share of active time, not a continuous duration: in a fully active hour it is 15 minutes, in an hour active for
only half its duration it is 7.5 minutes. Ground truth comes from the dataset inventory: every sample of a faulted
file is a fault sample, every sample of the fault-free file is normal. :func:`window_coverage` reports the
observed, active, expected and flagged counts and the eligibility of every window, including the excluded ones.

- TPR = flagged fault samples / fault samples
- FPR = flagged normal samples / normal samples
- detection delay = time from the first evaluated fault sample to the first flagged one (the LBNL SDAHU faults
  are present for the whole year, so the delay also reflects the season in which a fault shows).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

DEFAULT_WINDOW = "1h"
DEFAULT_PERSISTENCE = 0.25
DEFAULT_MIN_ACTIVE = 0.5


DEFAULT_CADENCE = "5min"  # used only when the cadence can't be inferred (fewer than two distinct timestamps)


def infer_cadence(index: pd.DatetimeIndex, default: str = DEFAULT_CADENCE) -> pd.Timedelta:
    """Median spacing of the distinct sorted timestamps, else ``default``."""
    uniq = pd.DatetimeIndex(index).unique().sort_values()
    if len(uniq) < 2:
        return pd.Timedelta(default)
    step = pd.Series(uniq[1:] - uniq[:-1]).median()
    return step if step > pd.Timedelta(0) else pd.Timedelta(default)


def window_coverage(
    flags: pd.Series,
    active: pd.Series,
    *,
    window: str = DEFAULT_WINDOW,
    persistence: float = DEFAULT_PERSISTENCE,
    min_active: float = DEFAULT_MIN_ACTIVE,
    cadence: str | pd.Timedelta | None = None,
) -> pd.DataFrame:
    """Per window: ``observed``, ``active``, ``flagged`` sample counts, ``expected`` samples (window / cadence),
    ``active_coverage`` (active / expected, capped at 1), ``eligible`` and ``decision`` (null when not eligible).

    Duplicate timestamps count once (the last value wins). Only windows containing at least one sample appear;
    a window with no samples at all is not observed and has no row."""
    flags = flags[~flags.index.duplicated(keep="last")]
    active = active[~active.index.duplicated(keep="last")]
    active = active.reindex(flags.index).fillna(False).astype(bool)
    flagged = flags.fillna(False).astype(bool) & active
    step = pd.Timedelta(cadence) if cadence is not None else infer_cadence(flags.index)
    expected = max(pd.Timedelta(window) / step, 1.0)
    grouped = pd.DataFrame({"observed": 1.0, "active": active.astype(float), "flagged": flagged.astype(float)},
                           index=flags.index)
    sums = grouped.resample(window).sum()
    sums = sums[sums["observed"] > 0]
    out = sums.astype(int)
    out["expected"] = float(expected)
    out["active_coverage"] = (sums["active"] / expected).clip(upper=1.0)
    out["eligible"] = out["active_coverage"] >= float(min_active)
    share = sums["flagged"] / sums["active"].where(sums["active"] > 0)
    out["decision"] = share.fillna(0.0).ge(float(persistence)).where(out["eligible"])
    return out


def window_decisions(
    flags: pd.Series,
    active: pd.Series,
    *,
    window: str = DEFAULT_WINDOW,
    persistence: float = DEFAULT_PERSISTENCE,
    min_active: float = DEFAULT_MIN_ACTIVE,
    cadence: str | pd.Timedelta | None = None,
) -> pd.Series:
    """One boolean per evaluation window active for at least ``min_active`` of its elapsed time.

    ``flags`` and ``active`` are boolean series on the same index. Ineligible windows are dropped here; use
    :func:`window_coverage` to see them and why."""
    cov = window_coverage(flags, active, window=window, persistence=persistence, min_active=min_active,
                          cadence=cadence)
    return cov.loc[cov["eligible"], "decision"].astype(bool)


@dataclass
class Score:
    method: str
    fault_file: str
    samples: int
    flagged: int
    rate: float  # TPR for a fault file, FPR for the fault-free file
    delay_h: float | None  # fault files only; None when never detected

    def to_dict(self) -> dict:
        return asdict(self)


def score_file(method: str, fault_file: str, decisions: pd.Series, *, is_fault: bool) -> Score:
    n = int(decisions.size)
    k = int(decisions.sum())
    rate = float(k / n) if n else float("nan")
    delay = None
    if is_fault and k:
        first = decisions.index[0]
        hit = decisions[decisions].index[0]
        delay = float((hit - first) / pd.Timedelta(hours=1))
    return Score(method, fault_file, n, k, rate, delay)


def rates(decisions_fault: pd.Series, decisions_normal: pd.Series) -> tuple[float, float]:
    """``(TPR, FPR)`` from window decisions on a faulted run and on the fault-free run."""
    tpr = float(decisions_fault.mean()) if decisions_fault.size else float("nan")
    fpr = float(decisions_normal.mean()) if decisions_normal.size else float("nan")
    return tpr, fpr


def split_weeks(index: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic train / test split by ISO week: odd weeks train, even weeks test (both seasons in each)."""
    week = index.isocalendar().week.to_numpy() if hasattr(index, "isocalendar") else None
    if week is None:
        week = pd.Index(index).isocalendar().week.to_numpy()
    week = np.asarray(week, dtype=int)
    train = (week % 2) == 1
    return train, ~train
