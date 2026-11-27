"""The package loads roles/openfdd-roles.json (1.1.0-draft.1) and names rule inputs from it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_fdd.nf.model import column_for
from open_fdd.point_roles import (
    VERSION,
    load_vocabulary,
    pandas_column,
    resolve,
    role_names,
    roles_path,
    rule_input_names,
    unit_local_name,
    unit_local_names,
    validate_vocabulary,
)

ROOT = Path(__file__).resolve().parents[1]


def test_vocabulary_version_and_units():
    doc = load_vocabulary()
    assert doc["version"] == VERSION == "1.1.0-draft.1"
    assert validate_vocabulary(doc) == []
    assert "discharge_air_temperature" in role_names()
    assert "outdoor_air_intake_temperature" in rule_input_names()
    assert unit_local_names()[0] == "DEG_C"
    assert "L-PER-SEC" in unit_local_names()
    assert unit_local_name("unit:PA") == "PA" and unit_local_name(None) is None
    for rec in doc["roles"]:
        if rec["unit"] is not None:
            assert unit_local_name(rec["unit"]) in unit_local_names()


def test_legacy_keys_resolve_and_hyphenated_columns_do_not_replace_the_role_name():
    assert resolve("sat") == "discharge_air_temperature"
    assert resolve("discharge-air-temp") == "discharge_air_temperature"
    assert resolve("discharge_air_temperature") == "discharge_air_temperature"
    assert resolve("oa_t") == "outdoor_air_intake_temperature"
    assert resolve("not_a_role") is None
    assert resolve("cooling_valve_position") == "cooling_valve_position"
    assert resolve("outside_air_damper_position") is None
    assert pandas_column("discharge_air_temperature") == "discharge-air-temp"
    assert pandas_column("sat") == "discharge-air-temp"
    assert pandas_column("discharge-air-temp") == "discharge-air-temp"
    assert column_for("fan_status") == "fan-status"
    assert column_for("supply_fan_operating_status") == "fan-status"
    listed = set(role_names())
    assert "discharge-air-temp" not in listed
    assert "discharge_air_temperature" in listed


def test_packaged_copy_matches_the_repo_file():
    repo = ROOT / "roles" / "openfdd-roles.json"
    packaged = ROOT / "open_fdd" / "data" / "openfdd-roles.json"
    assert roles_path() == repo
    assert packaged.read_bytes() == repo.read_bytes()


def test_validate_rejects_a_bad_version():
    doc = json.loads((ROOT / "roles" / "openfdd-roles.json").read_text(encoding="utf-8"))
    doc["version"] = "1.0.0-draft.1"
    problems = validate_vocabulary(doc)
    assert any("version" in p for p in problems)


def test_duckdb_helpers_in_the_pack_match_the_sql_file():
    pack = json.loads((ROOT / "nf-app" / "rules" / "pack-postgres.json").read_text(encoding="utf-8"))
    helpers = (ROOT / "sql" / "fdd" / "duckdb" / "duckdb_helpers.sql").read_text(encoding="utf-8")
    assert pack["duckdb_helpers_sql"] == helpers


def test_sql_helpers_accept_duckdb_and_timescale():
    from open_fdd.analytics.sql_anomaly import normalize_engine
    from open_fdd.analytics.sql_runtime import render_runtime_sql

    assert normalize_engine("timescale") == "postgres"
    assert normalize_engine("duckdb") == "duckdb"
    with pytest.raises(ValueError):
        normalize_engine("mysql")
    pg = render_runtime_sql("postgres")
    assert render_runtime_sql("timescale") == pg
    assert "epoch_ms" in render_runtime_sql("duckdb")


def test_cli_help_names_the_duckdb_engine_and_the_role(capsys):
    from open_fdd.analytics.anomaly.cli import main as anomaly_main
    from open_fdd.ml.cli import main as ml_main

    assert anomaly_main(["screen", "--help"]) == 0
    text = capsys.readouterr().out
    assert "--sql-engine" in text and "duckdb" in text and "timescale" in text
    assert ml_main(["make-folder", "--help"]) == 0
    ml = capsys.readouterr().out
    assert "discharge_air_temperature" in ml
    assert "Legacy" in ml
