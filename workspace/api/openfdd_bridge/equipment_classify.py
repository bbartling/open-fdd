"""Classify model equipment rows (equipment_type, brick_type, name) for FDD presets and TTL."""

from __future__ import annotations

from typing import Any


def _equipment_key(eq: dict[str, Any]) -> str:
    return str(eq.get("id") or eq.get("equipment_id") or "").lower()


def effective_equipment_type(eq: dict[str, Any]) -> str:
    et = str(eq.get("equipment_type") or "").strip()
    if et:
        return et
    bt = str(eq.get("brick_type") or "").strip()
    return bt or "Equipment"


def is_vav(eq: dict[str, Any]) -> bool:
    et = effective_equipment_type(eq).upper()
    name = str(eq.get("name") or "").lower()
    eid = _equipment_key(eq)
    if "VAV" in et or "VARIABLE_AIR" in et or "vav" in name:
        return True
    return "-vav-" in eid or eid.endswith("-vav") or "trane-vav" in eid or "jci-vav" in eid


def is_ahu(eq: dict[str, Any]) -> bool:
    et = effective_equipment_type(eq).upper()
    name = str(eq.get("name") or "").lower()
    eid = _equipment_key(eq)
    if "AHU" in et or "AIR_HANDLER" in et or "AIR_HANDLING" in et:
        return True
    if "RTU" in et or "ROOFTOP" in et:
        return True
    if "rtu" in name or "ahu" in name:
        return True
    if "air_handling" in name.replace(" ", "_"):
        return True
    if "-rtu-" in eid or eid.endswith("-rtu") or "-ahu-" in eid or eid.endswith("-ahu"):
        return True
    inst = eq.get("bacnet_device_instance")
    if inst is not None and str(inst) == "1100":
        return True
    return False


def is_zone(eq: dict[str, Any]) -> bool:
    et = effective_equipment_type(eq).upper()
    name = str(eq.get("name") or "").lower()
    if "VAV" in et:
        return False
    return "ZONE" in et or "HVAC_ZONE" in et or ("zone" in name and "vav" not in name)


def hvac_bucket(eq: dict[str, Any]) -> str | None:
    if is_ahu(eq):
        return "AHU"
    if is_vav(eq):
        return "VAV"
    if is_zone(eq):
        return "ZONE"
    return None


def is_hws(eq: dict[str, Any]) -> bool:
    et = effective_equipment_type(eq).upper()
    name = str(eq.get("name") or "").lower()
    eid = _equipment_key(eq)
    if "HOT_WATER" in et or "HW_PLANT" in et or "BOILER" in et or "CHILLER" in et:
        return True
    if "hw-plant" in eid or "hw_plant" in eid or "boiler" in eid:
        return True
    return "hw plant" in name or "boiler" in name or "hot water" in name


def is_chiller(eq: dict[str, Any]) -> bool:
    et = effective_equipment_type(eq).upper()
    name = str(eq.get("name") or "").lower()
    eid = _equipment_key(eq)
    if "CHILLER" in et or "CHILLED_WATER" in et or "CW_PLANT" in et:
        return True
    return "chiller" in name or "chw" in eid or "cw-plant" in eid


def is_zone_box(eq: dict[str, Any]) -> bool:
    """Generic zone-level equipment (FCU/VAV box, lab BACnet device, zone sensors)."""
    et = effective_equipment_type(eq).upper()
    name = str(eq.get("name") or "").lower()
    eid = _equipment_key(eq)
    if is_ahu(eq) or is_vav(eq) or is_chiller(eq) or is_hws(eq):
        return False
    if "BACNET_DEVICE" in et or "LABORATORY" in et or "BRICK" in et:
        return True
    if "bench" in eid or "5007" in eid or "bens" in name:
        return True
    return is_zone(eq)


def is_oat_sensor(eq: dict[str, Any]) -> bool:
    et = effective_equipment_type(eq).upper()
    name = str(eq.get("name") or "").lower()
    return "OUTSIDE_AIR" in et or "WEATHER" in et or "oat" in name or "outside air" in name


def report_family(eq: dict[str, Any]) -> str:
    if is_ahu(eq):
        return "ahu"
    if is_chiller(eq):
        return "chiller"
    if is_hws(eq):
        return "hws"
    if is_vav(eq):
        return "vav"
    if is_oat_sensor(eq):
        return "oat_weather"
    if is_zone_box(eq):
        return "zone"
    return "other"
