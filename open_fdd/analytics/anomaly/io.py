"""Load a device folder (``history_wide.csv`` + ``column_map.json``)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from open_fdd.analytics.site_model import normalize_equipment_type


@dataclass
class DeviceSeries:
    """Wide historian indexed by UTC timestamps plus resolved AHU IO columns."""

    frame: pd.DataFrame
    points: list[tuple[str, str]]
    missing: list[tuple[str, str]] = field(default_factory=list)
    column_map: dict[str, Any] = field(default_factory=dict)


def _equip_type(block: dict[str, Any]) -> str:
    raw = block.get("equipType") or block.get("equipment_type") or ""
    return str(raw).strip()


def _is_ahu_type(equip_type: str) -> bool:
    """AHU admission is the canonical stamp. Id text is not a type."""
    return normalize_equipment_type(equip_type) == "AHU"


def _recognized_stamp(raw: str) -> bool:
    norm = normalize_equipment_type(raw)
    return bool(norm) and norm != "UNKNOWN"


def admitted_equipment_stamp(
    column_map: dict[str, Any],
    *,
    point_pairs: list[tuple[str, str]] | None = None,
) -> str:
    """Raw ``equipType`` / ``equipment_type`` from the map.

    A top-level stamp wins when it is recognized. Otherwise the stamp comes
    from nested blocks whose points were loaded. Disagreeing nested stamps
    stay blank. Equipment-id text is not consulted.
    """
    if not isinstance(column_map, dict):
        return ""
    top = _equip_type(column_map)
    if _recognized_stamp(top):
        return top
    blocks = _equipment_blocks(column_map)
    if not blocks:
        return ""
    wanted = set(point_pairs) if point_pairs is not None else None
    stamps: list[str] = []
    for block in blocks.values():
        if not isinstance(block, dict):
            continue
        pairs = _pairs_from_block(block)
        if wanted is not None and not (set(pairs) & wanted):
            continue
        raw = _equip_type(block)
        if _recognized_stamp(raw):
            stamps.append(raw)
    if not stamps:
        return ""
    if len({normalize_equipment_type(stamp) for stamp in stamps}) != 1:
        return ""
    return stamps[0]


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


def _equipment_blocks(column_map: dict[str, Any]) -> dict[str, Any] | None:
    """Nested equipment map.

    Package exports use ``equipment``. Haystack exports use ``equip`` as an
    object of device blocks. A string ``equip`` (device id on a flat sidecar)
    is metadata and is not a block map.
    """
    equipment = column_map.get("equipment")
    if isinstance(equipment, dict) and equipment:
        return equipment
    equip = column_map.get("equip")
    if isinstance(equip, dict) and equip:
        return equip
    return None


def iter_mapped_points(column_map: dict[str, Any]) -> list[tuple[str, str]]:
    """Every ``(role, column)`` pair, including non-AHU equipment stamps.

    Nested ``equipment`` / Haystack ``equip`` blocks contribute every device.
    A flat sidecar contributes its ``points`` / ``column_roles``.
    """
    if not isinstance(column_map, dict):
        return []
    equipment = _equipment_blocks(column_map)
    if equipment is not None:
        pairs: list[tuple[str, str]] = []
        for block in equipment.values():
            if isinstance(block, dict):
                pairs.extend(_pairs_from_block(block))
        return _dedupe(pairs)
    return _dedupe(_pairs_from_block(column_map))


def iter_ahu_io_points(column_map: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ``(role, column)`` for AHU IO referenced by the column map.

    Nested ``equipment`` / Haystack ``equip`` blocks and flat maps contribute
    points only when the block is stamped as an AHU-family type. A missing
    stamp is not AHU. Zone / VAV blocks are omitted. ``equipment`` wins when
    it is a non-empty object; otherwise a dict ``equip`` is used.
    """
    if not isinstance(column_map, dict):
        return []
    equipment = _equipment_blocks(column_map)
    if equipment is not None:
        pairs: list[tuple[str, str]] = []
        for _equip_id, block in equipment.items():
            if not isinstance(block, dict):
                continue
            if not _is_ahu_type(_equip_type(block)):
                continue
            pairs.extend(_pairs_from_block(block))
        return _dedupe(pairs)

    if not _is_ahu_type(_equip_type(column_map)):
        return []
    return _dedupe(_pairs_from_block(column_map))


def load_device_folder(path: Path | str, *, ahu_only: bool = True) -> DeviceSeries:
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
    point_pairs = iter_ahu_io_points(column_map) if ahu_only else iter_mapped_points(column_map)
    for role, column in point_pairs:
        if column in frame.columns:
            present.append((role, column))
        else:
            missing.append((role, column))
    return DeviceSeries(frame=frame, points=present, missing=missing, column_map=column_map)
