"""Zone temperature out of bounds during occupied hours (Arrow, VAV-C)."""

import pyarrow.compute as pc

from open_fdd.arrow_runtime.cookbook import _unoccupied_mask, oob_mask


def apply_faults_arrow(table, cfg, context=None):
    occupied = pc.invert(_unoccupied_mask(table, cfg))
    return pc.and_(oob_mask(table, cfg), occupied)
