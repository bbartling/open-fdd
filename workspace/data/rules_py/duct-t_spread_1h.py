"""Duct-T spread 1h (Arrow)."""

from open_fdd.arrow_runtime.cookbook import spread_1h_mask


def apply_faults_arrow(table, cfg, context=None):
    return spread_1h_mask(table, cfg)
