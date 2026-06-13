"""Outdoor air temperature flatline (Arrow, BLD-B)."""

from open_fdd.arrow_runtime.cookbook import sensor_flatline_mask


def apply_faults_arrow(table, cfg, context=None):
    return sensor_flatline_mask(table, "outdoor_air_temp", cfg)
