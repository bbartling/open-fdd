"""Classify equipment for RCx Central (mirrors openfdd_bridge.equipment_classify)."""

from __future__ import annotations

from typing import Any


def effective_equipment_type(eq: dict[str, Any]) -> str:
    et = str(eq.get("equipment_type") or "").strip()
    if et:
        return et
    bt = str(eq.get("brick_type") or "").strip()
    return bt or "Equipment"


def is_vav(eq: dict[str, Any]) -> bool:
    et = effective_equipment_type(eq).upper()
    name = str(eq.get("name") or "").lower()
    return "VAV" in et or "VARIABLE_AIR" in et or "vav" in name


def is_ahu(eq: dict[str, Any]) -> bool:
    et = effective_equipment_type(eq).upper()
    name = str(eq.get("name") or "").lower()
    if "AHU" in et or "AIR_HANDLER" in et or "AIR_HANDLING" in et:
        return True
    if "RTU" in et or "ROOFTOP" in et:
        return True
    if "rtu" in name or "ahu" in name:
        return True
    return "air_handling" in name.replace(" ", "_")


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
