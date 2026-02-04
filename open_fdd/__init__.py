"""
open-fdd — Fault Detection and Diagnostics for HVAC systems.

Config-driven, pandas-based. Define fault rules in YAML, run against DataFrames.

Example:
    from open_fdd import RuleRunner
    runner = RuleRunner("open_fdd/rules")
    df_result = runner.run(df)
"""

from open_fdd.engine import RuleRunner, resolve_from_ttl

__all__ = ["RuleRunner", "resolve_from_ttl"]
