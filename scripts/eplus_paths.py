"""Shared artifact paths for E+ dump, clustering, and synthetic golden fixtures.

Prefer ``reports/eplus-dump/`` for new work. Legacy ``reports/wattlab-parity/`` paths
remain as fallbacks so existing benches and gitignored fixtures keep working.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EPLUS_DUMP_ROOT = Path(
    os.environ.get("EPLUS_DUMP_ROOT", ROOT / "reports/eplus-dump")
).resolve()
LEGACY_PARITY_ROOT = ROOT / "reports/wattlab-parity"


def parity_root() -> Path:
    """Active reports root — new name when present, else legacy."""
    if EPLUS_DUMP_ROOT.is_dir():
        return EPLUS_DUMP_ROOT
    if LEGACY_PARITY_ROOT.is_dir():
        return LEGACY_PARITY_ROOT
    return EPLUS_DUMP_ROOT


def synthetic_fixture_dir() -> Path:
    for base in (EPLUS_DUMP_ROOT, LEGACY_PARITY_ROOT):
        p = base / "fixtures/synthetic_59/openfdd_synthetic_59_rule_fixture_v1"
        if p.is_dir():
            return p
    return LEGACY_PARITY_ROOT / "fixtures/synthetic_59/openfdd_synthetic_59_rule_fixture_v1"


def synthetic_artifacts_dir() -> Path:
    return parity_root() / "artifacts/synthetic_59"


def clustering_artifacts_dir(building_id: str) -> Path:
    return parity_root() / "artifacts" / building_id / "clustering"
