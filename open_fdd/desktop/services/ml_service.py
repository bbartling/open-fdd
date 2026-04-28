from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

import pandas as pd

from open_fdd.desktop.services.time_utils import infer_timestamp_column, parse_timestamp_series
from open_fdd.desktop.storage.connectors import TimeSeriesConnector


@dataclass
class MlRunResult:
    rows_train: int
    rows_test: int
    rows_scored: int
    model_name: str
    mae: float
    rmse: float
    r2: float
    residual_threshold: float
    output_source: str
    storage_ref: str
    overlap_with_rule_flag: int


def _safe_token(value: str) -> str:
    raw = str(value or "").strip().casefold()
    out = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return out or "metric"


def _to_float(value: float) -> float:
    if math.isfinite(float(value)):
        return float(value)
    return 0.0


class MLService:
    def __init__(self, connector: TimeSeriesConnector) -> None:
        self.connector = connector

    def train_baseline(
        self,
        *,
        site_id: str,
        source: str,
        target_col: str,
        feature_cols: list[str] | None = None,
        lag_cols: list[str] | None = None,
        train_fraction: float = 0.8,
        residual_quantile: float = 0.95,
        rule_flag_col: str | None = None,
        output_source: str | None = None,
    ) -> MlRunResult:
        try:
            from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
            from sklearn.linear_model import LinearRegression
            from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
        except ImportError as exc:
            raise RuntimeError(
                "ML baseline requires scikit-learn. Install desktop extras: pip install open-fdd[desktop]"
            ) from exc

        frame = self.connector.read_frame(source=source, site_id=site_id)
        if frame.empty:
            raise ValueError(f"No rows found for source='{source}' site_id='{site_id}'.")
        if target_col not in frame.columns:
            raise ValueError(f"Target column not found: {target_col}")

        df = frame.copy()
        ts_col = infer_timestamp_column(df)
        df[ts_col] = parse_timestamp_series(df, timestamp_col=ts_col, min_valid_ratio=0.5)
        df = df[df[ts_col].notna()].sort_values(ts_col).reset_index(drop=True)
        if df.empty:
            raise ValueError("No valid timestamp rows available after parsing.")

        candidate_features = [str(c) for c in (feature_cols or []) if str(c) and str(c) != target_col]
        if not candidate_features:
            candidate_features = [str(c) for c in df.columns if str(c) not in {ts_col, target_col}]

        for lag_col in lag_cols or []:
            if lag_col in df.columns:
                df[f"{lag_col}_lag1"] = pd.to_numeric(df[lag_col], errors="coerce").shift(1)
                candidate_features.append(f"{lag_col}_lag1")

        feature_set: list[str] = []
        for col in candidate_features:
            if col in df.columns and col not in feature_set:
                feature_set.append(col)
        if not feature_set:
            raise ValueError("No usable feature columns found.")

        model_df = df[[ts_col, target_col, *feature_set]].copy()
        for col in [target_col] + feature_set:
            model_df[col] = pd.to_numeric(model_df[col], errors="coerce")
        model_df = model_df.dropna(subset=[target_col] + feature_set)
        if len(model_df.index) < 40:
            raise ValueError(f"Not enough rows for ML training after cleaning: {len(model_df.index)}")

        split_idx = max(1, min(len(model_df.index) - 1, int(len(model_df.index) * max(0.5, min(0.95, train_fraction)))))
        train = model_df.iloc[:split_idx].copy()
        test = model_df.iloc[split_idx:].copy()
        if train.empty or test.empty:
            raise ValueError("Insufficient train/test split. Add more data rows.")

        x_train = train[feature_set]
        y_train = train[target_col]
        x_test = test[feature_set]
        y_test = test[target_col]

        candidates: list[tuple[str, Any]] = [
            ("linear_regression", LinearRegression()),
            ("random_forest", RandomForestRegressor(n_estimators=200, min_samples_leaf=5, random_state=42, n_jobs=-1)),
            ("extra_trees", ExtraTreesRegressor(n_estimators=300, min_samples_leaf=5, random_state=42, n_jobs=-1)),
        ]
        best_name = ""
        best_model = None
        best_mae = float("inf")
        best_rmse = float("inf")
        best_r2 = float("-inf")

        for name, model in candidates:
            model.fit(x_train, y_train)
            pred = model.predict(x_test)
            mae = _to_float(mean_absolute_error(y_test, pred))
            rmse = _to_float(math.sqrt(mean_squared_error(y_test, pred)))
            r2 = _to_float(r2_score(y_test, pred))
            if mae < best_mae:
                best_name = name
                best_model = model
                best_mae = mae
                best_rmse = rmse
                best_r2 = r2

        if best_model is None:
            raise RuntimeError("No best_model found after evaluating candidates.")
        scored = model_df[[ts_col, target_col, *feature_set]].copy()
        scored["ml_prediction"] = best_model.predict(scored[feature_set])
        scored["ml_residual"] = scored[target_col] - scored["ml_prediction"]
        scored["ml_abs_residual"] = scored["ml_residual"].abs()
        threshold = _to_float(scored["ml_abs_residual"].quantile(max(0.5, min(0.999, residual_quantile))))
        scored["ml_residual_fault"] = (scored["ml_abs_residual"] >= threshold).astype(int)

        overlap = 0
        if rule_flag_col and rule_flag_col in df.columns:
            # Align rule flag directly on scored row index to avoid many-to-many timestamp merges.
            aligned_rule = pd.to_numeric(df.loc[scored.index, rule_flag_col], errors="coerce").fillna(0).astype(int)
            overlap = int(((scored["ml_residual_fault"] == 1) & (aligned_rule == 1)).sum())

        out_source = output_source or f"ml_{_safe_token(target_col)}"
        output_frame = scored[[ts_col, target_col, "ml_prediction", "ml_residual", "ml_abs_residual", "ml_residual_fault"]].copy()
        output_frame = output_frame.rename(columns={ts_col: "timestamp", target_col: "target_actual"})
        storage_ref = str(self.connector.write_frame(source=out_source, site_id=site_id, frame=output_frame))

        return MlRunResult(
            rows_train=len(train.index),
            rows_test=len(test.index),
            rows_scored=len(output_frame.index),
            model_name=best_name,
            mae=best_mae,
            rmse=best_rmse,
            r2=best_r2,
            residual_threshold=threshold,
            output_source=out_source,
            storage_ref=storage_ref,
            overlap_with_rule_flag=overlap,
        )
