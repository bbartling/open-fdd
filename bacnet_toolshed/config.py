"""Load enabled BACnet points from commissioning CSV."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bacnet_toolshed.point_id import make_point_id, make_series_id

CSV_FIELDNAMES = [
    "device_instance",
    "device_address",
    "object_type",
    "object_instance",
    "object_name",
    "description",
    "present_value",
    "units",
    "site_id",
    "building_id",
    "system_id",
    "brick_class",
    "brick_tag",
    "enabled",
    "poll_interval_s",
    "point_id",
    "series_id",
]


@dataclass
class PointConfig:
    device_instance: int
    device_address: str
    object_type: str
    object_instance: int
    object_name: str
    description: str
    units: str
    site_id: str
    building_id: str
    system_id: str
    brick_class: str
    brick_tag: str
    poll_interval_s: int
    point_id: str
    series_id: str
    object_id: str

    def rpm_key(self) -> str:
        return self.object_id


def _truthy(v: Any) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _object_id(object_type: str, object_instance: int | str) -> str:
    ot = str(object_type).strip().lower()
    return f"{ot},{object_instance}"


def normalize_row(row: dict[str, Any], defaults: dict[str, str] | None = None) -> dict[str, str]:
    defaults = defaults or {}
    out = {k: str(row.get(k) or defaults.get(k, "")).strip() for k in CSV_FIELDNAMES}
    if not out["site_id"]:
        out["site_id"] = defaults.get("site_id", "site")
    if not out["building_id"]:
        out["building_id"] = defaults.get("building_id", "building")
    if not out["system_id"]:
        out["system_id"] = "unknown"
    if not out["point_id"]:
        out["point_id"] = make_point_id(
            out["device_instance"], out["object_type"], out["object_instance"]
        )
    if not out["series_id"]:
        out["series_id"] = make_series_id(
            out["site_id"], out["building_id"], out["system_id"], out["point_id"]
        )
    return out


def row_to_point(row: dict[str, Any], defaults: dict[str, str] | None = None) -> PointConfig:
    n = normalize_row(row, defaults)
    return PointConfig(
        device_instance=int(n["device_instance"]),
        device_address=n["device_address"],
        object_type=n["object_type"],
        object_instance=int(n["object_instance"]),
        object_name=n["object_name"],
        description=n["description"],
        units=n["units"],
        site_id=n["site_id"],
        building_id=n["building_id"],
        system_id=n["system_id"],
        brick_class=n["brick_class"],
        brick_tag=n["brick_tag"],
        poll_interval_s=int(n["poll_interval_s"] or "0") or 0,
        point_id=n["point_id"],
        series_id=n["series_id"],
        object_id=_object_id(n["object_type"], n["object_instance"]),
    )


def load_points_csv(
    path: str | Path,
    *,
    enabled_only: bool = False,
    defaults: dict[str, str] | None = None,
) -> list[PointConfig]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    points: list[PointConfig] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            if enabled_only and not _truthy(raw.get("enabled")):
                continue
            if not raw.get("device_instance") or not raw.get("object_type"):
                continue
            if not str(raw.get("object_instance", "")).strip():
                continue
            points.append(row_to_point(raw, defaults))
    return points


def load_enabled_points(
    path: str | Path,
    defaults: dict[str, str] | None = None,
) -> list[PointConfig]:
    return load_points_csv(path, enabled_only=True, defaults=defaults)


def group_by_device(points: list[PointConfig]) -> dict[tuple[int, str], list[PointConfig]]:
    out: dict[tuple[int, str], list[PointConfig]] = {}
    for p in points:
        key = (p.device_instance, p.device_address)
        out.setdefault(key, []).append(p)
    return out


def validate_points(points: list[PointConfig]) -> list[str]:
    errors: list[str] = []
    if not points:
        errors.append("no enabled points in CSV")
    for p in points:
        if not p.device_address:
            errors.append(f"missing device_address for {p.point_id}")
        if not p.site_id or not p.building_id:
            errors.append(f"missing site_id/building_id for {p.point_id}")
    return errors
