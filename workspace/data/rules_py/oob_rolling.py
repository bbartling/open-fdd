"""Cookbook Recipe 6 — out of bounds on rolling mean (Arrow)."""

import pyarrow.compute as pc

from open_fdd.arrow_runtime.cookbook import _unoccupied_mask, oob_mask


def apply_faults_arrow(table, cfg, context=None):
    mask = oob_mask(table, cfg)
    if cfg.get("occupied_only"):
        occupied = pc.invert(_unoccupied_mask(table, cfg))
        mask = pc.and_(mask, occupied)
    return mask
