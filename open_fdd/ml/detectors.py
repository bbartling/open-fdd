"""ML / statistical FDD detectors for AHU role frames (SI, Haystack role columns).

Every detector follows the same small interface::

    det = make_detector("pca")          # pca | grey_box | ocsvm | copod | zscore | mad
    det.fit(normal_frame)               # rows believed fault-free (ignored by zscore / mad)
    flags = det.flags(frame)            # boolean Series on frame.index (False where not active)

Detectors only look at *active* rows (operating proof on and, when the role has data, occupied; rows without
proof are not assessed); see :func:`active_mask`. Thresholds are set from the training rows only (default: the 99th percentile of the
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
    "zone-air-temp",
    "heating-valve",
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
    "zone_t": "zone-air-temp",
    "compressor_status": "compressor-status",
}

METHODS: tuple[str, ...] = ("pca", "grey_box", "ocsvm", "copod", "zscore", "mad")

#: Gray-box residual families: ``{name: (required role sets (one of each tuple), roles that must be absent)}``.
#: The mixed-air families are the AHU ones. ``heat_rise`` / ``cool_drop`` are the single-zone family (furnace,
#: RTU, heat pump): supply minus zone (else return) air temperature against the heating or cooling command. They
#: run only when there is no mixed-air temperature, so an AHU keeps exactly the mixed-air residuals.
GREY_BOX_RESIDUALS: dict[str, tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]] = {
    "oa_fraction": (
        (("mixed-air-temp",), ("return-air-temp",), ("outside-air-temp",), ("outside-air-damper",)),
        (),
    ),
    "coil_delta_t": ((("mixed-air-temp",), ("discharge-air-temp",), ("cooling-valve",)), ()),
    "sat_error": ((("discharge-air-temp",), ("discharge-air-temp-sp",), ("cooling-valve",)), ()),
    "heat_rise": (
        (("discharge-air-temp",), ("zone-air-temp", "return-air-temp"), ("heating-valve",)),
        ("mixed-air-temp",),
    ),
    "cool_drop": (
        (("discharge-air-temp",), ("zone-air-temp", "return-air-temp"), ("cooling-valve", "compressor-status")),
        ("mixed-air-temp",),
    ),
}


def _roles_with_data(frame: pd.DataFrame) -> list[str]:
    """Columns of a role frame that carry at least one numeric value (a mapped but empty role does not count)."""
    return [c for c in frame.columns if pd.to_numeric(frame[c], errors="coerce").notna().any()]


def grey_box_families(columns) -> dict[str, list[str]]:
    """The gray-box residuals a set of role columns allows, with the roles each one would use.

    ``columns`` is a list of role names or a role frame; with a frame only roles that carry data count, so an
    empty ``zone-air-temp`` falls back to a usable ``return-air-temp`` and an empty mixed-air role does not block
    the single-zone families.
    """
    have = set(_roles_with_data(columns)) if isinstance(columns, pd.DataFrame) else set(columns)
    out: dict[str, list[str]] = {}
    for name, (needs, absent) in GREY_BOX_RESIDUALS.items():
        if any(role in have for role in absent):
            continue
        picked = [next((r for r in options if r in have), None) for options in needs]
        if all(picked):
            out[name] = [str(r) for r in picked]
    return out


def _fraction(values: pd.Series) -> pd.Series:
    """A 0-100 % command as a 0-1 fraction (values already in 0-1 are left alone)."""
    finite = values.dropna()
    if not finite.empty and float(finite.max()) > 1.5:
        return values / 100.0
    return values
DEFAULT_QUANTILE = 0.99


def canonical_roles(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename a 223P role or a legacy key onto the pandas column the detectors read.

    ``discharge_air_temperature`` and ``sat`` both become ``discharge-air-temp``. A column that is already
    that pandas name is left as it is. The rule-input name is :func:`open_fdd.point_roles.resolve`.
    """
    from open_fdd.point_roles import pandas_column

    mapping: dict[str, str] = {}
    taken = set(frame.columns)
    for col in frame.columns:
        target = pandas_column(str(col))
        if target != col and target not in taken:
            mapping[col] = target
            taken.add(target)
    renamed = frame.rename(columns=mapping)
    renamed.attrs = dict(frame.attrs)
    return renamed


