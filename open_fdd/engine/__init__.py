"""
Config-driven fault detection engine.

Define fault rules in YAML, run them against pandas DataFrames.
"""

from open_fdd.engine.runner import RuleRunner

__all__ = ["RuleRunner"]
