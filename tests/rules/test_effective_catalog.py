"""Deterministic effective catalog serialization and hashes."""

from __future__ import annotations

import json

from open_fdd.catalog import (
    dumps_canonical,
    effective_catalog,
    effective_config_hash,
    rule_catalog_hash,
    sql_registry_hash,
)
from open_fdd.version import CATALOG_SCHEMA_VERSION, manifest


def test_schema_version_and_counts():
    doc = effective_catalog()
    assert doc["schema_version"] == CATALOG_SCHEMA_VERSION
    assert doc["rule_count"] == 59
    assert doc["sql_analytics_count"] == 4
    assert len(doc["rules"]) == 59
    chw = next(r for r in doc["rules"] if r["rule_id"] == "CHW-1")
    assert "chilled-water-supply-temp" in chw["required_roles"]
    assert chw["thresholds"]["min_dt"] == 4.0
    assert chw["confirm_seconds"] == 900
    assert chw["gate"]["kind"] == "hydronic_flow"


def test_hash_stable_and_override_changes_effective_only():
    a = rule_catalog_hash()
    b = rule_catalog_hash()
    assert a == b
    assert len(a) == 64
    assert a == effective_config_hash(None)
    changed = effective_config_hash({"CHW-1": {"min_dt": 6.0}})
    assert changed != a
    doc = effective_catalog(overrides_by_rule={"CHW-1": {"min_dt": 6.0}})
    chw = next(r for r in doc["rules"] if r["rule_id"] == "CHW-1")
    assert chw["thresholds"]["min_dt"] == 6.0
    # defaults-only hash must ignore that call
    assert rule_catalog_hash() == a


def test_canonical_json_rejects_ellipsis_and_is_sorted():
    blob = dumps_canonical(effective_catalog())
    assert "..." not in blob
    assert "\n" not in blob
    parsed = json.loads(blob)
    assert list(parsed.keys()) == sorted(parsed.keys())
    # no default=str leftovers
    assert "Timestamp(" not in blob
    assert "dtype:" not in blob


def test_manifest_wires_hashes():
    doc = manifest()
    assert doc["rule_catalog_hash"] == rule_catalog_hash()
    assert doc["effective_config_hash"] == effective_config_hash()
    assert doc["catalog_schema_version"] == CATALOG_SCHEMA_VERSION
    assert sql_registry_hash()
