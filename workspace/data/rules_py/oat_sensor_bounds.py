"""Outdoor air temperature bounds (Arrow, BLD-B)."""

from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask


def apply_faults_arrow(table, cfg, context=None):
    return sensor_bounds_mask(table, "outdoor_air_temp", cfg)
