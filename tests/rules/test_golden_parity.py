"""Shared golden fixtures: pandas always; do not claim 59/59 full DF parity."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from golden_dual_compare import run_fixture  # noqa: E402
INV = ROOT / "sql_rules" / "generated" / "parity_inventory.yaml"


def test_seeded_goldens_match_pandas():
    inv = yaml.safe_load(INV.read_text(encoding="utf-8"))
    ran = 0
    for c in inv["concepts"]:
        if c.get("kind") != "diagnostic":
            continue
        for fx in c.get("proof_fixtures") or []:
            if not fx.get("oracle_seed"):
                continue
            run_fixture(ROOT / fx["path"])
            ran += 1
    assert ran >= 8


def test_fc7_not_claimed_full_parity():
    inv = yaml.safe_load(INV.read_text(encoding="utf-8"))
    fc7 = next(c for c in inv["concepts"] if c["canonical_id"] == "FC7")
    assert fc7["parity_level"] == "concept_only"
    assert fc7["difference_class"] == "missing_implementation"
