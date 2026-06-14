"""Shared helpers for bench FDD rules (BACnet 5007 + Niagara bench9065)."""

from __future__ import annotations

from typing import Any

import pyarrow.compute as pc

from open_fdd.arrow_runtime.cookbook import flatline_1h_mask, oob_mask, spread_1h_mask

__all__ = [
    "flatline_1h_mask",
    "oob_mask",
    "spread_1h_mask",
    "bound_column",
    "cast_column",
    "kit_fmt",
    "kit_value_stats",
]


def bound_column(cfg: dict[str, Any] | None, default: str) -> str:
    """Historian column from FDD runner bindings (``cfg['value_column']``) or rule default."""
    raw = (cfg or {}).get("value_column")
    col = str(raw or default).strip()
    return col or default


def cast_column(table, cfg: dict[str, Any] | None, default: str):
    col = bound_column(cfg, default)
    return pc.cast(table[col], "float64"), col


def kit_fmt(scalar) -> str:
    v = scalar.as_py() if scalar is not None else None
    return "nan" if v is None else f"{v:.2f}"


def kit_value_stats(table, cfg: dict[str, Any] | None, default: str) -> str:
    vals, col = cast_column(table, cfg, default)
    print(
        f"rows={table.num_rows} column={col} "
        f"min={kit_fmt(pc.min(vals))} max={kit_fmt(pc.max(vals))} "
        f"mean={kit_fmt(pc.mean(vals))}"
    )
    return col
