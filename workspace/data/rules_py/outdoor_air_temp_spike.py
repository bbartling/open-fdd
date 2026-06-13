"""Outdoor air temperature spike between polls (Arrow, BLD-B)."""

from open_fdd.arrow_runtime.cookbook import rate_of_change_mask
from open_fdd.arrow_runtime.sensor_catalog import cfg_from_profile


def apply_faults_arrow(table, cfg, context=None):
    merged = cfg_from_profile("outdoor_air_temp", cfg)
    return rate_of_change_mask(table, merged)
