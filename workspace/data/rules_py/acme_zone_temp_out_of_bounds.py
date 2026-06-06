"""Acme zone temp out of bounds (Arrow)."""

from open_fdd.arrow_runtime.cookbook import oob_mask


def apply_faults_arrow(table, cfg, context=None):
    return oob_mask(table, cfg)
