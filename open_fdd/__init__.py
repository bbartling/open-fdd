"""
open-fdd — Fault Detection and Diagnostics for HVAC systems.

Config-driven, pandas-based. Define fault rules in YAML, run against DataFrames.

Example:
    from open_fdd import RuleRunner
    runner = RuleRunner(rules_path="path/to/rules")
    df_result = runner.run(df)
"""

from open_fdd.engine import RuleRunner

__version__ = "2.3.0"

__all__ = ["RuleRunner", "__version__"]
