"""Tests for mirrored TTL + local SPARQL on RCx Central."""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio.central.model_sparql_local import (
    TtlGraphError,
    execute_site_sparql,
    load_graph_path,
    run_sparql,
    validate_readonly_sparql,
    validate_site_model,
)
from portfolio.central.model_ttl_mirror import ttl_mirror_status

MINI_TTL = """@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
brick:Site_acme a brick:Site ;
  rdfs:label "Acme" .
brick:AHU_01 a brick:Air_Handling_Unit ;
  brick:isPartOf brick:Site_acme .
brick:VAV_01 a brick:Variable_Air_Volume_Box ;
  brick:isPartOf brick:Site_acme .
"""


@pytest.fixture()
def mini_ttl(tmp_path: Path, monkeypatch) -> Path:
    site_dir = tmp_path / "sites" / "acme" / "model"
    site_dir.mkdir(parents=True)
    path = site_dir / "data_model.ttl"
    path.write_text(MINI_TTL, encoding="utf-8")
    monkeypatch.setenv("OPENFDD_RCX_CENTRAL_DATA", str(tmp_path))
    return path


def test_validate_readonly_sparql_rejects_insert():
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        validate_readonly_sparql("INSERT { ?s ?p ?o } WHERE {}")


def test_load_graph_and_count_ahu(mini_ttl: Path):
    graph = load_graph_path(mini_ttl)
    rows = run_sparql(
        graph,
        """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT (COUNT(?x) AS ?count) WHERE { ?x a brick:Air_Handling_Unit . }""",
    )
    assert rows and rows[0].get("count") == "1"


def test_execute_site_sparql_uses_mirror(mini_ttl: Path):
    out = execute_site_sparql("acme", "PREFIX brick: <https://brickschema.org/schema/Brick#>\nSELECT ?x WHERE { ?x a brick:Variable_Air_Volume_Box . }", sync_if_missing=False)
    assert out["row_count"] == 1
    assert out["query_engine"] == "sparql"


def test_validate_site_model_checks(mini_ttl: Path):
    out = validate_site_model("acme", sync_if_missing=False)
    assert out["ok"] is True
    counts = {c["id"]: c.get("count") for c in out["checks"]}
    assert counts.get("ahu_information") == 1
    assert counts.get("count-vavs") == 1
    assert counts.get("sites") == 1


def test_ttl_mirror_status_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENFDD_RCX_CENTRAL_DATA", str(tmp_path))
    status = ttl_mirror_status("acme")
    assert status["ttl_exists"] is False


def test_load_graph_missing_raises(tmp_path: Path):
    with pytest.raises(TtlGraphError):
        load_graph_path(tmp_path / "missing.ttl")
