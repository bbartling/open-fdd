"""
Config-driven fault detection engine.

Define fault rules in YAML, run them against pandas DataFrames.
"""

from open_fdd.engine.brick_resolver import resolve_from_ttl
from open_fdd.engine.runner import RuleRunner

__all__ = ["RuleRunner", "resolve_from_ttl"]
