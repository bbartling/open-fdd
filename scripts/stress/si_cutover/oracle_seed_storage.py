"""Checkout-only oracle seed conversion (metric-c-v2 storage from imperial wide CSV).

Used by ``sql_pandas_oracle_check.py --require-external-oracle`` so seed prep does
not import branch-only ``open_fdd.analytics.report_storage``. No imports from
``open_fdd`` — only pandas and contract constants aligned with ``metric_units.json``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# sql/contract/metric_units.json (same as open_fdd.units.convert)
PA_PER_IN_WC = 248.84
LPS_PER_CFM = 0.471947


def fahrenheit_to_celsius(value_f: float) -> float:
    return (float(value_f) - 32.0) * (5.0 / 9.0)

STORAGE_ABI_METRIC = "metric-c-v2"

ROLE_QUANTITY: dict[str, str] = {
    "discharge-air-temp": "absolute_temperature",
    "discharge-air-temp-sp": "absolute_temperature",
    "mixed-air-temp": "absolute_temperature",
    "return-air-temp": "absolute_temperature",
    "outside-air-temp": "absolute_temperature",
    "vav-discharge-air-temp": "absolute_temperature",
    "vav-inlet-air-temp": "absolute_temperature",
    "ahu-discharge-air-temp": "absolute_temperature",
    "chilled-water-supply-temp": "absolute_temperature",
    "chilled-water-return-temp": "absolute_temperature",
    "hot-water-supply-temp": "absolute_temperature",
    "hot-water-return-temp": "absolute_temperature",
    "zone-air-temp": "absolute_temperature",
    "web-outside-air-temp": "absolute_temperature",
    "web-outside-air-dewpoint": "absolute_temperature",
    "web-outside-air-wetbulb": "absolute_temperature",
    "duct-static-pressure": "air_pressure",
    "duct-static-pressure-sp": "air_pressure",
    "zone-airflow": "volumetric_flow",
    "min-flow-sp": "volumetric_flow",
}


def _convert_imperial_wide_columns_to_storage(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.attrs = dict(getattr(frame, "attrs", {}))
    for col in out.columns:
        role = str(col)
        quantity = ROLE_QUANTITY.get(role)
        if quantity is None:
            continue
        series = pd.to_numeric(out[col], errors="coerce")
        converted: list[float] = []
        for v in series:
            if pd.isna(v):
                converted.append(v)  # type: ignore[arg-type]
                continue
            fv = float(v)
            if quantity == "absolute_temperature":
                converted.append(fahrenheit_to_celsius(fv))
            elif quantity == "air_pressure":
                converted.append(fv * PA_PER_IN_WC)
            elif quantity == "volumetric_flow":
                converted.append(fv * LPS_PER_CFM)
            else:
                converted.append(fv)
        out[col] = converted
    return out


def _stamp_storage_role_units(frame: pd.DataFrame) -> None:
    role_units: dict[str, str] = dict(frame.attrs.get("role_units") or {})
    for col in frame.columns:
        quantity = ROLE_QUANTITY.get(str(col))
        if quantity == "absolute_temperature":
            role_units[str(col)] = "°C"
        elif quantity == "air_pressure":
            role_units[str(col)] = "Pa"
        elif quantity == "volumetric_flow":
            role_units[str(col)] = "L/s"
    if role_units:
        frame.attrs["role_units"] = role_units


def _tag_metric_storage_frame(frame: pd.DataFrame, *, display_units: str = "imperial") -> pd.DataFrame:
    out = frame.copy()
    out.attrs = dict(getattr(frame, "attrs", {}))
    out.attrs["storage_abi"] = STORAGE_ABI_METRIC
    out.attrs["display_units"] = display_units
    _stamp_storage_role_units(out)
    return out


def oracle_seed_frame_from_imperial_wide(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert Wave-0 oracle CSV magnitudes (imperial) to metric-c-v2 rule storage."""
    out = _convert_imperial_wide_columns_to_storage(frame)
    out.attrs["storage_values_converted"] = True
    return _tag_metric_storage_frame(out, display_units="imperial")


def oracle_seed_frame_for_pandas_rules(frame: pd.DataFrame, *, external_oracle: bool) -> pd.DataFrame:
    """Checkout SI conversion for branch rules; leave imperial wide for published PyPI oracle."""
    if external_oracle:
        return frame
    return oracle_seed_frame_from_imperial_wide(frame)


def ensure_storage_frame(frame: pd.DataFrame, column_map: dict[str, Any] | None = None) -> pd.DataFrame:
    """Minimal storage tagging for harness tests (source_units aware)."""
    column_map = column_map or {}
    abi = column_map.get("storage_abi") or getattr(frame, "attrs", {}).get("storage_abi")
    if str(abi or "").strip() != STORAGE_ABI_METRIC:
        raise ValueError("missing or unsupported storage_abi; expected metric-c-v2")
    out = frame.copy()
    out.attrs = dict(getattr(frame, "attrs", {}))
    out.attrs["storage_abi"] = STORAGE_ABI_METRIC
    source = str(column_map.get("source_units") or "").strip().lower()
    if source in {"imperial", "ip", "us", "f", "fahrenheit"} and not out.attrs.get(
        "storage_values_converted"
    ):
        out = _convert_imperial_wide_columns_to_storage(out)
        out.attrs["storage_values_converted"] = True
    display = str(column_map.get("display_units") or "imperial")
    out.attrs["display_units"] = display
    _stamp_storage_role_units(out)
    return out
