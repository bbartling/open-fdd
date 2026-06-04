"""Open-FDD local BACnet device name and instance — shared defaults for all deployments."""

from __future__ import annotations

import os
import re

# Professional head-end identity (no hostname suffix).
DEFAULT_BACNET_DEVICE_NAME = "OpenFDD"
DEFAULT_BACNET_INSTANCE_ID = 599999

_NAME_MAX_LEN = 64
_INSTANCE_MIN = 0
_INSTANCE_MAX = 4194302


def normalize_bacnet_device_name(raw: str | None) -> str:
    """BACnet objectName for the local Device (alphanumeric + limited punctuation)."""
    text = (raw or "").strip()
    if not text:
        text = DEFAULT_BACNET_DEVICE_NAME
    # Collapse whitespace; BACnet names are often single-token on supervisors.
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^A-Za-z0-9._-]", "", text)
    return (text or DEFAULT_BACNET_DEVICE_NAME)[:_NAME_MAX_LEN]


def normalize_bacnet_instance_id(raw: str | int | None) -> int:
    try:
        value = int(str(raw).strip()) if raw is not None and str(raw).strip() else DEFAULT_BACNET_INSTANCE_ID
    except (TypeError, ValueError):
        value = DEFAULT_BACNET_INSTANCE_ID
    return max(_INSTANCE_MIN, min(_INSTANCE_MAX, value))


def device_name_from_cfg(cfg: dict[str, str]) -> str:
    env = os.environ.get("OFDD_BACNET_DEVICE_NAME", "").strip()
    raw = env or str(cfg.get("BACNET_NAME") or "").strip() or None
    return normalize_bacnet_device_name(raw)


def instance_id_from_cfg(cfg: dict[str, str]) -> int:
    env = os.environ.get("OFDD_BACNET_INSTANCE", "").strip()
    raw = env or str(cfg.get("BACNET_INSTANCE") or "").strip() or None
    return normalize_bacnet_instance_id(raw)


def apply_device_identity_defaults(cfg: dict[str, str]) -> dict[str, str]:
    """Ensure commission.env / env keys resolve to normalized name + instance strings."""
    out = dict(cfg)
    out["BACNET_NAME"] = device_name_from_cfg(out)
    out["BACNET_INSTANCE"] = str(instance_id_from_cfg(out))
    return out
