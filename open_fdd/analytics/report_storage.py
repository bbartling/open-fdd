"""SI storage vs display preference for PyPI reporting (#1284 W5b).

Historian and package ingest store metric-c-v2 (°C, Pa, L/s, …). The pandas
oracle and offline report accept that storage ABI and convert to the caller's
``imperial`` or ``si`` display preference only for presentation (Plotly axes,
Typst captions). Rule evaluation uses the storage frame unchanged.

Legacy device folders without ``storage_abi`` remain imperial-f-v1 until the CSV
values are re-exported in SI with ``storage_abi: metric-c-v2`` on the column map.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from open_fdd.analytics.units import DEFAULT_ROLE_UNITS, is_metric_unit_system, report_units_map
from open_fdd.units.convert import (
    PA_PER_IN_WC,
    LPS_PER_CFM,
    celsius_to_fahrenheit,
    delta_c_to_delta_f,
    delta_f_to_delta_c,
    fahrenheit_to_celsius,
)

STORAGE_ABI_METRIC = "metric-c-v2"
STORAGE_ABI_IMPERIAL = "imperial-f-v1"

ECON_IDENTIFIABLE_DELTA_IMPERIAL_F = 10.0

# Haystack role → metric_units.json quantity id (storage conversion).
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


def normalize_display_units(preference: str | None) -> str:
    """Return ``imperial`` or ``si`` (default imperial)."""
    token = str(preference or "imperial").strip().lower()
    if token in {"imperial", "ip", "us", "f", "fahrenheit"}:
        return "imperial"
    if token in {"si", "metric", "c", "celsius"}:
        return "si"
    raise ValueError("units must be imperial or si")


def resolve_storage_abi(column_map: dict[str, Any] | None, frame: Any | None = None) -> str:
    column_map = column_map or {}
    declared = column_map.get("storage_abi") or column_map.get("processing_abi")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    if frame is not None:
        existing = getattr(frame, "attrs", {}).get("storage_abi")
        if isinstance(existing, str) and existing.strip():
            return existing.strip()
    return STORAGE_ABI_IMPERIAL


def _legacy_imperial_unit(role: str) -> str | None:
    unit = DEFAULT_ROLE_UNITS.get(role)
    if unit in (None, "", "bool"):
        return None
    if unit == "°F":
        return "degF"
    if unit == "in. w.c.":
        return "inWC"
    if unit == "cfm":
        return "cfm"
    if unit == "%":
        return "percent"
    if unit == "kW":
        return "kW"
    if unit == "A":
        return "A"
    return str(unit)


def _imperial_to_storage(role: str, value: float) -> float:
    quantity = ROLE_QUANTITY.get(role)
    if quantity == "absolute_temperature":
        return fahrenheit_to_celsius(value)
    if quantity == "air_pressure":
        return float(value) * PA_PER_IN_WC
    if quantity == "volumetric_flow":
        return float(value) * LPS_PER_CFM
    return float(value)


def _storage_to_imperial(role: str, value: float) -> float:
    quantity = ROLE_QUANTITY.get(role)
    if quantity == "absolute_temperature":
        return celsius_to_fahrenheit(value)
    if quantity == "air_pressure":
        return float(value) / PA_PER_IN_WC
    if quantity == "volumetric_flow":
        return float(value) / LPS_PER_CFM
    return float(value)


def _storage_to_display(role: str, value: float, *, display: str) -> float:
    if display == "si":
        return float(value)
    return _storage_to_imperial(role, value)


def _legacy_to_display(role: str, value: float, *, display: str) -> float:
    if display == "imperial":
        return float(value)
    return _imperial_to_storage(role, value)


def ensure_storage_frame(frame: pd.DataFrame, column_map: dict[str, Any] | None = None) -> pd.DataFrame:
    """Tag ``storage_abi`` on the role frame used for rule evaluation.

    ``metric-c-v2`` folders store SI values as-is. Legacy folders (no
    ``storage_abi``) remain ``imperial-f-v1`` until the export is re-ingested in
    SI; display preference still converts presentation-only copies.
    """
    column_map = column_map or {}
    abi = resolve_storage_abi(column_map, frame)
    out = frame.copy()
    out.attrs = dict(getattr(frame, "attrs", {}))
    if abi not in {STORAGE_ABI_METRIC, STORAGE_ABI_IMPERIAL}:
        raise ValueError(f"unsupported storage_abi {abi!r}")
    out.attrs["storage_abi"] = abi
    metadata = dict(column_map)
    if abi == STORAGE_ABI_METRIC and not metadata.get("unit_system"):
        metadata["unit_system"] = "si"
    if abi == STORAGE_ABI_IMPERIAL and not metadata.get("unit_system"):
        metadata["unit_system"] = "imperial"
    from open_fdd.analytics.units import stamp_display_units

    stamp_display_units(out, metadata)
    return out


def frame_for_display(frame: pd.DataFrame, display_units: str | None) -> pd.DataFrame:
    """Presentation copy: convert storage SI values to the display preference."""
    preference = normalize_display_units(display_units)
    storage_abi = str(getattr(frame, "attrs", {}).get("storage_abi") or STORAGE_ABI_IMPERIAL)
    out = frame.copy()
    out.attrs = dict(getattr(frame, "attrs", {}))
    want_si = preference == "si"
    for col in out.columns:
        role = str(col)
        if role not in ROLE_QUANTITY:
            continue
        series = pd.to_numeric(out[col], errors="coerce")
        converted = []
        for v in series:
            if pd.isna(v):
                converted.append(v)
                continue
            fv = float(v)
            if storage_abi == STORAGE_ABI_METRIC:
                converted.append(_storage_to_display(role, fv, display=preference))
            else:
                converted.append(_legacy_to_display(role, fv, display=preference))
        out[col] = converted
    overrides = out.attrs.get("units") if isinstance(out.attrs.get("units"), dict) else None
    units_map = report_units_map(preference, overrides)
    out.attrs["display_units"] = preference
    out.attrs["unit_system"] = preference
    out.attrs["units_map"] = units_map
    return out


def apply_unit_metadata(frame: Any, metadata: dict[str, Any] | None = None) -> dict[str, str]:
    """Stamp display metadata on a frame (parity harness hook)."""
    metadata = metadata or {}
    preference = normalize_display_units(metadata.get("display_units") or metadata.get("unit_system"))
    overrides = metadata.get("units") if isinstance(metadata.get("units"), dict) else None
    units = report_units_map(preference, overrides)
    frame.attrs["display_units"] = preference
    frame.attrs["unit_system"] = preference
    frame.attrs["units_map"] = units
    if metadata.get("storage_abi"):
        frame.attrs["storage_abi"] = str(metadata["storage_abi"])
    return units


def economizer_identifiable_delta_min(display_units: str | None) -> float:
    """Minimum |OAT−RAT| for economizer scatter, in display temperature units."""
    if normalize_display_units(display_units) == "si":
        return delta_f_to_delta_c(ECON_IDENTIFIABLE_DELTA_IMPERIAL_F)
    return ECON_IDENTIFIABLE_DELTA_IMPERIAL_F


def fault_content_signature(results) -> list[dict[str, Any]]:
    """Stable fault rows for display-mode parity tests (T1284-6)."""
    rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: str(getattr(item, "rule_id", ""))):
        rows.append(
            {
                "rule_id": str(getattr(result, "rule_id", "")),
                "status": str(getattr(result, "status", "")),
                "fault_hours": round(float(getattr(result, "fault_hours", 0.0) or 0.0), 3),
                "applicable": bool(getattr(result, "applicable", False)),
            }
        )
    return rows
