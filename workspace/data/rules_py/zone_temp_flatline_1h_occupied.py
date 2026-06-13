"""Zone temperature flatline during occupied hours (Arrow, VAV-C)."""

import pyarrow.compute as pc

from open_fdd.arrow_runtime.cookbook import _unoccupied_mask, flatline_1h_mask


def apply_faults_arrow(table, cfg, context=None):
    occupied = pc.invert(_unoccupied_mask(table, cfg))
    return pc.and_(flatline_1h_mask(table, cfg), occupied)
