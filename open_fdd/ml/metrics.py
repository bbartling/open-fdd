"""Detection metrics in the style of the LBNL / NREL FDD evaluation framework (Frank, Lin, Granderson et al. 2019).

An *evaluation sample* is a fixed window (default one hour) in which the unit was operating. A detector's
5-minute flags become one decision per sample: the sample is *flagged* when at least ``persistence`` of its
active points are flagged (default 0.25, i.e. 15 minutes in an hour). Ground truth comes from the dataset
inventory: every sample of a faulted file is a fault sample, every sample of the fault-free file is normal.

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


def window_decisions(
    flags: pd.Series,
    active: pd.Series,
    *,
    window: str = DEFAULT_WINDOW,
    persistence: float = DEFAULT_PERSISTENCE,
    min_active: float = DEFAULT_MIN_ACTIVE,
) -> pd.Series:
    """One boolean per evaluation window that is active for at least ``min_active`` of its points.

    ``flags`` and ``active`` are boolean series on the same index. Windows below ``min_active`` are dropped.
    """
    active = active.reindex(flags.index).fillna(False).astype(bool)
    flagged = flags.fillna(False).astype(bool) & active
    grouped = pd.DataFrame({"active": active.astype(float), "flagged": flagged.astype(float)})
    sums = grouped.resample(window).sum()
    counts = grouped["active"].resample(window).count()
    keep = (counts > 0) & (sums["active"] >= float(min_active) * counts)
    sums = sums[keep]
    share = sums["flagged"] / sums["active"].where(sums["active"] > 0)
    return share.fillna(0.0).ge(float(persistence))


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
