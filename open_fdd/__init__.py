"""
open-fdd — Fault Detection and Diagnostics for HVAC systems.

Config-driven, pandas-based. Define fault rules in YAML, run against DataFrames.

Example:
    from open_fdd import RuleRunner
    runner = RuleRunner(rules_path="path/to/rules")
    df_result = runner.run(df)
"""

from open_fdd.engine import RuleRunner

__version__ = "2.3.1"

__all__ = ["GUI", "RuleRunner", "__version__"]


def __getattr__(name: str):
    if name == "GUI":
        from open_fdd.desktop import GUI

        return GUI
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
