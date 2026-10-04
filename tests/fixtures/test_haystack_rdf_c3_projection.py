"""C3 Haystack RDF strict projection — independent RDFLib parse of product bytes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "scripts" / "fixtures" / "haystack_rdf"
GENERATED_TTL = FIX / "generated" / "c3_projection.ttl"
DEFS_TTL = FIX / "defs" / "defs.ttl"
DEFS_PIN = FIX / "defs" / "defs.pin.json"


def test_c3_expected_answers_declare_strict_delivery() -> None:
    exp = json.loads((FIX / "expected_c1_answers.json").read_text())
    strict = exp["strict_haystack_projection_v1"]
    assert strict["c3_delivery"] is True
    assert strict["profile"] == "ofdd_haystack_projection_v1"
    assert strict["defs_pin"] == "haystack-defs-ttl-4.0.0"
    assert "SAT" == strict["must_emit_column"]
    assert "CLG_VLV_CMD" in strict.get("must_emit_columns_also", [])


def test_defs_pin_artifact_present() -> None:
    pin = json.loads(DEFS_PIN.read_text())
    assert pin["defs_pin"] == "haystack-defs-ttl-4.0.0"
    assert DEFS_TTL.is_file()
    import hashlib

    digest = hashlib.sha256(DEFS_TTL.read_bytes()).hexdigest()
    assert digest == pin["sha256"]


def test_semantic_meta_has_c3_cases() -> None:
    meta = json.loads((FIX / "synthetic_point_metadata_v1.json").read_text())
    cols = {(p["equipment_id"], p["column"]) for p in meta["points"]}
    assert ("AHU_CASE_1", "SAT") in cols
    assert ("AHU_CASE_1", "MYSTERY_FLOW") in cols
    assert ("VAV_CASE_1", "CLG_VLV_CMD") in cols


def test_inventory_marks_exclusion_and_ambiguity() -> None:
    inv = json.loads((FIX / "synthetic_mapping_inventory.json").read_text())
    vav = next(e for e in inv["equipment"] if e["equipment_id"] == "VAV_CASE_1")
    assert "sat_sp" in vav["ambiguous_roles"]
    excl = next(e for e in inv["equipment"] if e["equipment_id"] == "VAV_EXCLUDED_1")
    aux = next(c for c in excl["columns"] if c["column"] == "INTENTIONALLY_EXCLUDED_AUX")
    assert aux["status"] == "excluded"


def _ensure_product_ttl() -> Path:
    """Prefer committed/CI-generated artifact; otherwise build via cargo bin."""
    env_path = os.environ.get("OPENFDD_HAYSTACK_C3_TTL")
    if env_path:
        p = Path(env_path)
        if not p.is_file():
            raise FileNotFoundError(f"OPENFDD_HAYSTACK_C3_TTL missing: {p}")
        return p
    if GENERATED_TTL.is_file() and GENERATED_TTL.stat().st_size > 0:
        return GENERATED_TTL
    # Generate from the Rust exporter (actual product bytes).
    cmd = [
        "cargo",
        "run",
        "-q",
        "-p",
        "open_fdd_edge_prototype",
        "--bin",
        "haystack_c3_export_fixture",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    if not GENERATED_TTL.is_file():
        raise FileNotFoundError(f"exporter did not write {GENERATED_TTL}")
    return GENERATED_TTL


@pytest.mark.skipif(
    subprocess.call(
        [sys.executable, "-c", "import rdflib"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    != 0,
    reason="rdflib not installed",
)
def test_rdflib_parses_actual_exporter_bytes_against_pinned_defs() -> None:
    from rdflib import Graph, Namespace, RDF, URIRef

    ttl_path = _ensure_product_ttl()
    g = Graph()
    g.parse(ttl_path.as_posix(), format="turtle")

    defs = Graph()
    defs.parse(DEFS_TTL.as_posix(), format="turtle")

    ph = Namespace("https://project-haystack.org/def/ph/4.0.0#")
    ph_iot = Namespace("https://project-haystack.org/def/phIoT/4.0.0#")
    ph_sci = Namespace("https://project-haystack.org/def/phScience/4.0.0#")

    assert len(g) >= 10
    assert (None, RDF.type, ph_iot.site) in g
    assert (None, RDF.type, ph_iot.equip) in g
    assert (None, RDF.type, ph_iot.point) in g
    assert (None, ph.hasTag, ph_iot.sensor) in g
    assert (None, ph.hasTag, ph_sci.air) in g
    assert (None, ph.unit, None) in g

    # Every standard object IRI used as rdf:type or ph:hasTag must exist in pinned defs.
    for _s, p, o in g.triples((None, None, None)):
        if p not in (RDF.type, ph.hasTag):
            continue
        if not isinstance(o, URIRef):
            continue
        iri = str(o)
        if not iri.startswith("https://project-haystack.org/def/"):
            continue
        assert (o, None, None) in defs or (None, None, o) in defs, f"missing def for {iri}"

    # Ambiguous + excluded columns remain as semantic points.
    text = ttl_path.read_text(encoding="utf-8")
    assert "CLG_VLV_CMD" in text or "fddSelection" in text
    assert "fddExcluded" in text or "INTENTIONALLY_EXCLUDED_AUX" in text
    # Unversioned wrong NS must not appear.
    assert "https://project-haystack.org/def/ph#" not in text.replace(
        "https://project-haystack.org/def/ph/4.0.0#", ""
    )


def test_handwritten_turtle_syntax_smoke_only() -> None:
    """Labeled syntax smoke — does NOT close HR-03/04 or #1001."""
    pytest.importorskip("rdflib")
    from rdflib import Graph

    ttl = """
@prefix ph: <https://project-haystack.org/def/ph/4.0.0#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
@prefix ofdd: <urn:openfdd:ns#> .
ofdd:smoke a phIoT:site ;
  ph:hasTag phIoT:site ;
  ofdd:buildingId "SMOKE" .
"""
    g = Graph()
    g.parse(data=ttl, format="turtle")
    assert len(g) >= 2


def test_crosswalk_advertises_c3_directions() -> None:
    text = (ROOT / "docs/modeling/data-model-json-rdf-crosswalk.md").read_text()
    assert "haystack.ttl" in text
    assert "semantic-meta" in text
    assert "ofdd_haystack_projection_v1" in text
