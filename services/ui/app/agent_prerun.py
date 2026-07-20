"""Post-upload agent helpers: column map bootstrap + fault prerun (no HTTP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class PrerunResult:
    ok: bool
    message: str
    evaluations: int = 0
    column_map_built: bool = False
    warnings: list[str] = field(default_factory=list)
    error_count: int = 0
    fault_count: int = 0
    skip_count: int = 0


def ensure_column_map(
    frames: dict[str, pd.DataFrame],
    *,
    existing_map: dict[str, Any] | None,
    building_id: str = "",
) -> tuple[dict[str, Any] | None, bool, list[str]]:
    """Return (column_map, built_new, warnings). Builds from CSVs if missing."""
    warnings: list[str] = []
    if existing_map and (existing_map.get("equipment") or existing_map.get("points")):
        return existing_map, False, warnings
    try:
        from app.column_map_json import build_column_map_from_equipment_frames

        cmap = build_column_map_from_equipment_frames(
            frames, building_id=building_id or "UNKNOWN"
        )
        warnings.append("Auto-built column_map from loaded CSV headers / columns.csv")
        return cmap, True, warnings
    except Exception as exc:
        warnings.append(f"column_map auto-build skipped: {exc}")
        return existing_map, False, warnings


def prerun_faults(
    frames: dict[str, pd.DataFrame],
    *,
    params_by_rule: dict[str, dict] | None = None,
    weather: pd.DataFrame | None = None,
    role_map: dict[str, Any] | None = None,
) -> tuple[list[Any], PrerunResult]:
    """Run all active rules for every equipment; return results + summary."""
    from app.rules.runner import run_batch

    # Stamp role_map onto frames for run_batch apply_role_map
    stamped: dict[str, pd.DataFrame] = {}
    for eq_id, df in frames.items():
        out = df.copy(deep=False)
        out.attrs = dict(getattr(df, "attrs", {}) or {})
        out.attrs["equipment_id"] = eq_id
        if role_map is not None:
            out.attrs["_role_map"] = role_map
        stamped[eq_id] = out

    results = run_batch(
        stamped,
        params_by_rule=params_by_rule,
        weather=weather,
    )
    err = sum(1 for r in results if getattr(r, "status", "") == "ERROR")
    fault = sum(1 for r in results if getattr(r, "status", "") == "FAULT")
    skip = sum(
        1
        for r in results
        if str(getattr(r, "status", "")).startswith("SKIPPED")
        or getattr(r, "status", "") == "NOT_APPLICABLE_EQUIPMENT_TYPE"
    )
    ok = err == 0
    msg = (
        f"Prerun complete: {len(results)} evaluations · "
        f"{fault} FAULT · {skip} skipped/NA · {err} ERROR"
    )
    return results, PrerunResult(
        ok=ok,
        message=msg,
        evaluations=len(results),
        warnings=[],
        error_count=err,
        fault_count=fault,
        skip_count=skip,
    )
