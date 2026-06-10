"""Cookbook Recipe 1 — flatline over ~1 hour (Arrow)."""

import pyarrow.compute as pc

from open_fdd.arrow_runtime.cookbook import _unoccupied_mask, flatline_1h_mask


def apply_faults_arrow(table, cfg, context=None):
    mask = flatline_1h_mask(table, cfg)
    if cfg.get("occupied_only"):
        occupied = pc.invert(_unoccupied_mask(table, cfg))
        mask = pc.and_(mask, occupied)
    return mask
