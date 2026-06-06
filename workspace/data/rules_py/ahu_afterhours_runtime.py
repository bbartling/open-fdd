"""AHU fan after hours with satisfied zones (Arrow)."""

from open_fdd.arrow_runtime.cookbook import after_hours_fan_satisfied_mask


def apply_faults_arrow(table, cfg, context=None):
    return after_hours_fan_satisfied_mask(table, cfg)
