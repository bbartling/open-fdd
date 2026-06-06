"""
open-fdd — Fault Detection and Diagnostics for HVAC systems.

Config-driven, pandas-based. Define fault rules in YAML, run against DataFrames.
"""

from open_fdd.engine import RuleRunner

__version__ = "3.0.1"

__all__ = ["RuleRunner", "__version__"]
