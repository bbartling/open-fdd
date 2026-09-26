"""Generic RCx report template: profiles, figure selection, history sources.

Any agent can build the same PDF from mapped roles and a history frame. The
deploy host is not part of the template. A device folder, an Open-FDD HTTP
API (self-hosted or hosted), or a future vendor adapter all land on
``RoleHistory``.

Only the VAV-style air-handler profile draws figures today. Other system
profiles are registered so a later pass can fill them without a new chrome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

# Agents write prose into these keys (``ai_comments.json`` or the API).
# Empty slots stay out of the end-user PDF.
AI_COMMENT_SLOTS: tuple[str, ...] = (
    "sensor_checks",
    "anomaly_screening",
    "executive_summary",
    "rcx_week",
    "confirmed_faults",
    "economizer",
)

# Individual AHU timeseries already covered by the economizer rainbow overlay.
SKIPPED_RCX_PRESET_IDS: frozenset[str] = frozenset(
    {
        "ahu_dats",
        "ahu_mats",
        "ahu_rats",
        "ahu_dampers",
        "ahu_cooling_valves",
        "fan_speeds",
    }
)


@dataclass(frozen=True)
class FigureSpec:
    """One PDF figure. Included only when every ``roles`` entry is mapped."""

    id: str
    title: str
    caption: str
    kind: str
    roles: tuple[str, ...]
    any_roles: tuple[str, ...] = ()
    y_role: str = ""
    overlay_role: str = ""
    fan_on: bool = False


@dataclass(frozen=True)
class SystemProfile:
    id: str
    label: str
    equipment_types: tuple[str, ...]
    implemented: bool
    figures: tuple[FigureSpec, ...] = ()


def _vav_ahu_figures() -> tuple[FigureSpec, ...]:
    return (
        FigureSpec(
            "econ_temps",
            "Free-cooling temperatures and outdoor-air damper",
            "Outdoor, return, mixed, and supply air on the temperature axis. "
            "Damper percent is on the right axis. Fan running only.",
            "econ_temps",
            ("outside-air-temp", "return-air-temp", "mixed-air-temp"),
            fan_on=True,
        ),
        FigureSpec(
            "bas_web_oat",
            "BAS vs web outdoor-air temperature",
            "Building outdoor-air temperature and web outdoor-air temperature on one axis.",
            "bas_web",
            ("outside-air-temp", "web-outside-air-temp"),
        ),
        FigureSpec(
            "ahu_sat_reset_scatter",
            "Supply air vs web outdoor temperature",
            "Supply air temperature against web outdoor air. Fan running only.",
            "oat_scatter",
            ("discharge-air-temp", "web-outside-air-temp"),
            any_roles=("fan-status", "fan-cmd"),
            y_role="discharge-air-temp",
            fan_on=True,
        ),
        FigureSpec(
            "duct_static_box",
            "Duct static while the fan runs",
            "Duct static pressure with the fan running.",
            "box",
            ("duct-static-pressure",),
            any_roles=("fan-status", "fan-cmd"),
            y_role="duct-static-pressure",
            fan_on=True,
        ),
        FigureSpec(
            "duct_static_ts",
            "Duct static and setpoint",
            "Duct static pressure with the mapped setpoint.",
            "timeseries",
            ("duct-static-pressure",),
            y_role="duct-static-pressure",
            overlay_role="duct-static-pressure-sp",
        ),
    )


def _stub(profile_id: str, label: str, *equipment_types: str) -> SystemProfile:
    return SystemProfile(
        id=profile_id,
        label=label,
        equipment_types=equipment_types,
        implemented=False,
    )


PROFILES: dict[str, SystemProfile] = {
    "vav_ahu": SystemProfile(
        id="vav_ahu",
        label="Air handler",
        equipment_types=("AHU",),
        implemented=True,
        figures=_vav_ahu_figures(),
    ),
    "cv_ahu": _stub("cv_ahu", "Constant-volume air handler", "AHU"),
    "single_zone": _stub("single_zone", "Single-zone unit", "ZONE"),
    "chiller": _stub("chiller", "Chiller", "CHILLER", "CHW_PLANT"),
    "boiler": _stub("boiler", "Boiler", "BOILER"),
    "heat_pump": _stub("heat_pump", "Heat pump", "HP"),
    "vav_box": _stub("vav_box", "VAV box", "VAV"),
    "fan_coil": _stub("fan_coil", "Fan coil", "FCU", "ZONE"),
    "geothermal_field": _stub("geothermal_field", "Geothermal field", "GEOTHERMAL"),
    "data_hall": _stub("data_hall", "Data hall", "DATA_HALL"),
}

_EQUIP_PROFILE = {
    "ahu": "vav_ahu",
    "rtu": "vav_ahu",
    "unitventilator": "vav_ahu",
    "uv": "vav_ahu",
    "vav": "vav_box",
    "fcu": "fan_coil",
    "zone": "single_zone",
    "zone_other": "single_zone",
    "chiller": "chiller",
    "chwplant": "chiller",
    "chw_plant": "chiller",
    "boiler": "boiler",
    "heatpump": "heat_pump",
    "hp": "heat_pump",
    "geothermal": "geothermal_field",
    "datahall": "data_hall",
    "data_hall": "data_hall",
}


def profile_for_equip_type(equip_type: str | None) -> str:
    """Map a stamped equipment type to a registered profile id."""
    key = str(equip_type or "").strip().lower().replace("-", "").replace(" ", "")
    key = key.replace("_", "")
    # keys above use underscores removed except we stored both forms
    compact = {
        name.replace("_", ""): profile_id for name, profile_id in _EQUIP_PROFILE.items()
    }
    return compact.get(key, "vav_ahu")


def resolve_profile(profile_id: str | None, equip_type: str | None = None) -> SystemProfile:
    """Return a registered profile. Unknown ids are an error."""
    chosen = (profile_id or "").strip() or profile_for_equip_type(equip_type)
    profile = PROFILES.get(chosen)
    if profile is None:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown report profile {chosen!r}. Known profiles: {known}")
    return profile


def select_figures(profile_id: str, mapped_roles: set[str]) -> list[FigureSpec]:
    """Figures whose required roles are present. Skipped presets never return."""
    profile = resolve_profile(profile_id)
    if not profile.implemented:
        return []
    chosen: list[FigureSpec] = []
    for spec in profile.figures:
        if spec.id in SKIPPED_RCX_PRESET_IDS:
            continue
        if not all(role in mapped_roles for role in spec.roles):
            continue
        if spec.any_roles and not any(role in mapped_roles for role in spec.any_roles):
            continue
        chosen.append(spec)
    return chosen


def empty_ai_comments() -> dict[str, str]:
    return {slot: "" for slot in AI_COMMENT_SLOTS}


def load_ai_comments(folder: Path | str, override: dict[str, str] | None = None) -> dict[str, str]:
    """Merge ``ai_comments.json`` in the device folder with an explicit dict.

    Unknown keys are ignored. Empty strings stay out of the PDF.
    """
    import json

    comments = empty_ai_comments()
    path = Path(folder) / "ai_comments.json"
    blobs: list[dict] = []
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            blobs.append(raw)
    if override:
        blobs.append(dict(override))
    for raw in blobs:
        for key, value in raw.items():
            if key in comments and value is not None:
                comments[key] = str(value).strip()
    return comments


@dataclass
class RoleHistory:
    """Role-named history, independent of where the rows came from."""

    frame: pd.DataFrame
    equipment_id: str
    equipment_type: str
    points: list[tuple[str, str]]
    source_id: str


@dataclass
class DeviceFolderSource:
    """``history_wide.csv`` + ``column_map.json`` on disk."""

    folder: Path | str
    source_id: str = field(default="device_folder", init=False)

    def load(self) -> RoleHistory:
        from open_fdd.analytics.anomaly.io import load_device_folder
        from open_fdd.reporting.single_system_typst import equipment_label, role_frame

        folder = Path(self.folder)
        device = load_device_folder(folder)
        frame = role_frame(device)
        equip_type = str(frame.attrs.get("equipment_type") or "ahu")
        return RoleHistory(
            frame=frame,
            equipment_id=equipment_label(device.column_map, folder),
            equipment_type=equip_type,
            points=list(device.points),
            source_id=self.source_id,
        )


@dataclass
class OpenFddApiSource:
    """History from any Open-FDD central. Pass ``reader`` to supply the frame.

    ``base_url`` is the central origin (self-hosted or hosted). This class does
    not open a network connection. An agent that already holds a JWT passes a
    ``reader`` that returns a role-named frame.
    """

    base_url: str
    reader: Callable[[], pd.DataFrame] | None = None
    equipment_id: str = "AHU"
    equipment_type: str = "ahu"
    source_id: str = field(default="openfdd_api", init=False)

    def load(self) -> RoleHistory:
        if self.reader is None:
            raise NotImplementedError(
                "Open-FDD API history needs a reader that returns a role-named frame. "
                "Use a device folder (history_wide.csv + column_map.json) until that reader is supplied. "
                f"Central origin: {self.base_url}"
            )
        frame = self.reader()
        points = [(str(column), str(column)) for column in frame.columns]
        return RoleHistory(
            frame=frame,
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            points=points,
            source_id=self.source_id,
        )


@dataclass
class VendorApiSource:
    """Placeholder for a future vendor historian. No vendor calls are made."""

    vendor: str
    reader: Callable[[], pd.DataFrame] | None = None
    equipment_id: str = "AHU"
    equipment_type: str = "ahu"
    source_id: str = field(default="vendor_api", init=False)

    def load(self) -> RoleHistory:
        if self.reader is None:
            raise NotImplementedError(
                f"Vendor API {self.vendor!r} is registered and not connected. "
                "Map the export into a device folder, or pass a reader that returns a role-named frame."
            )
        frame = self.reader()
        points = [(str(column), str(column)) for column in frame.columns]
        return RoleHistory(
            frame=frame,
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            points=points,
            source_id=self.source_id,
        )


HISTORY_SOURCES: dict[str, type] = {
    "device_folder": DeviceFolderSource,
    "openfdd_api": OpenFddApiSource,
    "vendor_api": VendorApiSource,
}
