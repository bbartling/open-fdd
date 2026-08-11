"""Parity inventory contract: 59 diagnostics, 4 SQL analytics, no alias padding."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
INV_YAML = ROOT / "sql_rules" / "generated" / "parity_inventory.yaml"
INV_JSON = ROOT / "sql_rules" / "generated" / "parity_inventory.json"

REQUIRED = {
    "rule_id",
    "title",
    "equipment_types",
    "required_roles",
    "optional_roles",
    "operational_proof_roles",
    "default_thresholds",
    "pandas_implementation",
    "datafusion_sql_implementation",
    "documentation_link",
    "test_coverage",
    "parity_status",
    "known_semantic_differences",
    "difference_class",
}


def test_inventory_files_exist_and_agree():
    assert INV_YAML.is_file()
    assert INV_JSON.is_file()
    y = yaml.safe_load(INV_YAML.read_text(encoding="utf-8"))
    j = json.loads(INV_JSON.read_text(encoding="utf-8"))
    assert y["schema_version"] == "parity-inventory-v2"
    assert y["counts"] == j["counts"]
    assert y["counts"]["pandas_diagnostics"] == 59
    assert y["counts"]["sql_analytics"] == 59 - 55  # 4
    assert y["counts"]["sql_analytics"] == 4
    assert y["counts"]["sql_registry"] == 63
    assert "59" in y["count_explanation"] and "63" in y["count_explanation"]


def test_matrix_has_required_columns_and_true_counts():
    inv = yaml.safe_load(INV_YAML.read_text(encoding="utf-8"))
    matrix = inv["matrix"]
    assert len(matrix) == 63
    diagnostics = [r for r in matrix if r["pandas_implementation"]]
    analytics = [r for r in matrix if r["pandas_implementation"] is None]
    assert len(diagnostics) == 59
    assert len(analytics) == 4
    for row in matrix:
        assert REQUIRED <= set(row)
    aliases = set(inv["aliases_index"])
    assert "SV-SLEW" in aliases
    assert "FC13" in aliases
    assert "excess_runtime" in aliases
    # Aliases are not extra executable rules
    ids = [r["rule_id"] for r in diagnostics]
    assert "SV-SLEW" not in ids
    assert "excess_runtime" not in ids


def test_known_gaps_classified():
    inv = yaml.safe_load(INV_YAML.read_text(encoding="utf-8"))
    by = {r["rule_id"]: r for r in inv["matrix"]}
    assert by["CHW-1"]["difference_class"] in {"none", "semantic_gap"}
    assert by["SCHED-247"]["difference_class"] in {"none", "semantic_gap"}
    assert by["FC7"]["difference_class"] == "missing_implementation"
    assert by["FAN-RUNTIME-HOURS"]["difference_class"] == "intentional_non_applicability"
