"""Load a device folder (``history_wide.csv`` + ``column_map.json``)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

# Stamped types that count as AHU IO for v1 screening.
_AHU_EQUIP_TYPES = frozenset({"ahu", "rtu", "unitventilator", "uv", "cv"})


@dataclass
class DeviceSeries:
    """Wide historian indexed by UTC timestamps plus resolved AHU IO columns."""

    frame: pd.DataFrame
    points: list[tuple[str, str]]
    missing: list[tuple[str, str]] = field(default_factory=list)
    column_map: dict[str, Any] = field(default_factory=dict)


def _equip_type(block: dict[str, Any]) -> str:
    raw = block.get("equipType") or block.get("equipment_type") or ""
    return str(raw).strip().lower()


def _is_ahu_type(equip_type: str) -> bool:
    return equip_type in _AHU_EQUIP_TYPES


def _pairs_from_block(block: dict[str, Any]) -> list[tuple[str, str]]:
    """Merge ``column_roles`` then ``points`` (points win on the same role)."""
    merged: dict[str, str] = {}
    for key in ("column_roles", "points"):
        raw = block.get(key)
        if not isinstance(raw, dict):
            continue
        for role, column in raw.items():
            if not isinstance(column, str):
                continue
            column = column.strip()
            if not column:
                continue
            merged[str(role)] = column
    return list(merged.items())


def _dedupe(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        out.append(pair)
    return out


def iter_ahu_io_points(column_map: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ``(role, column)`` for AHU IO referenced by the column map.

    Flat device maps contribute every ``points`` / ``column_roles`` entry when
    the stamp is missing or AHU-like. Nested ``equipment`` blocks contribute
    only AHU-typed blocks (or unstamped ids that start with ``ahu`` / ``rtu``).
    Zone / VAV blocks are omitted.
    """
    if not isinstance(column_map, dict):
        return []
    equipment = column_map.get("equipment")
    if isinstance(equipment, dict) and equipment:
        pairs: list[tuple[str, str]] = []
        for equip_id, block in equipment.items():
            if not isinstance(block, dict):
                continue
            equip_type = _equip_type(block)
            if equip_type:
                if not _is_ahu_type(equip_type):
                    continue
            else:
                token = str(equip_id).strip().lower()
                if not (token.startswith("ahu") or token.startswith("rtu")):
                    continue
            pairs.extend(_pairs_from_block(block))
        return _dedupe(pairs)

    equip_type = _equip_type(column_map)
    if equip_type and not _is_ahu_type(equip_type):
        return []
    return _dedupe(_pairs_from_block(column_map))


def load_device_folder(path: Path | str) -> DeviceSeries:
    """Read ``history_wide.csv`` and ``column_map.json`` from ``path``.

    ``timestamp_utc`` becomes a timezone-aware UTC index. Columns named by the
    map but absent from the CSV are recorded on ``missing`` and are not screened.
    """
    folder = Path(path)
    csv_path = folder / "history_wide.csv"
    map_path = folder / "column_map.json"
    if not csv_path.is_file():
        raise FileNotFoundError(f"missing history_wide.csv in {folder}")
    if not map_path.is_file():
        raise FileNotFoundError(f"missing column_map.json in {folder}")

    frame = pd.read_csv(csv_path)
    if "timestamp_utc" not in frame.columns:
        raise ValueError(f"{csv_path} has no timestamp_utc column")
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, format="mixed")
    frame = frame.drop(columns=["timestamp_utc"])
    frame.index = pd.DatetimeIndex(timestamps, name="timestamp_utc")
    frame = frame.sort_index()

    column_map = json.loads(map_path.read_text(encoding="utf-8"))
    if not isinstance(column_map, dict):
        raise ValueError(f"{map_path} must be a JSON object")

    present: list[tuple[str, str]] = []
    missing: list[tuple[str, str]] = []
    for role, column in iter_ahu_io_points(column_map):
        if column in frame.columns:
            present.append((role, column))
        else:
            missing.append((role, column))
    return DeviceSeries(frame=frame, points=present, missing=missing, column_map=column_map)
