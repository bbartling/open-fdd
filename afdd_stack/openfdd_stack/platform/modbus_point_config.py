"""Normalize and validate Modbus point ``modbus_config`` (API, import, scraper)."""

from __future__ import annotations

from typing import Any, Optional

# Modbus PDU limits; single read typically capped at 125 registers.
_MAX_REGISTERS_PER_READ = 125
_MAX_ADDRESS = 65535

# diy-bacnet-server DecodeLiteral (bacpypes_server/modbus_routes.py)
_ALLOWED_DECODE = frozenset(("raw", "uint16", "int16", "uint32", "int32", "float32"))


def normalize_modbus_config(cfg: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Return a cleaned ``modbus_config`` dict for DB/scraper, or ``None`` if invalid.

    Required: non-empty ``host``, integer ``address`` in range, ``function`` holding|input.
    Optional with defaults: ``port`` 502, ``unit_id`` 1, ``timeout`` 5.0, ``count`` 1.

    If the dict looks like the gateway **batch read** body (top-level ``registers`` list),
    a **single** register object is merged into the flat point shape. Multiple registers
    raise ``ValueError`` with operator-oriented guidance (one DB point per register).
    """
    if not isinstance(cfg, dict):
        return None

    if "registers" in cfg:
        regs = cfg.get("registers")
        if not isinstance(regs, list) or len(regs) == 0:
            return None
        if len(regs) > 1:
            raise ValueError(
                "modbus_config must describe one Modbus register read per point. "
                "The gateway batch request uses registers[] for multiple reads at once; "
                "for a persisted point use a flat object (host, address, count, function, …) "
                "without registers, or add one data-model row per register."
            )
        first = regs[0]
        if not isinstance(first, dict):
            return None
        cfg = {k: v for k, v in cfg.items() if k != "registers"}
        for k, val in first.items():
            cfg[k] = val

    host = str(cfg.get("host") or "").strip()
    if not host:
        return None
    try:
        address = int(cfg["address"])
    except (KeyError, TypeError, ValueError):
        return None
    if address < 0 or address > _MAX_ADDRESS:
        return None

    fn = str(cfg.get("function") or "holding").strip().lower()
    if fn not in ("holding", "input"):
        return None

    try:
        port = int(cfg["port"]) if cfg.get("port") is not None else 502
    except (TypeError, ValueError):
        return None
    if port < 1 or port > 65535:
        return None

    unit_raw = cfg.get("unit_id") if cfg.get("unit_id") is not None else cfg.get("unit")
    try:
        unit_id = int(unit_raw) if unit_raw is not None else 1
    except (TypeError, ValueError):
        return None
    if unit_id < 0 or unit_id > 247:
        return None

    try:
        timeout = float(cfg["timeout"]) if cfg.get("timeout") is not None else 5.0
    except (TypeError, ValueError):
        return None
    if not (0.1 <= timeout <= 120.0):
        return None

    try:
        count = int(cfg["count"]) if cfg.get("count") is not None else 1
    except (TypeError, ValueError):
        return None
    if count < 1 or count > _MAX_REGISTERS_PER_READ:
        return None

    out: dict[str, Any] = {
        "host": host,
        "port": port,
        "unit_id": unit_id,
        "timeout": timeout,
        "address": address,
        "count": count,
        "function": fn,
    }

    dec = cfg.get("decode")
    if dec is not None and dec != "":
        ds = str(dec).strip().lower()
        if ds not in _ALLOWED_DECODE:
            return None
        out["decode"] = ds
        if ds in ("float32", "uint32", "int32") and count < 2:
            return None

    if cfg.get("scale") is not None:
        try:
            out["scale"] = float(cfg["scale"])
        except (TypeError, ValueError):
            return None

    if cfg.get("offset") is not None:
        try:
            out["offset"] = float(cfg["offset"])
        except (TypeError, ValueError):
            return None

    if cfg.get("label") is not None:
        lab = str(cfg["label"]).strip()
        if lab:
            out["label"] = lab[:512]

    return out
