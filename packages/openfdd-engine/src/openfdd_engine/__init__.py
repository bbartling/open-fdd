"""
Standalone Open-FDD engine package.
"""

from .brick_resolver import resolve_from_ttl
from .runner import RuleRunner, bounds_map_from_rule, load_rule

__all__ = ["RuleRunner", "bounds_map_from_rule", "load_rule", "resolve_from_ttl"]

