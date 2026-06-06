"""Bench OA-T flatline 1h (Arrow)."""

from open_fdd.arrow_runtime.cookbook import flatline_1h_mask


def apply_faults_arrow(table, cfg, context=None):
    return flatline_1h_mask(table, cfg)
