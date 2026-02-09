"""Tests for platform rules loader (hot-reload)."""

from pathlib import Path

import pytest

from open_fdd.platform.rules_loader import HotReloadRules, _rules_dir_hash


def test_rules_dir_hash(tmp_path):
    """Hash changes when YAML content changes."""
    (tmp_path / "r1.yaml").write_text("name: foo\n")
    h1 = _rules_dir_hash(tmp_path)
    (tmp_path / "r1.yaml").write_text("name: bar\n")
    h2 = _rules_dir_hash(tmp_path)
    assert h1 != h2


def test_rules_dir_hash_empty(tmp_path):
    """Empty dir returns empty hash."""
    assert _rules_dir_hash(tmp_path) == ""


def test_hot_reload_rules(tmp_path):
    """HotReloadRules returns rules and reloads on change."""
    rule = """
name: test_rule
type: expression
flag: test_flag
inputs:
  x: {column: x}
params: {}
expression: "x > 0"
"""
    (tmp_path / "rule.yaml").write_text(rule)
    loader = HotReloadRules(tmp_path)
    rules = loader.rules
    assert len(rules) >= 1
    assert rules[0].get("name") == "test_rule"

    # Change file
    rule2 = rule.replace("test_rule", "test_rule2")
    (tmp_path / "rule.yaml").write_text(rule2)
    rules2 = loader.rules
    assert rules2[0].get("name") == "test_rule2"
