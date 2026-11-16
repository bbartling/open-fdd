"""ML / statistical FDD detectors for AHU role frames (SI, Haystack role columns).

Every detector follows the same small interface::

    det = make_detector("pca")          # pca | grey_box | ocsvm | copod | zscore | mad
    det.fit(normal_frame)               # rows believed fault-free (ignored by zscore / mad)
    flags = det.flags(frame)            # boolean Series on frame.index (False where not active)

Detectors only look at *active* rows (supply fan proven on and, when the role exists, occupied); see
:func:`active_mask`. Thresholds are set from the training rows only (default: the 99th percentile of the
normal score, i.e. about 1 % of normal 5-minute samples flagged before any persistence filter).

- ``pca``: PCA + squared prediction error (SPE / Q statistic) with per-role contributions (Wang & Xiao 2004).
- ``grey_box``: physics residuals: the mixed-air balance (outdoor-air fraction vs damper command), the cooling
  coil air-side delta-T vs valve command, and SAT minus setpoint while the valve is modulating.
- ``ocsvm``: one-class SVM per operating mode (scikit-learn). ``copod``: COPOD per mode (``pyod``, optional).
- ``zscore`` / ``mad``: the existing ``open_fdd.analytics.anomaly`` rolling detectors over each role (a sample is
  flagged when any role is), one day of samples per window, no training.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

#: Roles the multivariate detectors use when present (setpoints excluded: often constant).
FEATURE_ROLES: tuple[str, ...] = (
    "discharge-air-temp",
    "mixed-air-temp",
    "return-air-temp",
    "outside-air-temp",
    "outside-air-damper",
    "cooling-valve",
    "fan-cmd",
    "duct-static-pressure",
)

#: Short role names (sql/fdd/role_map.json keys) accepted as aliases.
ROLE_ALIASES: dict[str, str] = {
    "sat": "discharge-air-temp",
    "sat_sp": "discharge-air-temp-sp",
    "mat": "mixed-air-temp",
    "rat": "return-air-temp",
    "oa_t": "outside-air-temp",
    "oa_damper_pct": "outside-air-damper",
    "clg_valve_pct": "cooling-valve",
    "htg_valve_pct": "heating-valve",
    "fan_cmd": "fan-cmd",
    "fan_status": "fan-status",
    "duct_static": "duct-static-pressure",
    "duct_static_sp": "duct-static-pressure-sp",
    "occ_mode": "occupied",
}

METHODS: tuple[str, ...] = ("pca", "grey_box", "ocsvm", "copod", "zscore", "mad")
DEFAULT_QUANTILE = 0.99


def canonical_roles(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename short role aliases (``sat``, ``mat`` ...) to the Haystack role names used here."""
    renamed = frame.rename(columns={k: v for k, v in ROLE_ALIASES.items() if k in frame.columns and v not in frame.columns})
    renamed.attrs = dict(frame.attrs)
    return renamed


def active_mask(frame: pd.DataFrame) -> pd.Series:
    """Rows where the unit runs: ``fan-status`` > 0.5 (else ``fan-cmd`` > 0.05), and ``occupied`` > 0.5 if present."""
    if "fan-status" in frame.columns:
        on = pd.to_numeric(frame["fan-status"], errors="coerce") > 0.5
    elif "fan-cmd" in frame.columns:
        on = pd.to_numeric(frame["fan-cmd"], errors="coerce") > 0.05
    else:
        on = pd.Series(True, index=frame.index)
    if "occupied" in frame.columns:
        occ = pd.to_numeric(frame["occupied"], errors="coerce")
        if occ.notna().any():
            on &= occ > 0.5
    return on.fillna(False).astype(bool)


def _features(frame: pd.DataFrame, roles: list[str]) -> pd.DataFrame:
    return frame.reindex(columns=roles).apply(pd.to_numeric, errors="coerce").astype(float)


