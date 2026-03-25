"""
Compatibility namespace for standalone engine API.
"""

from open_fdd.engine.brick_resolver import resolve_from_ttl
from open_fdd.engine.runner import RuleRunner, bounds_map_from_rule, load_rule

__all__ = ["RuleRunner", "bounds_map_from_rule", "load_rule", "resolve_from_ttl"]

