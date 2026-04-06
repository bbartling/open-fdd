"""
Config-driven fault detection engine.

Define fault rules in YAML, run them against pandas DataFrames.
"""

from open_fdd.engine.column_map_resolver import (
    ColumnMapResolver,
    FirstWinsCompositeResolver,
    ManifestColumnMapResolver,
    load_column_map_manifest,
)
from open_fdd.engine.runner import RuleRunner, bounds_map_from_rule, load_rule

__all__ = [
    "RuleRunner",
    "bounds_map_from_rule",
    "load_rule",
    "ColumnMapResolver",
    "ManifestColumnMapResolver",
    "FirstWinsCompositeResolver",
    "load_column_map_manifest",
]
