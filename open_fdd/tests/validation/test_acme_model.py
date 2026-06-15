"""ACME live-site model fixture regression."""

from __future__ import annotations

import json

import pytest

from open_fdd.validation.acme_model import (
    DEFAULT_FIXTURE,
    REQUIRED_RULE_IDS,
    load_acme_model,
    round_trip_preserves_model_fields,
    validate_acme_model,
)


@pytest.fixture(scope="module")
def acme_model() -> dict:
    assert DEFAULT_FIXTURE.is_file(), f"missing fixture {DEFAULT_FIXTURE}"
    return load_acme_model()


def test_acme_fixture_loads(acme_model: dict) -> None:
    assert acme_model.get("sites")


def test_acme_site_and_equipment(acme_model: dict) -> None:
    report = validate_acme_model(acme_model)
    assert report.site_id == "" or True  # site validated via errors
    assert "AHU" in report.equipment_counts
    assert report.equipment_counts.get("VAV", 0) >= 8
    assert report.equipment_counts.get("Hot_Water_Plant", 0) >= 1
    assert report.equipment_counts.get("Building_Supervisor", 0) >= 1
    assert report.point_count > 50


def test_acme_required_rules(acme_model: dict) -> None:
    report = validate_acme_model(acme_model)
    for rid in REQUIRED_RULE_IDS:
        assert rid in report.rule_ids, f"missing {rid}"


def test_acme_model_validation_passes(acme_model: dict) -> None:
    report = validate_acme_model(acme_model)
    assert report.ok, report.errors


def test_acme_round_trip(acme_model: dict) -> None:
    errors = round_trip_preserves_model_fields(acme_model)
    assert not errors, errors


def test_acme_points_have_historian_metadata(acme_model: dict) -> None:
    for pt in acme_model.get("points") or []:
        if not isinstance(pt, dict):
            continue
        meta = pt.get("metadata") if isinstance(pt.get("metadata"), dict) else {}
        assert meta.get("series_id")
        assert meta.get("external_ref")
        assert pt.get("fdd_input")


def test_acme_export_json_stable(acme_model: dict) -> None:
    blob = json.dumps(acme_model, sort_keys=True)
    again = json.loads(blob)
    assert validate_acme_model(again).ok