def active_mask(frame: pd.DataFrame) -> pd.Series:
    """Rows the shared activity policy assesses (:mod:`open_fdd.analytics.anomaly.activity`, ``proof``).

    Proof is the run-proof contract (``open_fdd.run_proof.derive_run_proof``): a resolved ``run-proof`` column,
    else an own status role (``fan-status`` first), else an own command (``fan-cmd`` first), each ``> 0.05``;
    ``occupied`` must be ``> 0.5`` when it has data.
    Rows without proof are not assessed: a frame with no proof role has no active rows.
    """
    from open_fdd.analytics.anomaly.activity import activity_mask

    return activity_mask(canonical_roles(frame), policy="proof")


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
        # a mapped role with no active data (all NaN) would empty the joint dropna; leave it out
        with_data = set(_roles_with_data(rows))
        candidates = [r for r in self.feature_roles if r in with_data]
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

    def assessment(self, frame: pd.DataFrame) -> pd.Series:
        """Per row: ``"assessed"``, ``"inactive"`` or ``"missing_inputs"`` (a fitted role is absent or NaN) (#1666).

        A row that is not assessed carries no flag; this says why, so "no flag" is never read as "healthy"."""
        if self.loadings_ is None:
            raise RuntimeError("pca is not fitted: call fit() on known-good data first")
        return _assessment(self.scores(frame), active_mask(canonical_roles(frame)))

    def assessed_mask(self, frame: pd.DataFrame) -> pd.Series:
        return self.assessment(frame) == "assessed"

    def missing_roles(self, frame: pd.DataFrame) -> list[str]:
        """Fitted roles the frame does not have at all."""
        cols = set(canonical_roles(frame).columns)
        return [r for r in self.roles if r not in cols]


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
    families_: dict[str, list[str]] = field(default_factory=dict)
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
        # scoring uses the single-zone roles picked at fit time; fitting picks the roles that carry data
        families = self.families_ if self.families_ else grey_box_families(f)
        if "heat_rise" in families:
            sat, ref, cmd = families["heat_rise"]
            out["heat_rise"] = (_fraction(num(cmd)), num(sat) - num(ref), self.bin_width)
        if "cool_drop" in families:
            sat, ref, cmd = families["cool_drop"]
            out["cool_drop"] = (_fraction(num(cmd)), num(ref) - num(sat), self.bin_width)
        return out

    def fit(self, normal: pd.DataFrame) -> "GreyBox":
        self.tables_, self.centers_, self.thresholds_ = {}, {}, {}  # a refit never keeps an earlier baseline
        self.families_ = {}
        rows = normal[active_mask(canonical_roles(normal))]
        raw = self._raw(rows)
        if not raw:
            raise ValueError(
                "grey_box needs one residual family: MAT/RAT/OAT/damper, MAT/SAT/cooling valve, SAT/SAT setpoint/"
                "cooling valve, or (no MAT) SAT + zone or return temp + heating valve, or + cooling valve or "
                "compressor status; see `open-fdd-ml methods FOLDER`"
            )
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
        picked = grey_box_families(canonical_roles(rows))
        self.families_ = {k: v for k, v in picked.items() if k in self.thresholds_ and k in ("heat_rise", "cool_drop")}
        if not self.thresholds_:
            raise ValueError("gray-box learned no residual: needs the mixed-air / coil roles and enough active "
                             "rows per bin on known-good data")
        return self

    def residuals(self, frame: pd.DataFrame) -> pd.DataFrame:
        if not self.thresholds_:  # never fitted, or the last fit failed: never report "no faults" silently
            raise RuntimeError("grey_box is not fitted: call fit() on known-good data first")
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

    def assessment(self, frame: pd.DataFrame) -> pd.Series:
        """Per row: ``"assessed"`` (at least one trained residual computed), ``"inactive"``, ``"missing_inputs"``
        (no trained residual's input roles are in the frame) or ``"no_residual"`` (inputs present, but every residual is
        NaN on that row: a missing sample, or outside its validity range such as |OAT - RAT| < 2 K or a saturated
        valve). A fitted model scored on a frame lacking every trained residual's inputs is unassessed, not
        fault-free (#1666)."""
        out = _assessment(self.scores(frame), active_mask(canonical_roles(frame)))
        if len(self.missing_residuals(frame)) < len(self.tables_):
            out[out == "missing_inputs"] = "no_residual"
        return out

    def assessed_mask(self, frame: pd.DataFrame) -> pd.Series:
        return self.assessment(frame) == "assessed"

    def missing_residuals(self, frame: pd.DataFrame) -> list[str]:
        """Trained residual families the frame cannot compute at all (their input roles are absent)."""
        if not self.thresholds_:
            raise RuntimeError("grey_box is not fitted: call fit() on known-good data first")
        available = set(self._raw(frame))
        return [k for k in self.tables_ if k not in available]


