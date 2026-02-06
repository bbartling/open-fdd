"""
Re-export Brick resolver utilities for backward compatibility.

Prefer: from open_fdd.engine.brick_resolver import resolve_from_ttl, get_equipment_types_from_ttl
"""

from open_fdd.engine.brick_resolver import (
    resolve_from_ttl,
    get_equipment_types_from_ttl,
)

__all__ = ["resolve_from_ttl", "get_equipment_types_from_ttl"]
