"""IPMVP-style change-point (piecewise-linear) baseline models.

Clean-room Inverse Modeling Toolkit shapes used for Option C M&V oracles:

* ``2P`` — linear: ``Y = a + b·X``
* ``3PH`` — heating: ``Y = a + b·(β − X)+``
* ``3PC`` — cooling: ``Y = a + b·(X − β)+``
* ``4P`` — dual slope, one change-point
* ``5P`` — dual slope, two change-points

Requires ``numpy`` (``pip install "open-fdd[oracle]"`` / ``[analytics]``).
Not a product DataFusion path — PyPI oracle / ECM tooling only.

External algorithm reference: Camber (Apache-2.0) — do not vendor into GHCR.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Sequence

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - exercised when bare install
    raise ImportError(
        "open_fdd.ecm_engineering.changepoint requires numpy; "
        'install with pip install "open-fdd[oracle]" or "open-fdd[analytics]"'
    ) from exc

from open_fdd.ecm_engineering.g14 import cvrmse_pct, nmbe_pct, score_g14

ModelKind = Literal["2P", "3PH", "3PC", "4P", "5P"]

_ALL_MODELS: tuple[ModelKind, ...] = ("2P", "3PH", "3PC", "4P", "5P")


@dataclass(frozen=True)
class ChangePointModel:
    """Fitted piecewise-linear energy vs independent-variable model."""

    kind: ModelKind
    intercept: float
    slope_heat: float
    slope_cool: float
    change_point: float
    change_point_cool: float | None
    n: int
    n_params: int
    r_squared: float
    rmse: float
    nmbe_pct: float
    cvrmse_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def predict(self, x: Sequence[float] | np.ndarray) -> np.ndarray:
        return predict_changepoint(self, x)


def _finite_xy(
    x: Sequence[float] | np.ndarray,
    y: Sequence[float] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    xa = np.asarray(x, dtype=float).ravel()
    ya = np.asarray(y, dtype=float).ravel()
    if xa.shape != ya.shape:
        raise ValueError("x and y must have the same shape")
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa = xa[mask]
    ya = ya[mask]
    if xa.size < 3:
        raise ValueError("need at least 3 finite (x, y) pairs")
    return xa, ya


def _design(
    kind: ModelKind,
    x: np.ndarray,
    *,
    bp: float,
    bp_cool: float | None = None,
) -> np.ndarray:
    ones = np.ones(x.shape[0], dtype=float)
    heat = np.maximum(bp - x, 0.0)
    cool_bp = bp if bp_cool is None else bp_cool
    cool = np.maximum(x - cool_bp, 0.0)
    if kind == "2P":
        return np.column_stack([ones, x])
    if kind == "3PH":
        return np.column_stack([ones, heat])
    if kind == "3PC":
        return np.column_stack([ones, cool])
    if kind == "4P":
        return np.column_stack([ones, heat, cool])
    if kind == "5P":
        if bp_cool is None:
            raise ValueError("5P requires bp_cool")
        return np.column_stack([ones, heat, cool])
    raise ValueError(f"unknown model kind: {kind}")


def _n_params(kind: ModelKind) -> int:
    return {"2P": 2, "3PH": 3, "3PC": 3, "4P": 4, "5P": 5}[kind]


def _lstsq(a: np.ndarray, y: np.ndarray) -> np.ndarray | None:
    if a.shape[0] < a.shape[1]:
        return None
    try:
        coef, _, rank, _ = np.linalg.lstsq(a, y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if rank < a.shape[1]:
        return None
    if not np.all(np.isfinite(coef)):
        return None
    return coef


def _metrics(y: np.ndarray, yhat: np.ndarray, *, n_params: int) -> tuple[float, float, float, float]:
    resid = y - yhat
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 if ss_tot == 0.0 else 1.0 - ss_res / ss_tot
    rmse = float(np.sqrt(ss_res / max(len(y) - n_params, 1)))
    nmbe = nmbe_pct(y.tolist(), yhat.tolist(), n_params=n_params)
    cvrmse = cvrmse_pct(y.tolist(), yhat.tolist(), n_params=n_params)
    return r2, rmse, nmbe, cvrmse


def _pack(
    kind: ModelKind,
    coef: np.ndarray,
    *,
    bp: float,
    bp_cool: float | None,
    x: np.ndarray,
    y: np.ndarray,
) -> ChangePointModel:
    a = _design(kind, x, bp=bp, bp_cool=bp_cool)
    yhat = a @ coef
    n_params = _n_params(kind)
    r2, rmse, nmbe, cvrmse = _metrics(y, yhat, n_params=n_params)
    intercept = float(coef[0])
    slope_heat = 0.0
    slope_cool = 0.0
    if kind == "2P":
        slope_cool = float(coef[1])
        slope_heat = float(coef[1])
    elif kind == "3PH":
        slope_heat = float(coef[1])
    elif kind == "3PC":
        slope_cool = float(coef[1])
    elif kind in ("4P", "5P"):
        slope_heat = float(coef[1])
        slope_cool = float(coef[2])
    return ChangePointModel(
        kind=kind,
        intercept=intercept,
        slope_heat=slope_heat,
        slope_cool=slope_cool,
        change_point=float(bp),
        change_point_cool=None if bp_cool is None else float(bp_cool),
        n=int(x.size),
        n_params=n_params,
        r_squared=r2,
        rmse=rmse,
        nmbe_pct=nmbe,
        cvrmse_pct=cvrmse,
    )


def _candidate_bps(x: np.ndarray, *, grid: int) -> np.ndarray:
    lo = float(np.min(x))
    hi = float(np.max(x))
    if not (np.isfinite(lo) and np.isfinite(hi) and hi > lo):
        return np.array([lo], dtype=float)
    # Keep interior change-points so both segments have room.
    span = hi - lo
    pad = max(span * 0.05, 1e-6)
    return np.linspace(lo + pad, hi - pad, num=max(int(grid), 3))


def fit_changepoint(
    x: Sequence[float] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    *,
    kind: ModelKind = "3PC",
    grid: int = 25,
) -> ChangePointModel:
    """Fit one change-point model kind by grid-searching the balance point(s)."""
    xa, ya = _finite_xy(x, y)
    if kind == "2P":
        coef = _lstsq(_design("2P", xa, bp=0.0), ya)
        if coef is None:
            raise ValueError("2P least-squares failed")
        mid = float(np.median(xa))
        return _pack("2P", coef, bp=mid, bp_cool=None, x=xa, y=ya)

    bps = _candidate_bps(xa, grid=grid)
    best: ChangePointModel | None = None

    if kind == "5P":
        for bp_h in bps:
            cool_cands = bps[bps >= bp_h]
            if cool_cands.size == 0:
                continue
            for bp_c in cool_cands:
                coef = _lstsq(_design("5P", xa, bp=float(bp_h), bp_cool=float(bp_c)), ya)
                if coef is None:
                    continue
                model = _pack("5P", coef, bp=float(bp_h), bp_cool=float(bp_c), x=xa, y=ya)
                if best is None or model.cvrmse_pct < best.cvrmse_pct:
                    best = model
    else:
        for bp in bps:
            coef = _lstsq(_design(kind, xa, bp=float(bp)), ya)
            if coef is None:
                continue
            model = _pack(kind, coef, bp=float(bp), bp_cool=None, x=xa, y=ya)
            if best is None or model.cvrmse_pct < best.cvrmse_pct:
                best = model

    if best is None:
        raise ValueError(f"could not fit change-point model {kind}")
    return best


def select_changepoint(
    x: Sequence[float] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    *,
    kinds: Sequence[ModelKind] | None = None,
    grid: int = 25,
) -> ChangePointModel:
    """Fit candidate kinds and return the lowest-CVRMSE model."""
    chosen = tuple(kinds) if kinds is not None else _ALL_MODELS
    best: ChangePointModel | None = None
    errors: list[str] = []
    for kind in chosen:
        try:
            model = fit_changepoint(x, y, kind=kind, grid=grid)
        except ValueError as exc:
            errors.append(f"{kind}: {exc}")
            continue
        if best is None or model.cvrmse_pct < best.cvrmse_pct:
            best = model
    if best is None:
        raise ValueError("no change-point model fitted: " + "; ".join(errors))
    return best


def predict_changepoint(
    model: ChangePointModel,
    x: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Predict energy from an independent-variable series."""
    xa = np.asarray(x, dtype=float).ravel()
    bp = model.change_point
    bp_c = model.change_point_cool
    if model.kind == "2P":
        return model.intercept + model.slope_cool * xa
    if model.kind == "3PH":
        return model.intercept + model.slope_heat * np.maximum(bp - xa, 0.0)
    if model.kind == "3PC":
        return model.intercept + model.slope_cool * np.maximum(xa - bp, 0.0)
    if model.kind == "4P":
        return (
            model.intercept
            + model.slope_heat * np.maximum(bp - xa, 0.0)
            + model.slope_cool * np.maximum(xa - bp, 0.0)
        )
    if model.kind == "5P":
        cool_bp = bp if bp_c is None else bp_c
        return (
            model.intercept
            + model.slope_heat * np.maximum(bp - xa, 0.0)
            + model.slope_cool * np.maximum(xa - cool_bp, 0.0)
        )
    raise ValueError(f"unknown model kind: {model.kind}")


def option_c_savings(
    baseline: ChangePointModel,
    *,
    reporting_x: Sequence[float] | np.ndarray,
    reporting_y: Sequence[float] | np.ndarray,
) -> dict[str, Any]:
    """IPMVP Option C avoided energy: baseline(pred) − reporting actual.

    Positive ``savings`` means reporting-period energy is below the baseline
    model prediction at the same independent-variable values.
    """
    xa, ya = _finite_xy(reporting_x, reporting_y)
    yhat = predict_changepoint(baseline, xa)
    savings = yhat - ya
    total_pred = float(np.sum(yhat))
    total_act = float(np.sum(ya))
    total_sav = float(np.sum(savings))
    g14 = score_g14(ya.tolist(), yhat.tolist(), granularity="monthly", n_params=baseline.n_params)
    return {
        "baseline_kind": baseline.kind,
        "n": int(xa.size),
        "predicted_total": total_pred,
        "actual_total": total_act,
        "savings_total": total_sav,
        "savings_fraction": (total_sav / total_pred) if total_pred else None,
        "reporting_vs_baseline_g14": g14.to_dict(),
        "per_period_savings": savings.tolist(),
    }
