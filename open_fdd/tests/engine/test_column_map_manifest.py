"""Manifest and composite column_map resolvers (no rdflib required)."""

import json
from pathlib import Path

import pytest

from open_fdd.engine.column_map_resolver import (
    ColumnMapResolver,
    FirstWinsCompositeResolver,
    ManifestColumnMapResolver,
    load_column_map_manifest,
)


def test_load_column_map_manifest_flat_json(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps(
            {"Supply_Air_Temperature_Sensor": "sat", "Outside_Air_Temperature_Sensor": "oat"}
        ),
        encoding="utf-8",
    )
    assert load_column_map_manifest(p) == {
        "Supply_Air_Temperature_Sensor": "sat",
        "Outside_Air_Temperature_Sensor": "oat",
    }


def test_load_column_map_manifest_wrapped_yaml(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "description: demo\ncolumn_map:\n  sat: col_sa\n  rat: col_ra\n",
        encoding="utf-8",
    )
    assert load_column_map_manifest(p) == {"sat": "col_sa", "rat": "col_ra"}


def test_load_column_map_manifest_missing_file(tmp_path):
    assert load_column_map_manifest(tmp_path / "missing.json") == {}


def test_manifest_resolver_satisfies_protocol(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("a: b\n", encoding="utf-8")
    assert isinstance(ManifestColumnMapResolver(p), ColumnMapResolver)


def test_manifest_resolver_ignores_ttl_path(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("column_map:\n  a: b\n", encoding="utf-8")
    r = ManifestColumnMapResolver(p)
    assert r.build_column_map(ttl_path=tmp_path / "any.ttl") == {"a": "b"}


def test_first_wins_composite_two_manifests(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text(
        "column_map:\n"
        "  Supply_Air_Temperature_Sensor: sat\n"
        "  Outside_Air_Temperature_Sensor: oat\n",
        encoding="utf-8",
    )
    extra = tmp_path / "extra.yaml"
    extra.write_text(
        "column_map:\n"
        "  Supply_Air_Temperature_Sensor: override_should_not_apply\n"
        "  Extra_Logical_Key: extra_col\n",
        encoding="utf-8",
    )
    r = FirstWinsCompositeResolver(
        ManifestColumnMapResolver(base),
        ManifestColumnMapResolver(extra),
    )
    m = r.build_column_map(ttl_path=tmp_path / "ignored.ttl")
    assert m["Supply_Air_Temperature_Sensor"] == "sat"
    assert m["Extra_Logical_Key"] == "extra_col"


def test_first_wins_composite_requires_one_resolver():
    with pytest.raises(ValueError, match="at least one"):
        FirstWinsCompositeResolver()
