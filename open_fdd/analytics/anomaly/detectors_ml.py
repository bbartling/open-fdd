"""Python-only detectors. Import sklearn / statsmodels lazily.

These methods stay offline Python. They are not part of the SQL-portable
Z-score / MAD surface. Install them with ``pip install "open-fdd[anomaly]"``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# MAD multiples on the STL residual. robust=False keeps that MAD on the scale of
# ordinary samples; robust=True collapses it and flags routine noise.
STL_THRESHOLD = 6.0
IFOREST_CONTAMINATION = 0.01
_EXTRA = "pip install 'open-fdd[anomaly]'"


def _load_stl():
    try:
        from statsmodels.tsa.seasonal import STL
    except ImportError as exc:
        raise ImportError(f"STL residual screening requires optional extra: {_EXTRA}") from exc
    return STL


def _load_isolation_forest():
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError as exc:
        raise ImportError(
            f"Isolation Forest screening requires optional extra: {_EXTRA}"
        ) from exc
    return IsolationForest


def stl_residual_flags(
    y: pd.Series,
    *,
    period: int,
    threshold: float = STL_THRESHOLD,
) -> pd.Series:
    """Flag STL residuals beyond a robust MAD threshold.

    Series shorter than two seasonal periods, or constant series, return all
    False instead of raising.
    """
    values = pd.to_numeric(y, errors="coerce")
    flags = pd.Series(False, index=values.index)
    period = int(period)
    finite = values.dropna()
    if period < 2 or len(finite) < 2 * period or int(finite.nunique()) <= 1:
        return flags

    stl_cls = _load_stl()
    filled = values.interpolate(limit_direction="both")
    if filled.isna().any():
        filled = filled.fillna(float(finite.median()))
    try:
        fit = stl_cls(filled.to_numpy(dtype=float), period=period, robust=False).fit()
    except (ValueError, np.linalg.LinAlgError):
        return flags
    resid = np.asarray(fit.resid, dtype=float)
    center = float(np.nanmedian(resid))
    mad = float(np.nanmedian(np.abs(resid - center)))
    if not np.isfinite(mad) or mad <= 0:
        return flags
    observed = values.notna().to_numpy()
    score = np.abs(resid - center) / mad
    flags = pd.Series(np.isfinite(score) & (score > float(threshold)) & observed, index=values.index)
    return flags.astype(bool)


def isolation_forest_flags(
    y: pd.Series,
    *,
    contamination: float = IFOREST_CONTAMINATION,
    random_state: int = 42,
) -> pd.Series:
    """Flag Isolation Forest outliers on value, short rolling mean/std, and lag-1.

    ``predict == -1`` is an anomaly. Fewer than 10 finite feature rows returns
    all False after the optional dependency has been imported.
    """
    forest_cls = _load_isolation_forest()
    values = pd.to_numeric(y, errors="coerce")
    flags = pd.Series(False, index=values.index)
    short = max(3, min(12, max(len(values) // 10, 1)))
    features = pd.DataFrame(
        {
            "value": values,
            "roll_mean": values.rolling(short, min_periods=1).mean(),
            "roll_std": values.rolling(short, min_periods=1).std(ddof=0).fillna(0.0),
            "lag1": values.shift(1),
        },
        index=values.index,
    )
    features = features.replace([np.inf, -np.inf], np.nan).dropna()
    if len(features) < 10:
        return flags
    rate = float(contamination)
    if not np.isfinite(rate) or rate <= 0 or rate > 0.5:
        raise ValueError("contamination must be in (0, 0.5]")
    model = forest_cls(
        n_estimators=100,
        contamination=rate,
        random_state=int(random_state),
    )
    pred = model.fit_predict(features.to_numpy(dtype=float))
    flags.loc[features.index] = pred == -1
    return flags.astype(bool)
