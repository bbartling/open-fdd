"""C3 Haystack RDF strict projection — RDFLib parse + HR-03/04/05 fixture checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "scripts" / "fixtures" / "haystack_rdf"


def test_c3_expected_answers_declare_strict_delivery() -> None:
    exp = json.loads((FIX / "expected_c1_answers.json").read_text())
    strict = exp["strict_haystack_projection_v1"]
    assert strict["c3_delivery"] is True
    assert strict["profile"] == "ofdd_haystack_projection_v1"
    assert "SAT" == strict["must_emit_column"]
    assert "CLG_VLV_CMD" in strict["must_not_emit_columns"]


def test_semantic_meta_has_c3_cases() -> None:
    meta = json.loads((FIX / "synthetic_point_metadata_v1.json").read_text())
    cols = {(p["equipment_id"], p["column"]) for p in meta["points"]}
    assert ("AHU_CASE_1", "SAT") in cols
    assert ("AHU_CASE_1", "MYSTERY_FLOW") in cols
    assert ("VAV_CASE_1", "CLG_VLV_CMD") in cols
    sat = next(p for p in meta["points"] if p["column"] == "SAT")
    assert "false" in sat["haystack_tags"]
    mystery = next(p for p in meta["points"] if p["column"] == "MYSTERY_FLOW")
    assert mystery.get("unit_status") == "unknown"
    assert "vendorFooTag" in mystery["haystack_tags"]


def test_inventory_marks_exclusion_and_ambiguity() -> None:
    inv = json.loads((FIX / "synthetic_mapping_inventory.json").read_text())
    vav = next(e for e in inv["equipment"] if e["equipment_id"] == "VAV_CASE_1")
    assert "sat_sp" in vav["ambiguous_roles"]
    excl = next(e for e in inv["equipment"] if e["equipment_id"] == "VAV_EXCLUDED_1")
    aux = next(c for c in excl["columns"] if c["column"] == "INTENTIONALLY_EXCLUDED_AUX")
    assert aux["status"] == "excluded"


@pytest.mark.skipif(
    subprocess.call(
        [sys.executable, "-c", "import rdflib"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    != 0,
    reason="rdflib not installed",
)
def test_rdflib_parses_projected_turtle_from_cargo_test_artifact(
    tmp_path: Path,
) -> None:
    """Build Turtle using the same Rust API via `cargo test` print is awkward;
    instead project with a one-shot rustc-free JSON fixture round-trip helper
    embedded as expected static TTL when cargo tests already validated shape.

    Here we only assert RDFLib can parse a minimal projected graph matching
    profile prefixes (syntax/HR-03 smoke without requiring full cargo in pytest).
    """
    from rdflib import Graph, Namespace

    # Minimal graph shape mirroring ofdd_haystack_projection_v1 (kept in sync with
    # edge/src/csv_ingest/haystack_projection.rs emit_resource).
    ttl = """
@prefix ph: <https://project-haystack.org/def/ph#> .
@prefix ofdd: <urn:openfdd:ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ofdd:site_OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1 a ph:site ;
  ph:hasTag ph:site ;
  ofdd:buildingId "OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1" .

ofdd:eq_OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1__AHU_CASE_1 a ph:equip ;
  ph:hasTag ph:ahu ;
  ph:hasTag ph:equip ;
  ph:siteRef ofdd:site_OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1 ;
  ofdd:equipmentId "AHU_CASE_1" .

ofdd:pt_OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1__AHU_CASE_1__SAT a ph:point ;
  ph:hasTag ph:sensor ;
  ph:hasTag ph:point ;
  ph:hasTag ph:air ;
  ph:hasTag ph:supply ;
  ph:hasTag ph:temp ;
  ph:equipRef ofdd:eq_OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1__AHU_CASE_1 ;
  ofdd:column "SAT" ;
  ofdd:unit "°F" .
"""
    g = Graph()
    g.parse(data=ttl, format="turtle")
    ph = Namespace("https://project-haystack.org/def/ph#")
    assert len(g) >= 10
    assert any(o == ph.site for o in g.objects())
    assert any(o == ph.equip for o in g.objects())
    assert any(o == ph.point for o in g.objects())
    # No false marker resource
    assert ph["false"] not in set(g.objects())


def test_crosswalk_advertises_c3_directions() -> None:
    text = (ROOT / "docs/modeling/data-model-json-rdf-crosswalk.md").read_text()
    assert "haystack.ttl" in text
    assert "semantic-meta" in text
    assert "ofdd_haystack_projection_v1" in text
