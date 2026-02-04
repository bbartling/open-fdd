"""
Config-driven fault detection engine.

Define fault rules in YAML, run them against pandas DataFrames.
"""

from open_fdd.engine.brick_resolver import resolve_from_ttl
from open_fdd.engine.runner import RuleRunner, bounds_map_from_rule, load_rule

__all__ = ["RuleRunner", "bounds_map_from_rule", "load_rule", "resolve_from_ttl"]