class Detector:
    name = "base"
    needs_training = True

    def fit(self, normal: pd.DataFrame) -> "Detector":
        return self

    def scores(self, frame: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def flags(self, frame: pd.DataFrame) -> pd.Series:
        raise NotImplementedError


@dataclass
class PCASPE(Detector):
    """PCA on standardized roles; flag when SPE exceeds the training quantile."""

    variance: float = 0.90
    quantile: float = DEFAULT_QUANTILE
    feature_roles: tuple[str, ...] = FEATURE_ROLES
    roles: list[str] = field(default_factory=list)
    mean_: np.ndarray | None = None
    std_: np.ndarray | None = None
    loadings_: np.ndarray | None = None
    threshold_: float = float("nan")
    name: str = "pca"

    def fit(self, normal: pd.DataFrame) -> "PCASPE":
        normal = canonical_roles(normal)
        rows = normal[active_mask(normal)]
        candidates = [r for r in self.feature_roles if r in rows.columns]
        x = _features(rows, candidates).dropna()
        std = x.std(ddof=0)
        self.roles = [r for r in candidates if float(std.get(r, 0.0)) > 1e-9]
        if len(self.roles) < 2 or len(x) < 10:
            raise ValueError("PCA needs at least two non-constant feature roles and ten active rows")
        x = x[self.roles].to_numpy()
        self.mean_ = x.mean(axis=0)
        self.std_ = x.std(axis=0)
        z = (x - self.mean_) / self.std_
        _, s, vt = np.linalg.svd(z, full_matrices=False)
        explained = np.cumsum(s**2) / np.sum(s**2)
        k = int(np.searchsorted(explained, self.variance) + 1)
        k = max(1, min(k, len(self.roles) - 1))
        self.loadings_ = vt[:k].T
        self.threshold_ = float(np.quantile(self._spe(z), self.quantile))
        return self

    def _residual(self, z: np.ndarray) -> np.ndarray:
        assert self.loadings_ is not None
        return z - z @ self.loadings_ @ self.loadings_.T

    def _spe(self, z: np.ndarray) -> np.ndarray:
        return np.sum(self._residual(z) ** 2, axis=1)

    def _z(self, frame: pd.DataFrame) -> pd.DataFrame:
        x = _features(canonical_roles(frame), self.roles)
        return (x - self.mean_) / self.std_

    def scores(self, frame: pd.DataFrame) -> pd.Series:
        z = self._z(frame)
        ok = z.notna().all(axis=1)
        out = pd.Series(np.nan, index=frame.index)
        out[ok] = self._spe(z[ok].to_numpy())
        return out

    def contributions(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Per-role share of SPE (rows sum to 1): which roles drove the alarm."""
        z = self._z(frame)
        ok = z.notna().all(axis=1)
        out = pd.DataFrame(np.nan, index=frame.index, columns=self.roles)
        if ok.any():
            r2 = self._residual(z[ok].to_numpy()) ** 2
            total = r2.sum(axis=1, keepdims=True)
            total[total == 0] = 1.0
            out.loc[ok] = r2 / total
        return out

    def flags(self, frame: pd.DataFrame) -> pd.Series:
        s = self.scores(frame)
        return (s > self.threshold_).fillna(False) & active_mask(canonical_roles(frame))


def _binned_median(x: pd.Series, y: pd.Series, width: float) -> pd.Series:
    bins = (x / width).round().astype("Int64")
    table = y.groupby(bins).median()
    counts = y.groupby(bins).size()
    return table[counts >= 20]


def _lookup(table: pd.Series, x: pd.Series, width: float) -> pd.Series:
    bins = (x / width).round().astype("Int64")
    return bins.map(table).astype(float)


@dataclass
class GreyBox(Detector):
    """Physics residuals against expectations learned from normal data (binned medians)."""

    quantile: float = DEFAULT_QUANTILE
    min_oat_rat_delta: float = 2.0
    bin_width: float = 0.05
    tables_: dict[str, pd.Series] = field(default_factory=dict)
    centers_: dict[str, float] = field(default_factory=dict)
    thresholds_: dict[str, float] = field(default_factory=dict)
    name: str = "grey_box"

    def _raw(self, frame: pd.DataFrame) -> dict[str, tuple[pd.Series, pd.Series, float]]:
        """``{residual: (driver x, measured y, bin width)}`` for each residual the roles allow."""
        f = canonical_roles(frame)
        num = lambda r: pd.to_numeric(f[r], errors="coerce").astype(float)  # noqa: E731
        out: dict[str, tuple[pd.Series, pd.Series, float]] = {}
        if {"mixed-air-temp", "return-air-temp", "outside-air-temp", "outside-air-damper"} <= set(f.columns):
            mat, rat, oat = num("mixed-air-temp"), num("return-air-temp"), num("outside-air-temp")
            delta = oat - rat
            oaf = ((mat - rat) / delta).where(delta.abs() >= self.min_oat_rat_delta)
            out["oa_fraction"] = (num("outside-air-damper"), oaf, self.bin_width)
        if {"mixed-air-temp", "discharge-air-temp", "cooling-valve"} <= set(f.columns):
            out["coil_delta_t"] = (num("cooling-valve"), num("mixed-air-temp") - num("discharge-air-temp"), self.bin_width)
        if {"discharge-air-temp", "discharge-air-temp-sp", "cooling-valve"} <= set(f.columns):
            valve = num("cooling-valve")
            err = (num("discharge-air-temp") - num("discharge-air-temp-sp")).where((valve > 0.05) & (valve < 0.95))
            out["sat_error"] = (pd.Series(0.0, index=f.index), err, 1.0)
        return out

    def fit(self, normal: pd.DataFrame) -> "GreyBox":
        rows = normal[active_mask(canonical_roles(normal))]
        raw = self._raw(rows)
        if not raw:
            raise ValueError("grey_box needs MAT/RAT/OAT/damper or MAT/SAT/cooling valve roles")
        for key, (x, y, width) in raw.items():
            ok = x.notna() & y.notna()
            table = _binned_median(x[ok], y[ok], width)
            resid = y[ok] - _lookup(table, x[ok], width)
            resid = resid.dropna()
            if resid.empty:
                continue
            self.tables_[key] = table
            self.centers_[key] = float(resid.median())
            self.thresholds_[key] = float(np.quantile((resid - self.centers_[key]).abs(), self.quantile))
        if not self.thresholds_:
            raise ValueError("gray-box learned no residual: needs the mixed-air / coil roles and enough active "
                             "rows per bin on known-good data")
        return self

    def residuals(self, frame: pd.DataFrame) -> pd.DataFrame:
        raw = self._raw(frame)
        cols = {}
        for key, table in self.tables_.items():
            if key not in raw:
                continue
            x, y, width = raw[key]
            cols[key] = y - _lookup(table, x, width) - self.centers_[key]
        return pd.DataFrame(cols, index=frame.index)

    def scores(self, frame: pd.DataFrame) -> pd.Series:
        r = self.residuals(frame)
        ratios = pd.DataFrame({k: r[k].abs() / max(self.thresholds_[k], 1e-9) for k in r.columns}, index=frame.index)
        return ratios.max(axis=1, skipna=True)

    def flags(self, frame: pd.DataFrame) -> pd.Series:
        return (self.scores(frame) > 1.0).fillna(False) & active_mask(canonical_roles(frame))


def operating_mode(frame: pd.DataFrame) -> pd.Series:
    """AHU operating mode from the damper and cooling valve commands (fraction 0-1)."""
    f = canonical_roles(frame)
    valve = pd.to_numeric(f.get("cooling-valve", pd.Series(0.0, index=f.index)), errors="coerce").fillna(0.0)
    damper = pd.to_numeric(f.get("outside-air-damper", pd.Series(0.0, index=f.index)), errors="coerce").fillna(0.0)
    mode = pd.Series("min_oa", index=f.index, dtype=object)
    mode[(valve <= 0.05) & (damper > 0.15)] = "econ_only"
    mode[(valve > 0.05) & (damper < 0.5)] = "mech_min_oa"
    mode[(valve > 0.05) & (damper >= 0.5)] = "econ_mech"
    return mode


@dataclass
class ModeGated(Detector):
    """One novelty model per operating mode, trained on (a seeded subsample of) normal rows of that mode."""

    kind: str = "ocsvm"  # ocsvm | copod
    nu: float = 0.01
    max_train: int = 4000
    seed: int = 0
    feature_roles: tuple[str, ...] = FEATURE_ROLES
    roles: list[str] = field(default_factory=list)
    models_: dict[str, object] = field(default_factory=dict)
    mode_columns_: dict[str, list[int]] = field(default_factory=dict)
    name: str = "ocsvm"

    def __post_init__(self) -> None:
        self.name = self.kind

    def _model(self):
        if self.kind == "ocsvm":
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
            from sklearn.svm import OneClassSVM

            return make_pipeline(StandardScaler(), OneClassSVM(nu=self.nu, gamma="scale"))
        if self.kind == "copod":
            from pyod.models.copod import COPOD

            return COPOD(contamination=self.nu)
        raise ValueError(f"unknown mode-gated model {self.kind!r}")

    def fit(self, normal: pd.DataFrame) -> "ModeGated":
        normal = canonical_roles(normal)
        rows = normal[active_mask(normal)]
        candidates = [r for r in self.feature_roles if r in rows.columns]
        x = _features(rows, candidates).dropna()
        std = x.std(ddof=0)
        self.roles = [r for r in candidates if float(std.get(r, 0.0)) > 1e-9]
        if len(self.roles) < 2:
            raise ValueError(f"{self.kind} needs at least two non-constant feature roles")
        x = x[self.roles]
        modes = operating_mode(rows.loc[x.index])
        rng = np.random.default_rng(self.seed)
        for mode in sorted(modes.unique()):
            part = x[modes == mode]
            if len(part) < 50:
                continue
            if len(part) > self.max_train:
                part = part.iloc[np.sort(rng.choice(len(part), self.max_train, replace=False))]
            # a role held constant in this mode (e.g. the damper at minimum) carries no information; COPOD's
            # skewness of a constant column is undefined, so drop such roles per mode
            spread = part.std(ddof=0).to_numpy()
            cols = [i for i, sd in enumerate(spread) if sd > 1e-9] if self.kind == "copod" else list(range(part.shape[1]))
            if len(cols) < 1:
                continue
            model = self._model()
            model.fit(part.to_numpy()[:, cols])
            self.models_[mode] = model
            self.mode_columns_[mode] = cols
        if not self.models_:
            raise ValueError(f"{self.kind}: no operating mode had 50 normal rows")
        return self

    def flags(self, frame: pd.DataFrame) -> pd.Series:
        frame = canonical_roles(frame)
        act = active_mask(frame)
        x = _features(frame, self.roles)
        ok = act & x.notna().all(axis=1)
        modes = operating_mode(frame)
        out = pd.Series(False, index=frame.index)
        for mode, model in self.models_.items():
            sel = ok & (modes == mode)
            if not sel.any():
                continue
            values = x[sel].to_numpy()[:, self.mode_columns_.get(mode, list(range(len(self.roles))))]
            if self.kind == "ocsvm":
                out[sel] = model.predict(values) < 0  # type: ignore[attr-defined]
            else:
                out[sel] = model.predict(values) == 1  # type: ignore[attr-defined]
        return out

    def scores(self, frame: pd.DataFrame) -> pd.Series:
        return self.flags(frame).astype(float)


@dataclass
class RollingAnomaly(Detector):
    """Existing rolling z-score / MAD per role (``open_fdd.analytics.anomaly.detectors``); no training."""

    kind: str = "zscore"
    roles: list[str] = field(default_factory=lambda: list(FEATURE_ROLES))
    needs_training: bool = False
    name: str = "zscore"

    def __post_init__(self) -> None:
        self.name = self.kind

    def flags(self, frame: pd.DataFrame) -> pd.Series:
        from open_fdd.analytics.anomaly.detectors import (
            is_binary_like,
            rolling_mad_flags,
            rolling_zscore_flags,
            samples_per_day,
        )

        frame = canonical_roles(frame)
        act = active_mask(frame)
        window = samples_per_day(frame.index)
        out = pd.Series(False, index=frame.index)
        for role in self.roles:
            if role not in frame.columns:
                continue
            series = pd.to_numeric(frame[role], errors="coerce")
            if is_binary_like(series):
                continue
            fn = rolling_zscore_flags if self.kind == "zscore" else rolling_mad_flags
            out |= fn(series, window=window).reindex(frame.index).fillna(False).astype(bool)
        return out & act

    def scores(self, frame: pd.DataFrame) -> pd.Series:
        return self.flags(frame).astype(float)


def copod_available() -> bool:
    try:
        import pyod.models.copod  # noqa: F401
    except Exception:  # noqa: BLE001 - optional dependency
        return False
    return True


def make_detector(method: str, *, seed: int = 0, roles: tuple[str, ...] | None = None) -> Detector:
    """Build a detector by name; ``roles`` restricts the feature roles (default :data:`FEATURE_ROLES`)."""
    method = method.strip().lower().replace("-", "_")
    feats = tuple(roles) if roles else FEATURE_ROLES
    if method in {"pca", "pca_spe"}:
        return PCASPE(feature_roles=feats)
    if method in {"grey_box", "gray_box", "residual"}:
        return GreyBox()
    if method == "ocsvm":
        return ModeGated(kind="ocsvm", seed=seed, feature_roles=feats)
    if method == "copod":
        if not copod_available():
            raise ImportError('COPOD needs pyod: pip install "open-fdd[ml]" pyod')
        return ModeGated(kind="copod", seed=seed, feature_roles=feats)
    if method in {"zscore", "mad"}:
        return RollingAnomaly(kind=method, roles=list(feats))
    raise ValueError(f"unknown method {method!r}; choose from {', '.join(METHODS)}")


def plot_contributions(contrib: pd.DataFrame, flags: pd.Series, path, title: str = "PCA SPE contributions"):
    """Bar chart of the mean SPE share per role over flagged rows (needs matplotlib). Returns ``path``."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sel = contrib[flags.reindex(contrib.index).fillna(False).astype(bool)]
    share = sel.mean().sort_values(ascending=True) if not sel.empty else contrib.mean().sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(6, 0.4 * len(share) + 1.2))
    ax.barh(share.index, share.to_numpy() * 100.0)
    ax.set_xlabel("mean share of SPE on flagged samples (%)")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
