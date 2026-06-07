"""Arrow-native Rule Lab templates and examples."""

from __future__ import annotations

ARROW_RULE_HEADER = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
"""

DEFAULT_ARROW_RULE = '''"""Simple threshold — edit VALUE_COLUMN and MAX_TEMP constants."""

import pyarrow.compute as pc

VALUE_COLUMN = "zone_temp"
MAX_TEMP = 75.0


def _kit_value_stats(table):
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    print(
        f"rows={table.num_rows} column={VALUE_COLUMN} "
        f"min={pc.min(vals).as_py():.2f} max={pc.max(vals).as_py():.2f} "
        f"mean={pc.mean(vals).as_py():.2f}"
    )


def apply_faults_arrow(table, cfg, context=None):
    _kit_value_stats(table)
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    return pc.greater(vals, MAX_TEMP)
'''

ARROW_TEMPLATES: list[dict[str, str]] = [
    {
        "id": "threshold",
        "label": "Simple threshold",
        "code": """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
""",
    },
    {
        "id": "fan_no_airflow",
        "label": "Fan commanded but no airflow",
        "code": """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    fan_on = pc.greater(table["fan_cmd"], cfg.get("fan_on_threshold", 0.5))
    low_airflow = pc.less(table["airflow_cfm"], cfg["min_airflow_cfm"])
    return pc.and_(fan_on, low_airflow)
""",
    },
    {
        "id": "economizer",
        "label": "Economizer not opening",
        "code": """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    oat_good = pc.less(table["outside_air_temp"], cfg["economizer_oat_limit"])
    cooling = pc.greater(table["cooling_cmd"], cfg.get("cooling_threshold", 0.5))
    damper_low = pc.less(table["oa_damper_cmd"], cfg["min_oa_damper_cmd"])
    return pc.and_(pc.and_(oat_good, cooling), damper_low)
""",
    },
    {
        "id": "heat_cool_simultaneous",
        "label": "Heating and cooling simultaneously",
        "code": """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    heating = pc.greater(table["heat_cmd"], cfg.get("heat_threshold", 0.1))
    cooling = pc.greater(table["cool_cmd"], cfg.get("cool_threshold", 0.1))
    return pc.and_(heating, cooling)
""",
    },
    {
        "id": "sensor_range",
        "label": "Sensor out of range",
        "code": """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    too_low = pc.less(table["sensor_value"], cfg["min_value"])
    too_high = pc.greater(table["sensor_value"], cfg["max_value"])
    return pc.or_(too_low, too_high)
""",
    },
]

LEGACY_MIGRATION_MESSAGE = (
    "This is a legacy row rule. Convert it to apply_faults_arrow(table, cfg, context=None) "
    "for the Arrow-native runtime."
)