def _assessment(scores: pd.Series, active: pd.Series) -> pd.Series:
    out = pd.Series("assessed", index=scores.index, dtype=object)
    out[scores.isna().to_numpy()] = "missing_inputs"
    out[~active.reindex(scores.index).fillna(False).astype(bool).to_numpy()] = "inactive"
    return out


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
    # Fit provenance. ``fit_revision_`` counts successful fits of this instance; ``fit_receipt_`` says which
    # revision owns every fitted mode and why any mode was left out. A failed fit leaves the instance unfitted.
    fit_revision_: int = 0
    fit_receipt_: dict = field(default_factory=dict)
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

    def _reset_fit(self) -> None:
        self.roles, self.models_, self.mode_columns_, self.fit_receipt_ = [], {}, {}, {}

    @property
    def is_fitted(self) -> bool:
        return bool(self.models_)

    def fit(self, normal: pd.DataFrame) -> "ModeGated":
        """Fit one model per operating mode. A refit replaces the whole baseline (every mode model, feature-role
        selection and per-mode column choice); a mode absent from the new fit is unsupported, never served by an
        earlier fit. A failed fit leaves the instance unfitted so scoring raises instead of reporting no faults."""
        self._reset_fit()
        normal = canonical_roles(normal)
        rows = normal[active_mask(normal)]
        # a mapped role with no active data (all NaN) would empty the joint dropna; leave it out
        with_data = set(_roles_with_data(rows))
        candidates = [r for r in self.feature_roles if r in with_data]
        x = _features(rows, candidates).dropna()
        std = x.std(ddof=0)
        roles = [r for r in candidates if float(std.get(r, 0.0)) > 1e-9]
        if len(roles) < 2:
            self.fit_receipt_ = {"status": "failed", "reason": f"{self.kind} needs at least two non-constant feature roles"}
            raise ValueError(f"{self.kind} needs at least two non-constant feature roles")
        x = x[roles]
        modes = operating_mode(rows.loc[x.index])
        rng = np.random.default_rng(self.seed)
        revision = self.fit_revision_ + 1
        models: dict[str, object] = {}
        mode_columns: dict[str, list[int]] = {}
        fitted: dict[str, dict] = {}
        skipped: dict[str, str] = {}
        for mode in sorted(modes.unique()):
            part = x[modes == mode]
            available = len(part)
            if available < 50:
                skipped[mode] = f"{available} complete active training rows (< 50)"
                continue
            if available > self.max_train:
                part = part.iloc[np.sort(rng.choice(available, self.max_train, replace=False))]
            # a role held constant in this mode (e.g. the damper at minimum) carries no information; COPOD's
            # skewness of a constant column is undefined, so drop such roles per mode
            spread = part.std(ddof=0).to_numpy()
            cols = [i for i, sd in enumerate(spread) if sd > 1e-9] if self.kind == "copod" else list(range(part.shape[1]))
            if len(cols) < 1:
                skipped[mode] = "no non-constant feature role in this mode"
                continue
            model = self._model()
            model.fit(part.to_numpy()[:, cols])
            models[mode] = model
            mode_columns[mode] = cols
            fitted[mode] = {"revision": revision, "available_rows": int(available), "fit_rows": int(len(part)),
                            "roles": [roles[i] for i in cols]}
        if not models:
            self.fit_receipt_ = {"status": "failed", "reason": f"{self.kind}: no operating mode had 50 normal rows",
                                 "skipped_modes": skipped}
            raise ValueError(f"{self.kind}: no operating mode had 50 normal rows")
        # commit the new baseline only now, all at once
        self.roles, self.models_, self.mode_columns_ = roles, models, mode_columns
        self.fit_revision_ = revision
        self.fit_receipt_ = {
            "status": "fitted", "kind": self.kind, "revision": revision, "seed": self.seed, "roles": list(roles),
            "training_rows": int(len(normal)), "active_training_rows": int(len(rows)), "complete_active_rows": int(len(x)),
            "training_start": None if x.empty else str(x.index.min()),
            "training_end": None if x.empty else str(x.index.max()),
            "modes": fitted, "skipped_modes": skipped,
        }
        return self

    def _require_fitted(self) -> None:
        if not self.models_:  # never fitted, or the last fit failed: never report "no faults" silently
            raise RuntimeError(f"{self.kind} is not fitted: call fit() on known-good data first")

    def assessment(self, frame: pd.DataFrame) -> pd.Series:
        """Per row: ``"assessed"`` or why not (``"inactive"``, ``"missing_inputs"``, ``"unsupported_mode"``).

        ``unsupported_mode`` is an operating mode with no model in the current fit (too few training rows, or
        absent from the training data). Such rows are unassessed, not healthy."""
        self._require_fitted()
        frame = canonical_roles(frame)
        act = active_mask(frame)
        complete = _features(frame, self.roles).notna().all(axis=1)
        modes = operating_mode(frame)
        out = pd.Series("assessed", index=frame.index, dtype=object)
        out[~modes.isin(list(self.models_))] = "unsupported_mode"
        out[~complete] = "missing_inputs"
        out[~act] = "inactive"
        return out

    def assessed_mask(self, frame: pd.DataFrame) -> pd.Series:
        return self.assessment(frame) == "assessed"

    def flags(self, frame: pd.DataFrame) -> pd.Series:
        self._require_fitted()
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
            values = x[sel].to_numpy()[:, self.mode_columns_[mode]]
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

    def scored_roles(self, frame: pd.DataFrame) -> list[str]:
        """Roles this detector actually screens on ``frame`` (present and not binary-like)."""
        from open_fdd.analytics.anomaly.detectors import is_binary_like

        f = canonical_roles(frame)
        return [r for r in self.roles if r in f.columns and not is_binary_like(pd.to_numeric(f[r], errors="coerce"))]

    def role_flags(self, frame: pd.DataFrame) -> pd.DataFrame:
        """One boolean column per scored role (already gated by :func:`active_mask`); ``flags`` is their OR."""
        from open_fdd.analytics.anomaly.detectors import rolling_mad_flags, rolling_zscore_flags, samples_per_day

        f = canonical_roles(frame)
        act = active_mask(f)
        window = samples_per_day(f.index)
        fn = rolling_zscore_flags if self.kind == "zscore" else rolling_mad_flags
        cols = {}
        for role in self.scored_roles(f):
            series = pd.to_numeric(f[role], errors="coerce")
            cols[role] = fn(series, window=window).reindex(f.index).fillna(False).astype(bool) & act
        return pd.DataFrame(cols, index=f.index)


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

    sel = contrib[flags.reindex(contrib.index).fillna(False).astype(bool)].dropna(how="all")
    if sel.empty:
        # zero alarms: say so instead of plotting whole-frame shares under a "flagged samples" label (#1660)
        fig, ax = plt.subplots(figsize=(6, 1.6))
        ax.axis("off")
        ax.text(0.5, 0.5, "No flagged samples: no contributions to show", ha="center", va="center")
        ax.set_title(title)
    else:
        share = sel.mean().sort_values(ascending=True)
        fig, ax = plt.subplots(figsize=(6, 0.4 * len(share) + 1.2))
        ax.barh(share.index, share.to_numpy() * 100.0)
        ax.set_xlabel(f"mean share of SPE on {len(sel)} flagged samples (%)")
        ax.set_title(f"{title}\n{sel.index.min()} to {sel.index.max()}", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
