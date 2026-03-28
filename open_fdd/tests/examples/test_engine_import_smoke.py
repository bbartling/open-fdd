"""Minimal checks for engine-only / PyPI installs (`pip install open-fdd`).

Example notebooks are not executed in CI; integrators run them locally. This file
only verifies the public engine API imports without jupyter/nbformat.
"""

from __future__ import annotations


def test_engine_rule_runner_import() -> None:
    from open_fdd.engine import RuleRunner

    assert RuleRunner is not None


def test_engine_public_exports() -> None:
    from open_fdd.engine import (
        RuleRunner,
        bounds_map_from_rule,
        load_rule,
        resolve_from_ttl,
    )

    assert callable(load_rule)
    assert callable(resolve_from_ttl)
    assert callable(bounds_map_from_rule)
