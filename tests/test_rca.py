"""Tests for open_fdd.rca: RDF topology traversal, evidence, ranking, and CLI."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")

from datetime import UTC

from open_fdd.rca import (
    DataFrameEvidenceCollector,
    DataQualityEvidence,
    FaultEvidence,
    InMemoryEvidenceCollector,
    PointDeviation,
    SqlEvidenceCollector,
    analyze_rca,
    load_graph,
    report_to_dict,
    report_to_markdown,
)
from open_fdd.rca.cli import main as rca_main
from open_fdd.rca.evidence import parse_utc

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PLANT_TTL = ROOT / "open_fdd" / "rca" / "data" / "example_plant.ttl"


def test_example_plant_ahu_ranks_root_cause_for_two_unhappy_zones():
    graph = load_graph(EXAMPLE_PLANT_TTL)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(
                equipment_id="ahu-1",
                rule_id="SAT-HIGH",
                start=parse_utc("2026-11-24T10:00:00Z"),
                end=parse_utc("2026-11-24T12:00:00Z"),
                p_real=0.92,
                p_false_positive=0.04,
                confidence_label="likely_real",
            ),
            FaultEvidence(
                equipment_id="vav-1",
                rule_id="AIRFLOW-LOW",
                start=parse_utc("2026-11-24T10:10:00Z"),
                end=parse_utc("2026-11-24T12:00:00Z"),
                p_real=0.10,
                p_false_positive=0.86,
                confidence_label="likely_false_positive",
            ),
            FaultEvidence(
                equipment_id="zone-1",
                rule_id="ZNT-HIGH",
                start=parse_utc("2026-11-24T10:15:00Z"),
                end=parse_utc("2026-11-24T12:00:00Z"),
            ),
            FaultEvidence(
                equipment_id="zone-2",
                rule_id="ZNT-HIGH",
                start=parse_utc("2026-11-24T10:20:00Z"),
                end=parse_utc("2026-11-24T12:00:00Z"),
            ),
        ],
        point_deviations=[
            PointDeviation(
                equipment_id="ahu-1",
                role="discharge-air-temp",
                value_si=18.5,
                setpoint_si=13.0,
                unit="degC",
                timestamp=parse_utc("2026-11-24T10:30:00Z"),
            )
        ],
    )

    report = analyze_rca(graph, collector)
    traces = {t.symptom_equipment: t for t in report.traces}
    assert set(traces) == {"zone-1", "zone-2"}

    for z in ("zone-1", "zone-2"):
        tr = traces[z]
        assert tr.unknown_upstream is False
        assert tr.upstream_status == "traced"
        assert tr.candidates[0].equipment_id == "ahu-1"
        assert tr.candidates[0].rule_id == "SAT-HIGH"
        assert tr.candidates[0].downstream_symptoms_explained == 2
        assert tr.candidates[0].cause_chain[0] == "ahu-1"
        assert tr.candidates[0].cause_chain[-1] == z
        assert tr.candidates[0].relations
        assert all(rel.startswith("s223:") for rel in tr.candidates[0].relations)

    ahu = graph.resolve_node("ahu-1")
    assert ahu is not None
    assert "discharge_air_temperature" in ahu.property_roles
    assert "discharge_air_temperature_setpoint" in ahu.property_roles
    zone_walk = graph.traverse_upstream("zone-1")
    walked = [hop.node.node_id for hop in zone_walk.ancestors]
    assert "vav-1" in walked and "space-1" not in walked
    assert not any(
        edge.predicate == "s223:hasDomainSpace"
        for edge_list in graph.upstream_edges.values()
        for edge in edge_list
    )
    plant = EXAMPLE_PLANT_TTL.read_text(encoding="utf-8")
    assert "owl:imports <http://data.ashrae.org/standard223/1.0/model/all>" in plant
    assert "s223:DomainSpace" in plant
    assert "s223:hasDomainSpace" in plant
    assert "https://project-haystack.org/def/phIoT/>" not in plant
    assert "https://project-haystack.org/def/ph/>" not in plant
    assert "/4.0.0#" in plant

    # False positive on vav-1 is down-weighted well below ahu-1
    vav_cand = next(c for c in traces["zone-1"].candidates if c.equipment_id == "vav-1")
    assert vav_cand.confidence < traces["zone-1"].candidates[0].confidence
    assert any("likely_false_positive" in r for r in vav_cand.reasons)

    # Common-cause rollup aggregates both unhappy zones under ahu-1
    assert len(report.common_causes) == 1
    cc = report.common_causes[0]
    assert cc.root_equipment == "ahu-1"
    assert cc.root_rule == "SAT-HIGH"
    assert cc.downstream_symptom_count == 2
    assert cc.downstream_equipment == ["zone-1", "zone-2"]


def test_missing_feeds_link_yields_unknown_upstream():
    graph = load_graph(EXAMPLE_PLANT_TTL)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(
                equipment_id="ahu-1",
                rule_id="SAT-HIGH",
                start=parse_utc("2026-11-24T10:00:00Z"),
                end=parse_utc("2026-11-24T12:00:00Z"),
                p_real=0.95,
            ),
            FaultEvidence(
                equipment_id="zone-unlinked",
                rule_id="ZNT-HIGH",
                start=parse_utc("2026-11-24T10:15:00Z"),
                end=parse_utc("2026-11-24T12:00:00Z"),
            ),
        ]
    )

    report = analyze_rca(graph, collector, symptom_equip="zone-unlinked")
    assert len(report.traces) == 1
    tr = report.traces[0]
    assert tr.unknown_upstream is True
    assert tr.upstream_status == "unknown_upstream"
    assert tr.candidates == []
    assert any("unknown upstream" in n.lower() for n in tr.notes)
    md = report_to_markdown(report)
    assert "unknown_upstream" in md
    assert "unknown upstream" in md.lower()


def test_partial_chain_without_ahu_link_yields_partial_unknown_upstream():
    ttl = """
@prefix s223: <http://data.ashrae.org/standard223#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
@prefix local: <urn:test:partial:> .

local:ahu-1 a brick:Air_Handling_Unit ; phIoT:siteRef local:site-1 .
local:vav-orphan a brick:VAV ; s223:connectedTo local:zone-orphan .
local:zone-orphan a brick:HVAC_Zone .
"""
    graph = load_graph(ttl)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="ahu-1", rule_id="SAT-HIGH"),
            FaultEvidence(equipment_id="zone-orphan", rule_id="ZNT-HIGH"),
        ]
    )
    report = analyze_rca(graph, collector, symptom_equip="zone-orphan")
    tr = report.traces[0]
    assert tr.unknown_upstream is True
    assert tr.upstream_status == "partial_unknown_upstream"
    assert tr.unknown_upstream_at == ["vav-orphan"]
    assert all(c.equipment_id != "ahu-1" for c in tr.candidates)


def test_sparql_property_path_and_multi_vocab_223p_haystack_and_cycles():
    ttl = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix s223: <http://data.ashrae.org/standard223#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
@prefix local: <urn:test:multi:> .

local:boiler-1 a s223:Boiler, phIoT:boiler ; s223:connectedTo local:ahu-a .
local:ahu-a a s223:AirHandlingUnit ; s223:connectedTo local:vav-a .
local:vav-a a s223:TerminalUnit ; s223:connectedTo local:zone-a .
local:zone-a a s223:Zone .

# 223P Connection + ConnectionPoint path: plant-223 -> ahu-223 -> term-223 -> zone-223
local:plant-223 a phIoT:chiller ; s223:hasConnectionPoint local:cp-out .
local:cp-out a s223:OutletConnectionPoint ; s223:cnx local:conn-1 .
local:conn-1 a s223:Connection ; s223:cnx local:cp-in .
local:cp-in a s223:InletConnectionPoint .
local:ahu-223 a brick:Air_Handling_Unit ; s223:hasConnectionPoint local:cp-in .
local:conn-2 a s223:Connection ; s223:connectsFrom local:ahu-223 ; s223:connectsTo local:term-223 .
local:term-223 a brick:VAV ; s223:connectedTo local:zone-223 .
local:zone-223 a brick:HVAC_Zone .

# Deliberate cycle to confirm traversal terminates
local:loop-1 a brick:AHU ; s223:connectedTo local:loop-2 .
local:loop-2 a brick:AHU ; s223:connectedTo local:loop-1 .
"""
    graph = load_graph(ttl)

    # SPARQL property path on the 223P connectedTo chain (pyoxigraph)
    sparql_hits = graph.sparql_upstream("urn:test:multi:zone-a")
    assert set(sparql_hits) == {
        "urn:test:multi:vav-a",
        "urn:test:multi:ahu-a",
        "urn:test:multi:boiler-1",
    }

    # Python traversal reaches across 223P ConnectionPoint + Connection + connectedTo
    tr_223 = graph.traverse_upstream("zone-223")
    assert tr_223.unknown_upstream is False
    assert [h.node.node_id for h in tr_223.ancestors] == ["term-223", "ahu-223", "plant-223"]

    # Cycle terminates cleanly
    tr_loop = graph.traverse_upstream("loop-1")
    assert [h.node.node_id for h in tr_loop.ancestors] == ["loop-2"]

    # Custom SPARQL runner fallback/extension stays in sparql_ancestors without inventing hops
    tr_custom = graph.traverse_upstream(
        "zone-a",
        sparql_runner=lambda _q: [{"upstream": "urn:test:multi:extra-plant"}],
    )
    assert "urn:test:multi:extra-plant" in tr_custom.sparql_ancestors
    assert all(h.node.node_id != "extra-plant" for h in tr_custom.ancestors)


def test_temporal_precedence_and_data_quality_discount():
    ttl = """
@prefix s223: <http://data.ashrae.org/standard223#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
@prefix local: <urn:test:prec:> .

local:chiller-1 a brick:Chiller ; s223:connectedTo local:ahu-1 .
local:ahu-1 a brick:Air_Handling_Unit ; s223:connectedTo local:zone-1 .
local:zone-1 a brick:HVAC_Zone .
"""
    graph = load_graph(ttl)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(
                equipment_id="chiller-1",
                rule_id="CHWST-HIGH",
                start=parse_utc("2026-11-24T09:30:00Z"),
                end=parse_utc("2026-11-24T12:00:00Z"),
                p_real=0.85,
            ),
            FaultEvidence(
                equipment_id="ahu-1",
                rule_id="SAT-HIGH",
                start=parse_utc("2026-11-24T11:00:00Z"),  # after symptom onset
                end=parse_utc("2026-11-24T12:00:00Z"),
                p_real=0.85,
            ),
            FaultEvidence(
                equipment_id="zone-1",
                rule_id="ZNT-HIGH",
                start=parse_utc("2026-11-24T10:00:00Z"),
                end=parse_utc("2026-11-24T12:00:00Z"),
            ),
        ],
        data_quality_flags=[
            DataQualityEvidence(equipment_id="ahu-1", flag="stale", detail="SAT sensor stuck")
        ],
    )
    report = analyze_rca(graph, collector)
    cands = report.traces[0].candidates
    assert cands[0].equipment_id == "chiller-1"
    assert cands[0].precedence == "before_symptom"
    assert cands[1].equipment_id == "ahu-1"
    assert cands[1].precedence == "after_symptom"
    assert any("stale" in cov for cov in cands[1].data_quality_caveats)


def test_confidence_episodes_jsonl_and_sqlite_adapter_and_multisite(tmp_path):
    ttl = """
@prefix s223: <http://data.ashrae.org/standard223#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix local: <urn:test:sites:> .

local:site-a a phIoT:site ; rdfs:label "site-a" .
local:site-b a phIoT:site ; rdfs:label "site-b" .

local:a-ahu-1 a brick:Air_Handling_Unit ; rdfs:label "AHU-1" ; phIoT:siteRef local:site-a ; s223:connectedTo local:a-zone-1 .
local:a-zone-1 a brick:HVAC_Zone ; rdfs:label "Zone-1" ; phIoT:siteRef local:site-a .

local:b-ahu-1 a brick:Air_Handling_Unit ; rdfs:label "AHU-1" ; phIoT:siteRef local:site-b ; s223:connectedTo local:b-zone-1 .
local:b-zone-1 a brick:HVAC_Zone ; rdfs:label "Zone-1" ; phIoT:siteRef local:site-b .
"""
    graph = load_graph(ttl)

    # 1. open-fdd-ml confidence episodes.jsonl adapter
    jsonl = tmp_path / "episodes.jsonl"
    jsonl.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "episode_id": "ep1",
                        "equipment_id": "AHU-1",
                        "rule_id": "SAT-LOW",
                        "start": "2026-11-24T08:00:00Z",
                        "end": "2026-11-24T09:00:00Z",
                        "p_real": 0.91,
                        "p_false_positive": 0.05,
                        "label": "likely_real",
                        "site_id": "site-a",
                        "evidence": {"poor_data_quality": False},
                    }
                ),
                json.dumps(
                    {
                        "episode_id": "ep2",
                        "equipment_id": "Zone-1",
                        "rule_id": "ZNT-LOW",
                        "start": "2026-11-24T08:15:00Z",
                        "end": "2026-11-24T09:00:00Z",
                        "p_real": 0.80,
                        "p_false_positive": 0.10,
                        "label": "likely_real",
                        "site_id": "site-a",
                        "evidence": {},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ep_collector = DataFrameEvidenceCollector.from_confidence_episodes(jsonl)
    rep = analyze_rca(graph, ep_collector, site_id="site-a")
    assert rep.traces[0].candidates[0].equipment_iri == "urn:test:sites:a-ahu-1"

    # 2. SQLite SqlEvidenceCollector
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE rule_result (site_id TEXT, equipment_id TEXT, rule_id TEXT, window_start TEXT, window_end TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('site-b', 'AHU-1', 'SAT-HIGH', '2026-11-24T10:00:00Z', '2026-11-24T11:00:00Z', 'FAULT')"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('site-b', 'Zone-1', 'ZNT-HIGH', '2026-11-24T10:10:00Z', '2026-11-24T11:00:00Z', 'FAULT')"
    )
    sql_collector = SqlEvidenceCollector(conn).load(site_id="site-b")
    rep_b = analyze_rca(graph, sql_collector, site_id="site-b")
    assert rep_b.traces[0].candidates[0].equipment_iri == "urn:test:sites:b-ahu-1"
    conn.close()


def test_cli_example_writes_json_and_markdown(tmp_path, capsys):
    out = tmp_path / "rca_out"
    rc = rca_main(["--example", "--out-dir", str(out), "--print", "json"])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["report_version"] == 1
    assert payload["units"] == "SI"
    assert "advisory" in payload
    assert payload["totals"]["common_cause_groups"] == 1
    assert payload["totals"]["unknown_upstream_traces"] == 1
    assert (out / "rca_report.json").is_file()
    md = (out / "rca_report.md").read_text(encoding="utf-8")
    assert "HVAC Root-Cause Analysis" in md
    assert "unknown upstream" in md.lower()

    # report_to_dict matches JSON schema
    assert set(report_to_dict(analyze_rca(load_graph(EXAMPLE_PLANT_TTL), InMemoryEvidenceCollector()))["totals"]) == set(
        payload["totals"]
    )


def test_cli_missing_inputs_returns_2(capsys):
    rc = rca_main(["--print", "none"])
    assert rc == 2
    assert "error:" in capsys.readouterr().err

def test_sql_collector_fallback_keeps_fault_rows_when_confidence_sql_missing(monkeypatch):
    from open_fdd.rca import evidence as evmod

    monkeypatch.setattr(evmod, "confidence_sql_module", lambda: None)
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE rule_result (site_id TEXT, equipment_id TEXT, rule_id TEXT, window_start TEXT, window_end TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('site-a', 'ahu-1', 'SAT-HIGH', '2026-11-24T10:00:00Z', '2026-11-24T10:15:00Z', 'FAULT')"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('site-a', 'ahu-1', 'SAT-HIGH', '2026-11-24T10:15:00Z', '2026-11-24T10:30:00Z', 'FAULT')"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('site-a', 'ahu-1', 'SAT-HIGH', '2026-11-24T11:00:00Z', '2026-11-24T11:15:00Z', 'PASS')"
    )
    collector = evmod.SqlEvidenceCollector(conn).load(site_id="site-a")
    faults = collector.all_faults()
    assert len(faults) == 2
    assert {f.rule_id for f in faults} == {"SAT-HIGH"}
    conn.close()


def test_sql_collector_merges_episodes_and_reads_si_history_with_confidence_sql():
    csql = pytest.importorskip("open_fdd.ml.confidence_sql")
    from open_fdd.rca.evidence import SqlEvidenceCollector

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE rule_result (site_id TEXT, equipment_id TEXT, rule_id TEXT, subject_key TEXT, window_start TEXT, window_end TEXT, status TEXT, fault_hours DOUBLE, covered_hours DOUBLE)"
    )
    # Two adjacent FAULT windows should become one episode.
    conn.execute(
        "INSERT INTO rule_result VALUES ('site-a', 'ahu-1', 'SAT-HIGH', '', '2026-11-24T10:00:00Z', '2026-11-24T10:15:00Z', 'FAULT', 0.25, 0.25)"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('site-a', 'ahu-1', 'SAT-HIGH', '', '2026-11-24T10:15:00Z', '2026-11-24T10:30:00Z', 'FAULT', 0.25, 0.25)"
    )
    conn.execute(
        "CREATE TABLE input_sample (site_id TEXT, point_key TEXT, ts TEXT, value DOUBLE)"
    )
    conn.execute(
        "CREATE TABLE point (site_id TEXT, point_key TEXT, equipment_id TEXT, kind TEXT)"
    )
    conn.execute("INSERT INTO point VALUES ('site-a', 'discharge_air_temperature', 'ahu-1', 'Number')")
    conn.execute("INSERT INTO point VALUES ('site-a', 'discharge_air_temperature_setpoint', 'ahu-1', 'Number')")
    conn.execute("INSERT INTO input_sample VALUES ('site-a', 'discharge_air_temperature', '2026-11-24T10:10:00Z', 18.5)")
    conn.execute("INSERT INTO input_sample VALUES ('site-a', 'discharge_air_temperature_setpoint', '2026-11-24T10:10:00Z', 13.0)")
    collector = SqlEvidenceCollector(
        conn,
        table="rule_result",
        history_table="input_sample",
        point_table="point",
        history_columns={"site_id": "site_id"},
    ).load(site_id="site-a")
    faults = collector.all_faults()
    assert len(faults) == 1
    assert faults[0].equipment_id == "ahu-1"
    assert faults[0].start == parse_utc("2026-11-24T10:00:00Z")
    assert faults[0].end == parse_utc("2026-11-24T10:30:00Z")
    devs = {d.role: d for d in collector.all_deviations()}
    assert "discharge_air_temperature" in devs
    assert devs["discharge_air_temperature"].value_si == 18.5
    assert devs["discharge_air_temperature"].setpoint_si == 13.0
    assert devs["discharge_air_temperature"].resolved_deviation_si == 5.5
    conn.close()
    assert csql.episodes_sql is not None


def test_cli_sqlite_database(tmp_path):
    db = tmp_path / "fdd.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE rule_result (site_id TEXT, equipment_id TEXT, rule_id TEXT, window_start TEXT, window_end TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('Example Building', 'ahu-1', 'SAT-HIGH', '2026-11-24T10:00:00Z', '2026-11-24T12:00:00Z', 'FAULT')"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('Example Building', 'zone-1', 'ZNT-HIGH', '2026-11-24T10:15:00Z', '2026-11-24T12:00:00Z', 'FAULT')"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('Example Building', 'zone-2', 'ZNT-HIGH', '2026-11-24T10:20:00Z', '2026-11-24T12:00:00Z', 'FAULT')"
    )
    conn.commit()
    conn.close()
    out = tmp_path / "rca_out"
    rc = rca_main(["--graph", str(EXAMPLE_PLANT_TTL), "--sqlite", str(db), "--out-dir", str(out), "--print", "none"])
    assert rc == 0
    payload = json.loads((out / "rca_report.json").read_text(encoding="utf-8"))
    assert payload["totals"]["common_cause_groups"] == 1
    assert payload["common_causes"][0]["root_equipment"] == "ahu-1"


# --- Alias resolution, vocab filtering, and review follow-ups -----------------

ALIAS_TTL = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ph: <https://project-haystack.org/def/ph/4.0.0#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
@prefix s223: <http://data.ashrae.org/standard223#> .
@prefix ex: <https://example.org/def#> .
@prefix rec: <urn:example:site/plant-a#> .
@prefix recb: <urn:example:site/plant-b#> .

phIoT:equip a owl:Class ; rdfs:label "equip" .
ph:accumulate a owl:Class ; rdfs:label "accumulate" .

rec:site-1 a phIoT:site ;
    rdfs:label "Plant A" ;
    ex:siteId "plant-a" .

rec:eq.chiller-1 a phIoT:chiller ;
    rdfs:label "Chiller-1" ;
    phIoT:siteRef rec:site-1 ;
    ex:equipmentId "@p:demo:r:ch-001" ;
    s223:connectedTo rec:eq.ahu-1 .

rec:eq.ahu-1 a phIoT:equip ;
    rdfs:label "AHU West" ;
    phIoT:siteRef rec:site-1 ;
    ex:equipmentId "@p:demo:r:aaa-111" ;
    ex:sourceRef "@p:demo:r:aaa-111" ;
    ex:openfddKey "fin.aaa111" ;
    ex:siteId "plant-a" ;
    s223:connectedTo rec:eq.vav-1 .

rec:eq.vav-1 a phIoT:equip ;
    rdfs:label "VAV-1" ;
    phIoT:siteRef rec:site-1 ;
    ex:equipmentId "@p:demo:r:bbb-222" ;
    s223:connectedTo rec:eq.zone-1 .

rec:eq.zone-1 a phIoT:equip ;
    rdfs:label "Zone-1" ;
    phIoT:siteRef rec:site-1 ;
    ex:equipmentId "@p:demo:r:ccc-333" .

rec:eq.orphan a phIoT:equip ;
    rdfs:label "Orphan AHU" ;
    phIoT:siteRef rec:site-1 ;
    ex:equipmentId "@p:demo:r:ddd-444" .

rec:fin.sat a phIoT:point ;
    rdfs:label "SAT" ;
    phIoT:siteRef rec:site-1 ;
    phIoT:equipRef rec:eq.ahu-1 ;
    ex:pointId "@p:demo:r:eee-555" ;
    ex:openfddKey "fin.sat111" .

recb:site-2 a phIoT:site ;
    rdfs:label "Plant B" ;
    ex:siteId "plant-b" .

recb:eq.zone-1 a phIoT:equip ;
    rdfs:label "Zone-1" ;
    phIoT:siteRef recb:site-2 ;
    ex:equipmentId "@p:other:r:zzz-999" ;
    ex:siteId "plant-b" .
"""


def _alias_graph():
    from open_fdd.rca.graph import load_graph

    return load_graph(ALIAS_TTL)


def test_resolve_alternate_ids_and_skip_vocab_terms():
    g = _alias_graph()
    assert g.resolve_node("accumulate") is None
    assert g.resolve_node("equip") is None
    assert all(not n.iri.startswith("https://project-haystack.org/def/") for n in g.nodes.values())

    ahu = g.resolve_node("@p:demo:r:aaa-111")
    assert ahu is not None
    assert ahu.label == "AHU West"
    assert g.resolve_node("p:demo:r:aaa-111").iri == ahu.iri
    assert g.resolve_node("fin.aaa111").iri == ahu.iri
    assert g.resolve_node("AHU West").iri == ahu.iri
    assert g.resolve_node("eq.ahu-1").iri == ahu.iri
    point = g.resolve_node("fin.sat111")
    assert point is not None and point.is_point


def test_haystack_id_traversal_and_missing_feeder():
    g = _alias_graph()
    traced = g.traverse_upstream("@p:demo:r:ccc-333")
    assert traced.target is not None
    assert traced.upstream_status == "traced"
    assert [h.node.label for h in traced.ancestors] == ["VAV-1", "AHU West", "Chiller-1"]

    orphan = g.traverse_upstream("@p:demo:r:ddd-444")
    assert orphan.upstream_status == "unknown_upstream"
    assert orphan.unknown_upstream is True

    from_point = g.traverse_upstream("fin.sat111")
    assert from_point.target is not None and from_point.target.is_point
    assert any(h.node.label == "AHU West" for h in from_point.ancestors)
    assert from_point.upstream_status == "traced"


def test_site_scope_does_not_fall_back_to_another_site():
    g = _alias_graph()
    assert g.resolve_node("Zone-1", site_id="plant-a").iri.endswith("eq.zone-1")
    assert g.resolve_node("Zone-1", site_id="plant-b").iri.startswith("urn:example:site/plant-b")
    # An IRI from plant-b must not be returned when the caller asked for plant-a.
    plant_b = g.resolve_node("@p:other:r:zzz-999")
    assert plant_b is not None
    assert g.resolve_node(plant_b.iri, site_id="plant-a") is None
    assert g.resolve_node("missing-id", site_id="plant-a") is None


def test_cnx_requires_typed_inlet():
    from open_fdd.rca.graph import load_graph

    ttl = """
    @prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix rec: <urn:example:cnx#> .
    rec:fan s223:hasConnectionPoint rec:fan-out .
    rec:damper s223:hasConnectionPoint rec:damper-out .
    rec:fan-out a s223:OutletConnectionPoint ; s223:cnx rec:conn .
    rec:damper-out a s223:OutletConnectionPoint ; s223:cnx rec:conn .
    rec:conn s223:cnx rec:damper-out .
    """
    g = load_graph(ttl)
    # Two outlets on one connection must not invent a feeder edge.
    assert sum(len(v) for v in g.upstream_edges.values()) == 0


def test_closed_feeder_cycle_is_partial_unknown():
    from open_fdd.rca.graph import load_graph

    ttl = """
@prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix rec: <urn:example:cycle#> .
    rec:ahu-a s223:connectedTo rec:ahu-b .
    rec:ahu-b s223:connectedTo rec:ahu-a .
    """
    tr = load_graph(ttl).traverse_upstream("ahu-a")
    assert tr.upstream_status == "partial_unknown_upstream"
    assert tr.unknown_upstream is True


def test_sparql_only_hits_are_not_direct_feeder_candidates():
    from datetime import datetime

    from open_fdd.rca.evidence import FaultEvidence, InMemoryEvidenceCollector
    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.rank import analyze_rca
    from open_fdd.rca.report import report_to_markdown

    ttl = """
@prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix rec: <urn:example:path#> .
    rec:chiller-1 s223:connectedTo rec:ahu-1 .
    rec:ahu-1 s223:connectedTo rec:zone-1 .
    """
    g = load_graph(ttl)
    chiller = g.resolve_node("chiller-1")
    tr_unverified = g.traverse_upstream(
        "zone-1",
        max_hops=1,
        sparql_runner=lambda _q: [{"upstream": chiller.iri}, {"upstream": "urn:example:path#phantom"}],
    )
    assert chiller.iri in tr_unverified.sparql_ancestors
    assert "urn:example:path#phantom" in tr_unverified.sparql_ancestors
    assert all(h.node.iri != chiller.iri for h in tr_unverified.ancestors)
    assert all(h.node.node_id != "phantom" for h in tr_unverified.ancestors)

    # Default analyze_rca + markdown must not invent unverified SPARQL-only ancestors.
    # Patch sparql_upstream so analyze_rca actually sees the SPARQL-only hit.
    ts = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="zone-1", rule_id="ZNT-HIGH", start=ts, end=ts),
            FaultEvidence(equipment_id="phantom", rule_id="PLANT-DOWN", start=ts, end=ts),
        ]
    )
    g.sparql_upstream = lambda _iri, sparql_runner=None: [chiller.iri, "urn:example:path#phantom"]
    report = analyze_rca(g, collector)
    zone_tr = next(t for t in report.traces if t.symptom_equipment == "zone-1")
    assert all(c.equipment_id != "phantom" for c in zone_tr.candidates)
    assert all("phantom" not in c.cause_chain for c in zone_tr.candidates)
    md = report_to_markdown(report)
    assert "phantom -> zone-1" not in md


def test_incomplete_window_bounds_filter_independently():
    from datetime import datetime

    from open_fdd.rca.evidence import (
        FaultEvidence,
        InMemoryEvidenceCollector,
        PointDeviation,
    )

    start = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    early = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    collector = InMemoryEvidenceCollector(
        faults=[FaultEvidence(equipment_id="ahu-1", rule_id="SAT-HIGH", start=early, end=early)],
        point_deviations=[
            PointDeviation(equipment_id="ahu-1", role="sat", value_si=291.15, timestamp=early)
        ],
    )
    ev = collector.collect("ahu-1", window_start=start, window_end=None)
    assert ev.faults == []
    assert ev.point_deviations == []
    ev_open = collector.collect("ahu-1")
    assert len(ev_open.faults) == 1


def test_episode_dq_flag_stays_in_episode_window():
    from datetime import datetime

    from open_fdd.rca.evidence import DataFrameEvidenceCollector

    jan = {
        "equipment_id": "ahu-1",
        "rule_id": "SAT-HIGH",
        "start": "2026-01-15T00:00:00Z",
        "end": "2026-01-16T00:00:00Z",
        "evidence": {"poor_data_quality": True},
    }
    collector = DataFrameEvidenceCollector.from_confidence_episodes([jan])
    march = datetime(2026, 3, 1, tzinfo=UTC)
    ev = collector.collect("ahu-1", window_start=march, window_end=march)
    assert ev.faults == []
    assert ev.data_quality_flags == []
    jan_win = datetime(2026, 1, 15, 12, tzinfo=UTC)
    ev_jan = collector.collect("ahu-1", window_start=jan_win, window_end=jan_win)
    assert ev_jan.data_quality_flags and ev_jan.data_quality_flags[0].flag == "poor_data_quality"


def test_sample_clear_splits_episodes():
    from datetime import datetime

    from open_fdd.rca.evidence import DataFrameEvidenceCollector

    rows = [
        {"equipment_id": "ahu-1", "rule_id": "SAT-HIGH", "flag": "1", "timestamp": "2026-03-01T10:00:00Z"},
        {"equipment_id": "ahu-1", "rule_id": "SAT-HIGH", "flag": "0", "timestamp": "2026-03-01T10:05:00Z"},
        {"equipment_id": "ahu-1", "rule_id": "SAT-HIGH", "flag": "1", "timestamp": "2026-03-01T10:10:00Z"},
    ]
    collector = DataFrameEvidenceCollector.from_rule_results(rows, fault_statuses=("1", "FAULT"))
    assert len(collector.all_faults()) == 2
    starts = [f.start for f in collector.all_faults()]
    assert starts[0] == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    assert starts[1] == datetime(2026, 3, 1, 10, 10, tzinfo=UTC)


def test_sql_load_preserves_site_ids(tmp_path):
    import sqlite3

    from open_fdd.rca.evidence import SqlEvidenceCollector

    db = tmp_path / "sites.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE rule_result (site_id TEXT, equipment_id TEXT, rule_id TEXT, "
        "window_start TEXT, window_end TEXT, status TEXT)"
    )
    conn.executemany(
        "INSERT INTO rule_result VALUES (?,?,?,?,?,?)",
        [
            ("plant-a", "Zone-1", "ZNT-HIGH", "2026-03-01T00:00:00Z", "2026-03-01T01:00:00Z", "FAULT"),
            ("plant-b", "Zone-1", "ZNT-HIGH", "2026-03-01T00:00:00Z", "2026-03-01T01:00:00Z", "FAULT"),
        ],
    )
    conn.commit()
    faults = SqlEvidenceCollector(conn).load().all_faults()
    sites = sorted(f.site_id for f in faults)
    assert sites == ["plant-a", "plant-b"]
    collector = SqlEvidenceCollector(conn).load()
    scoped = [f for f in collector.all_faults() if f.site_id == "plant-a"]
    assert len(scoped) == 1
    g = _alias_graph()
    rep_a = analyze_rca(g, collector, site_id="plant-a")
    rep_b = analyze_rca(g, collector, site_id="plant-b")
    assert len(rep_a.traces) == 1 and rep_a.traces[0].symptom_site == "plant-a"
    assert len(rep_b.traces) == 1 and rep_b.traces[0].symptom_site == "plant-b"


def test_evidence_merged_across_aliases_and_common_cause_uses_iri():
    from datetime import datetime

    from open_fdd.rca.evidence import (
        FaultEvidence,
        InMemoryEvidenceCollector,
        PointDeviation,
    )
    from open_fdd.rca.rank import analyze_rca

    g = _alias_graph()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="AHU West", rule_id="SAT-HIGH", start=ts, end=ts, site_id="plant-a"),
            FaultEvidence(equipment_id="@p:demo:r:ccc-333", rule_id="ZNT-HIGH", start=ts, end=ts, site_id="plant-a"),
            FaultEvidence(equipment_id="@p:demo:r:bbb-222", rule_id="DM-HIGH", start=ts, end=ts, site_id="plant-a"),
        ],
        point_deviations=[
            PointDeviation(equipment_id="fin.aaa111", role="sat", value_si=291.15, setpoint_si=286.15, deviation_si=5.0, timestamp=ts, site_id="plant-a"),
        ],
    )
    report = analyze_rca(g, collector)
    zone = next(t for t in report.traces if t.upstream_status == "traced" and "ccc-333" in t.symptom_equipment)
    ahu_cands = [c for c in zone.candidates if c.equipment_id in {"eq.ahu-1", "AHU West"} or "aaa-111" in c.equipment_id]
    assert ahu_cands
    # The SAT-HIGH fault and the SAT deviation must both contribute (not first-alias wins).
    lead = ahu_cands[0]
    joined = " ".join(lead.reasons)
    assert "SAT-HIGH" in lead.rule_id or "SAT-HIGH" in joined or lead.rule_id == "SAT-HIGH"
    assert lead.score_breakdown["deviation"] > 0
    assert any("SI deviation" in reason for reason in lead.reasons)


def test_common_cause_next_checks_includes_site_and_iri():
    from datetime import datetime

    from open_fdd.rca.evidence import FaultEvidence, InMemoryEvidenceCollector
    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.rank import analyze_rca
    from open_fdd.rca.report import next_checks

    ttl = """
@prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix s1: <urn:example:site/north#> .
    @prefix s2: <urn:example:site/south#> .

    s1:ahu-shared a brick:AHU ; rdfs:label "AHU-1" ; phIoT:siteRef s1:site-north ; s223:connectedTo s1:z1, s1:z2 .
    s1:z1 a brick:HVAC_Zone ; phIoT:siteRef s1:site-north .
    s1:z2 a brick:HVAC_Zone ; phIoT:siteRef s1:site-north .

    s2:ahu-shared a brick:AHU ; rdfs:label "AHU-1" ; phIoT:siteRef s2:site-south ; s223:connectedTo s2:z3, s2:z4 .
    s2:z3 a brick:HVAC_Zone ; phIoT:siteRef s2:site-south .
    s2:z4 a brick:HVAC_Zone ; phIoT:siteRef s2:site-south .
    """
    g = load_graph(ttl)
    ts = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="urn:example:site/north#ahu-shared", rule_id="SAT-HIGH", start=ts, end=ts, site_id="site-north"),
            FaultEvidence(equipment_id="urn:example:site/north#z1", rule_id="ZNT-HIGH", start=ts, end=ts, site_id="site-north"),
            FaultEvidence(equipment_id="urn:example:site/north#z2", rule_id="ZNT-HIGH", start=ts, end=ts, site_id="site-north"),
            FaultEvidence(equipment_id="urn:example:site/south#ahu-shared", rule_id="SAT-HIGH", start=ts, end=ts, site_id="site-south"),
            FaultEvidence(equipment_id="urn:example:site/south#z3", rule_id="ZNT-HIGH", start=ts, end=ts, site_id="site-south"),
            FaultEvidence(equipment_id="urn:example:site/south#z4", rule_id="ZNT-HIGH", start=ts, end=ts, site_id="site-south"),
        ]
    )
    report = analyze_rca(g, collector)
    assert len(report.common_causes) == 2
    iris = {cc.root_iri for cc in report.common_causes}
    sites = {cc.root_site for cc in report.common_causes}
    assert iris == {"urn:example:site/north#ahu-shared", "urn:example:site/south#ahu-shared"}
    assert sites == {"site-north", "site-south"}
    checks = " | ".join(next_checks(report))
    assert "site-north" in checks and "site-south" in checks
    assert "urn:example:site/north#ahu-shared" in checks


def test_shared_label_does_not_leak_evidence_and_preserves_distinct_deviations():
    from datetime import datetime, timedelta

    from open_fdd.rca.evidence import (
        FaultEvidence,
        InMemoryEvidenceCollector,
        PointDeviation,
    )
    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.rank import _collect_for_node, analyze_rca

    ttl = """
@prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix rec: <urn:example:dup#> .

    rec:ahu-1 a brick:AHU ; rdfs:label "Shared AHU" ; s223:connectedTo rec:zone-1 .
    rec:ahu-2 a brick:AHU ; rdfs:label "Shared AHU" ; s223:connectedTo rec:zone-2 .
    rec:zone-1 a brick:HVAC_Zone .
    rec:zone-2 a brick:HVAC_Zone .
    """
    g = load_graph(ttl)
    ts = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="Shared AHU", rule_id="SAT-HIGH", start=ts, end=ts),
            FaultEvidence(equipment_id="zone-1", rule_id="ZNT-HIGH", start=ts, end=ts),
        ],
        point_deviations=[
            PointDeviation(equipment_id="ahu-1", role="sat", value_si=290.0, setpoint_si=286.0, deviation_si=4.0, timestamp=ts),
            PointDeviation(equipment_id="ahu-1", role="sat", value_si=290.0, setpoint_si=284.0, deviation_si=6.0, timestamp=ts),
        ],
    )
    node1 = g.resolve_node("ahu-1")
    ev1 = _collect_for_node(collector, g, node1, FaultEvidence(equipment_id="zone-1", rule_id="ZNT-HIGH", start=ts, end=ts), tolerance=timedelta(minutes=30))
    # Shared ambiguous label must not be pulled into ahu-1
    assert ev1.faults == []
    # Distinct setpoint_si / deviation_si at identical timestamp & value_si must both survive dedup
    assert len(ev1.point_deviations) == 2

    report = analyze_rca(g, collector)
    z1 = next(t for t in report.traces if t.symptom_equipment == "zone-1")
    assert all(c.rule_id != "SAT-HIGH" for c in z1.candidates)


def test_inferred_topology_recovers_hidden_chain_and_discounts_weight(tmp_path):
    import csv
    import math
    from datetime import datetime, timedelta

    import rdflib

    from open_fdd.rca.evidence import FaultEvidence, InMemoryEvidenceCollector
    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.infer import (
        infer_topology,
        load_telemetry_csv,
        suggested_links_to_csv,
        suggested_links_to_ttl,
    )
    from open_fdd.rca.rank import analyze_rca
    from open_fdd.rca.report import next_checks, report_to_dict, report_to_markdown

    # Full modeled baseline vs. stripped TTL with ZERO feeds links
    ttl_modeled = """
@prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <urn:test:hidden#> .

    ex:chiller-1 a brick:Chiller ; rdfs:label "Chiller-1" ; s223:connectedTo ex:ahu-1 .
    ex:ahu-1 a brick:AHU ; rdfs:label "AHU-1" ; s223:connectedTo ex:vav-1, ex:vav-2 .
    ex:vav-1 a brick:VAV ; rdfs:label "VAV-1" ; s223:connectedTo ex:zone-1 .
    ex:vav-2 a brick:VAV ; rdfs:label "VAV-2" ; s223:connectedTo ex:zone-2 .
    ex:zone-1 a brick:HVAC_Zone ; rdfs:label "Zone-1" .
    ex:zone-2 a brick:HVAC_Zone ; rdfs:label "Zone-2" .
    """

    ttl_hidden = """
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <urn:test:hidden#> .

    ex:chiller-1 a brick:Chiller ; rdfs:label "Chiller-1" .
    ex:ahu-1 a brick:AHU ; rdfs:label "AHU-1" .
    ex:vav-1 a brick:VAV ; rdfs:label "VAV-1" .
    ex:vav-2 a brick:VAV ; rdfs:label "VAV-2" .
    ex:zone-1 a brick:HVAC_Zone ; rdfs:label "Zone-1" .
    ex:zone-2 a brick:HVAC_Zone ; rdfs:label "Zone-2" .

    ex:chiller_chwst a brick:Chilled_Water_Supply_Temperature_Sensor ;
        rdfs:label "Chiller-1 CHWST" ; phIoT:equipRef ex:chiller-1 .
    ex:ahu_sat a brick:Supply_Air_Temperature_Sensor ;
        rdfs:label "AHU-1 SAT" ; phIoT:equipRef ex:ahu-1 .
    ex:ahu_sat_sp a brick:Supply_Air_Temperature_Setpoint ;
        rdfs:label "AHU-1 SAT SP" ; phIoT:equipRef ex:ahu-1 .
    ex:vav1_dat a brick:Discharge_Air_Temperature_Sensor ;
        rdfs:label "VAV-1 DAT" ; phIoT:equipRef ex:vav-1 .
    ex:vav2_dat a brick:Discharge_Air_Temperature_Sensor ;
        rdfs:label "VAV-2 DAT" ; phIoT:equipRef ex:vav-2 .
    ex:zone1_temp a brick:Zone_Air_Temperature_Sensor ;
        rdfs:label "Zone-1 Temp" ; phIoT:equipRef ex:zone-1 .
    ex:zone2_temp a brick:Zone_Air_Temperature_Sensor ;
        rdfs:label "Zone-2 Temp" ; phIoT:equipRef ex:zone-2 .
    """

    # Build lagged synthetic telemetry:
    # chiller_chwst(t) -> ahu_sat(t+1) -> vav1_dat(t+2), vav2_dat(t+2) -> zone1_temp(t+3), zone2_temp(t+3)
    n_steps = 60
    t0 = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
    csv_path = tmp_path / "telemetry.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "timestamp",
            "chiller_chwst",
            "ahu_sat",
            "ahu_sat_sp",
            "vav1_dat",
            "vav2_dat",
            "zone1_temp",
            "zone2_temp",
        ])
        base = [280.0 + 4.0 * math.sin(i / 4.0) + 0.1 * (i % 5) for i in range(n_steps + 5)]
        for i in range(n_steps):
            ts = (t0 + timedelta(minutes=15 * i)).isoformat()
            chwst = base[i + 3]
            ahu_sat = 286.0 + 0.9 * (base[i + 2] - 280.0)
            vav1 = ahu_sat + 1.5
            vav2 = ahu_sat + 2.0
            # lag +1 from ahu_sat -> vav1/vav2 -> zone1/zone2: use i+1 for vav and i+0 for zone
            ahu_sat = 286.0 + 0.9 * (base[i + 2] - 280.0)
            vav1 = 287.5 + 0.85 * (base[i + 1] - 280.0)
            vav2 = 288.0 + 0.80 * (base[i + 1] - 280.0)
            z1 = 294.0 + 0.75 * (base[i] - 280.0)
            z2 = 294.5 + 0.70 * (base[i] - 280.0)
            w.writerow([ts, round(chwst, 3), round(ahu_sat, 3), 286.0, round(vav1, 3), round(vav2, 3), round(z1, 3), round(z2, 3)])

    g_hidden = load_graph(ttl_hidden)
    assert sum(1 for lst in g_hidden.upstream_edges.values() for e in lst if not g_hidden.nodes[e.downstream_iri].is_point) == 0

    telemetry = load_telemetry_csv(csv_path)
    edges = infer_topology(g_hidden, telemetry, min_correlation=0.70, max_lag=3, min_samples=20)
    pairs = {(e.upstream_label, e.downstream_label) for e in edges}
    assert ("Chiller-1", "AHU-1") in pairs
    assert ("AHU-1", "VAV-1") in pairs
    assert ("AHU-1", "VAV-2") in pairs
    assert ("VAV-1", "Zone-1") in pairs
    assert ("VAV-2", "Zone-2") in pairs
    # Setpoints must not drive edges, and original graph must remain untouched
    assert all("SP" not in e.upstream_point and "SP" not in e.downstream_point for e in edges)
    assert sum(1 for lst in g_hidden.upstream_edges.values() for e in lst if not g_hidden.nodes[e.downstream_iri].is_point) == 0

    g_inferred = g_hidden.with_inferred_edges(edges)
    # Original hidden graph is still empty (never mutated)
    assert sum(1 for lst in g_hidden.upstream_edges.values() for e in lst if not g_hidden.nodes[e.downstream_iri].is_point) == 0

    ts_fault = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="ahu-1", rule_id="SAT-HIGH", start=ts_fault, end=ts_fault),
            FaultEvidence(equipment_id="zone-1", rule_id="ZNT-HIGH", start=ts_fault + timedelta(minutes=15), end=ts_fault + timedelta(minutes=30)),
            FaultEvidence(equipment_id="zone-2", rule_id="ZNT-HIGH", start=ts_fault + timedelta(minutes=15), end=ts_fault + timedelta(minutes=30)),
        ]
    )

    rep_modeled = analyze_rca(load_graph(ttl_modeled), collector)
    rep_inferred = analyze_rca(g_inferred, collector)

    # Without inference, zones are unknown_upstream; with inference, both recover ahu-1 at discounted confidence
    rep_hidden_only = analyze_rca(g_hidden, collector)
    assert rep_hidden_only.totals["unknown_upstream_traces"] == 3

    z1_mod = next(t for t in rep_modeled.traces if t.symptom_equipment == "zone-1")
    z1_inf = next(t for t in rep_inferred.traces if t.symptom_equipment == "zone-1")
    assert z1_inf.upstream_status == "traced_inferred"
    assert z1_inf.topology_source == "inferred, not modeled"
    assert z1_inf.candidates[0].equipment_id == "ahu-1"
    assert z1_inf.candidates[0].inferred is True
    assert z1_inf.candidates[0].confidence < z1_mod.candidates[0].confidence
    assert "inferred_topology_multiplier" in z1_inf.candidates[0].score_breakdown

    assert rep_inferred.totals["inferred_topology_traces"] >= 2
    assert any(cc.root_equipment == "ahu-1" and cc.inferred for cc in rep_inferred.common_causes)

    # JSON, Markdown, and next_checks clearly mark inferred, not modeled
    payload = report_to_dict(rep_inferred)
    assert any(t["topology_source"] == "inferred, not modeled" for t in payload["traces"])
    md = report_to_markdown(rep_inferred)
    assert "inferred, not modeled" in md
    assert any("inferred, not modeled" in chk for chk in next_checks(rep_inferred))

    # Suggested-links outputs (TTL + CSV) are valid for human review
    ttl_out = suggested_links_to_ttl(edges)
    csv_out = suggested_links_to_csv(edges)
    parsed_suggestions = rdflib.Graph()
    parsed_suggestions.parse(data=ttl_out, format="turtle")
    assert len(parsed_suggestions) == 4 * len(edges)
    assert "inferred, not modeled" in csv_out
    assert "s223:connectedTo" in csv_out


def test_cli_infer_topology_writes_suggested_links(tmp_path):
    import csv
    import json
    from datetime import datetime, timedelta

    from open_fdd.rca.cli import main

    ttl_path = tmp_path / "model.ttl"
    ttl_path.write_text(
        """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <urn:test:cli#> .

ex:ahu-1 a brick:AHU ; rdfs:label "AHU-1" .
ex:vav-1 a brick:VAV ; rdfs:label "VAV-1" .
ex:ahu_sat a brick:Supply_Air_Temperature_Sensor ; phIoT:equipRef ex:ahu-1 .
ex:vav_dat a brick:Discharge_Air_Temperature_Sensor ; phIoT:equipRef ex:vav-1 .
""",
        encoding="utf-8",
    )
    res_path = tmp_path / "results.csv"
    res_path.write_text(
        "equipment_id,rule_id,status,window_start,window_end\n"
        "ahu-1,SAT-HIGH,FAULT,2026-03-01T02:00:00Z,2026-03-01T04:00:00Z\n"
        "vav-1,DAT-LOW,FAULT,2026-03-01T02:15:00Z,2026-03-01T04:00:00Z\n",
        encoding="utf-8",
    )
    hist_path = tmp_path / "history.csv"
    t0 = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
    with hist_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "ahu_sat", "vav_dat"])
        for i in range(40):
            ts = (t0 + timedelta(minutes=15 * i)).isoformat()
            sig = 285.0 + 2.0 * ((i % 6) - 2.5)
            sig_lag = 286.0 + 2.0 * (((i - 1) % 6) - 2.5)
            w.writerow([ts, sig, sig_lag])

    out_dir = tmp_path / "out"
    rc = main([
        "--graph", str(ttl_path),
        "--results", str(res_path),
        "--infer-topology",
        "--history-csv", str(hist_path),
        "--infer-min-corr", "0.5",
        "--infer-min-samples", "20",
        "--out-dir", str(out_dir),
    ])
    assert rc == 0
    assert (out_dir / "suggested_links.ttl").is_file()
    assert (out_dir / "suggested_links.csv").is_file()
    report_json = json.loads((out_dir / "rca_report.json").read_text(encoding="utf-8"))
    assert report_json["source"]["inferred_topology"]["enabled"] is True
    assert report_json["source"]["inferred_topology"]["proposed_edges"] >= 1
    assert "inferred, not modeled" in (out_dir / "rca_report.md").read_text(encoding="utf-8")


def test_sql_fallback_uses_configured_fault_statuses(monkeypatch, tmp_path):
    from open_fdd.rca import evidence as evmod

    monkeypatch.setattr(evmod, "confidence_sql_module", lambda: None)
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE rule_result (site_id TEXT, equipment_id TEXT, rule_id TEXT, "
        "window_start TEXT, window_end TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('site-a', 'ahu-1', 'SAT-HIGH', "
        "'2026-11-24T10:00:00Z', '2026-11-24T10:15:00Z', 'ALARM')"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('site-a', 'ahu-1', 'SAT-HIGH', "
        "'2026-11-24T11:00:00Z', '2026-11-24T11:15:00Z', 'FAULT')"
    )
    default_faults = evmod.SqlEvidenceCollector(conn).load(site_id="site-a").all_faults()
    assert len(default_faults) == 1
    assert default_faults[0].status == "FAULT"
    alarm_faults = evmod.SqlEvidenceCollector(conn, fault_status=("ALARM",)).load(site_id="site-a").all_faults()
    assert len(alarm_faults) == 1
    assert alarm_faults[0].status == "ALARM"
    conn.close()


def test_sql_history_loads_each_window_and_preserves_zero_setpoint():
    from datetime import datetime, timedelta

    from open_fdd.rca.evidence import FaultEvidence, SqlEvidenceCollector

    class _FakeCsql:
        def paramstyle(self, conn):
            return "?"

        def history_sql(self, hm, ph, by_site=False):
            return "history"

        def fetch(self, conn, sql, params):
            eq, start, end = params[0], params[1], params[2]
            cols = ["ts", "point_id", "value"]
            rows = [
                ("2026-01-15T12:00:00Z", "sat", 290.0),
                ("2026-01-15T12:00:00Z", "sat-sp", 0.0),
                ("2026-03-15T12:00:00Z", "sat", 291.0),
                ("2026-03-15T12:00:00Z", "sat-sp", 286.0),
            ]
            return cols, [r for r in rows if start <= r[0] <= end and eq == "ahu-1"]

    jan = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    march = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    faults = [
        FaultEvidence(equipment_id="ahu-1", rule_id="SAT-HIGH", start=None, end=None, site_id="site-a"),
        FaultEvidence(equipment_id="ahu-1", rule_id="SAT-HIGH", start=jan, end=jan + timedelta(hours=1), site_id="site-a"),
        FaultEvidence(equipment_id="ahu-1", rule_id="SAT-HIGH", start=march, end=march + timedelta(hours=1), site_id="site-a"),
    ]
    collector = SqlEvidenceCollector(sqlite3.connect(":memory:"), history_table="input_sample")
    class _FakeHist:
        def col(self, name):
            return "site_id" if name == "site_id" else None

    devs = collector._load_history_deviations(_FakeCsql(), _FakeHist(), faults, site_id="site-a")
    by_month = {(d.timestamp.month if d.timestamp else None): d for d in devs}
    assert set(by_month) == {1, 3}
    assert by_month[1].setpoint_si == 0.0
    assert by_month[1].value_si == 290.0
    assert by_month[3].setpoint_si == 286.0


def test_cli_defaults_history_table_when_present(tmp_path):
    import sqlite3

    from open_fdd.rca.cli import _open_sql_collector, build_parser

    db = tmp_path / "fdd.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE rule_result (equipment_id TEXT, rule_id TEXT, window_start TEXT, window_end TEXT, status TEXT)")
    conn.execute("CREATE TABLE input_sample (point_key TEXT, ts TEXT, value DOUBLE)")
    conn.commit()
    conn.close()
    args = build_parser().parse_args(["--sqlite", str(db), "--graph", "unused.ttl"])
    collector, sql_conn, engine = _open_sql_collector(args)
    try:
        assert engine == "sqlite"
        assert collector.history_table == "input_sample"
        assert collector.point_table == "point"
    finally:
        sql_conn.close()

    args_off = build_parser().parse_args(["--sqlite", str(db), "--graph", "unused.ttl", "--no-history"])
    collector_off, sql_conn_off, _ = _open_sql_collector(args_off)
    try:
        assert collector_off.history_table is None
    finally:
        sql_conn_off.close()

    db_missing = tmp_path / "nohist.db"
    conn = sqlite3.connect(db_missing)
    conn.execute("CREATE TABLE rule_result (equipment_id TEXT, rule_id TEXT, window_start TEXT, window_end TEXT, status TEXT)")
    conn.commit()
    conn.close()
    args_missing = build_parser().parse_args(["--sqlite", str(db_missing), "--graph", "unused.ttl"])
    collector_missing, sql_conn_m, _ = _open_sql_collector(args_missing)
    try:
        assert collector_missing.history_table is None
    finally:
        sql_conn_m.close()


def test_inferred_negative_correlation_explained_in_evidence(tmp_path):
    import csv
    from datetime import datetime, timedelta

    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.infer import (
        infer_topology,
        load_telemetry_csv,
        suggested_links_to_csv,
    )

    ttl = """
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <urn:test:inverse#> .

    ex:chiller-1 a brick:Chiller ; rdfs:label "Chiller-1" .
    ex:loop-1 a brick:Chilled_Water_Loop ; rdfs:label "CHW Loop" .
    ex:chwst a brick:Chilled_Water_Supply_Temperature_Sensor ;
        rdfs:label "CHWST" ; phIoT:equipRef ex:chiller-1 .
    ex:loop_rwt a brick:Chilled_Water_Return_Temperature_Sensor ;
        rdfs:label "CHWRT" ; phIoT:equipRef ex:loop-1 .
    """
    csv_path = tmp_path / "hist.csv"
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "chwst", "loop_rwt"])
        for i in range(40):
            ts = (t0 + timedelta(minutes=15 * i)).isoformat()
            # Upstream leaving temp falls as downstream loop/return temp rises (inverse, lag +1)
            leaving = 280.0 - 3.0 * ((i % 8) - 3.5)
            loop = 285.0 + 2.5 * (((i - 1) % 8) - 3.5)
            w.writerow([ts, leaving, loop])

    edges = infer_topology(load_graph(ttl), load_telemetry_csv(csv_path), min_correlation=0.50, min_samples=20)
    pairs = {(e.upstream_label, e.downstream_label) for e in edges}
    assert ("Chiller-1", "CHW Loop") in pairs
    edge = next(e for e in edges if e.upstream_label == "Chiller-1")
    assert edge.correlation is not None and edge.correlation < 0
    joined = " | ".join(edge.evidence)
    assert "r=-" in joined or "r=-0" in f"r={edge.correlation:+.3f}"
    assert "inverse co-movement allowed" in joined or "negative correlation is expected" in joined
    assert "does not require a positive sign" in joined
    csv_text = suggested_links_to_csv(edges)
    assert "negative correlation is expected" in csv_text


def test_case_distinct_aliases_do_not_leak_evidence():
    from datetime import datetime, timedelta

    from open_fdd.rca.evidence import FaultEvidence, InMemoryEvidenceCollector
    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.rank import _collect_for_node, analyze_rca

    ttl = """
@prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix rec: <urn:example:case#> .

    rec:ahu-west a brick:AHU ; rdfs:label "AHU West" ; s223:connectedTo rec:zone-1 .
    rec:ahu-west-b a brick:AHU ; rdfs:label "ahu west" ; s223:connectedTo rec:zone-2 .
    rec:zone-1 a brick:HVAC_Zone .
    rec:zone-2 a brick:HVAC_Zone .
    """
    g = load_graph(ttl)
    ts = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="AHU West", rule_id="SAT-HIGH", start=ts, end=ts),
            FaultEvidence(equipment_id="zone-1", rule_id="ZNT-HIGH", start=ts, end=ts),
            FaultEvidence(equipment_id="zone-2", rule_id="ZNT-HIGH", start=ts, end=ts),
        ]
    )
    west = g.resolve_node("ahu-west")
    west_b = g.resolve_node("ahu-west-b")
    ev_a = _collect_for_node(collector, g, west, FaultEvidence(equipment_id="zone-1", rule_id="ZNT-HIGH", start=ts, end=ts), tolerance=timedelta(minutes=30))
    ev_b = _collect_for_node(collector, g, west_b, FaultEvidence(equipment_id="zone-2", rule_id="ZNT-HIGH", start=ts, end=ts), tolerance=timedelta(minutes=30))
    assert ev_a.faults == []
    assert ev_b.faults == []

    report = analyze_rca(g, collector)
    for tr in report.traces:
        assert all(c.rule_id != "SAT-HIGH" for c in tr.candidates)


def test_sql_fallback_trims_status_and_uses_question_placeholder(monkeypatch):
    from open_fdd.rca import evidence as evmod

    monkeypatch.setattr(evmod, "confidence_sql_module", lambda: None)
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE rule_result (site_id TEXT, equipment_id TEXT, rule_id TEXT, "
        "window_start TEXT, window_end TEXT, status TEXT)"
    )
    padded = [
        " ALARM ",
        chr(9) + "ALARM" + chr(9),
        chr(10) + "ALARM" + chr(10),
    ]
    for i, status in enumerate(padded):
        conn.execute(
            "INSERT INTO rule_result VALUES (?, 'ahu-1', 'SAT-HIGH', "
            "'2026-11-24T10:00:00Z', '2026-11-24T10:15:00Z', ?)",
            (f"site-{i}", status),
        )
    for i, _status in enumerate(padded):
        faults = evmod.SqlEvidenceCollector(conn, fault_status=("ALARM",)).load(site_id=f"site-{i}").all_faults()
        assert len(faults) == 1, _status
        assert faults[0].status == "ALARM"
    assert evmod.sql_placeholder(conn) == "?"
    conn.close()


def test_mixed_modeled_and_inferred_path_is_labeled_mixed():
    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.infer import InferredEdge

    ttl = """
@prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix rec: <urn:example:mix#> .
    rec:ahu-1 s223:connectedTo rec:zone-1 .
    rec:chiller-1 a brick:Chiller .
    rec:ahu-1 a brick:AHU .
    rec:zone-1 a brick:HVAC_Zone .
    """
    g = load_graph(ttl)
    inferred = g.with_inferred_edges(
        [
            InferredEdge(
                upstream_iri="urn:example:mix#chiller-1",
                downstream_iri="urn:example:mix#ahu-1",
                upstream_id="chiller-1",
                downstream_id="ahu-1",
                upstream_label="chiller-1",
                downstream_label="ahu-1",
                confidence=0.8,
            )
        ]
    )
    tr = inferred.traverse_upstream("zone-1")
    assert tr.topology_source == "mixed (modeled + inferred, not modeled)"
    assert tr.inferred_edges_used == 1
    assert any(not h.inferred or "mixed" in h.topology_source for h in tr.ancestors)


def test_infer_skips_cross_site_pairs_and_shared_points(tmp_path):
    import csv
    from datetime import datetime, timedelta

    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.infer import infer_topology, load_telemetry_csv

    ttl = """
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix s1: <urn:example:site/a#> .
    @prefix s2: <urn:example:site/b#> .

    s1:site a phIoT:site ; rdfs:label "plant-a" .
    s2:site a phIoT:site ; rdfs:label "plant-b" .
    s1:ahu a brick:AHU ; rdfs:label "AHU-A" ; phIoT:siteRef s1:site .
    s1:vav a brick:VAV ; rdfs:label "VAV-A" ; phIoT:siteRef s1:site .
    s2:vav a brick:VAV ; rdfs:label "VAV-B" ; phIoT:siteRef s2:site .
    s1:sat a brick:Supply_Air_Temperature_Sensor ; phIoT:equipRef s1:ahu, s1:vav ; rdfs:label "SAT shared" .
    s2:dat a brick:Discharge_Air_Temperature_Sensor ; phIoT:equipRef s2:vav ; rdfs:label "DAT-B" .
    """
    csv_path = tmp_path / "h.csv"
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "sat", "dat"])
        for i in range(40):
            sig = 285.0 + ((i % 6) - 2.5)
            w.writerow([(t0 + timedelta(minutes=15 * i)).isoformat(), sig, sig])
    edges = infer_topology(load_graph(ttl), load_telemetry_csv(csv_path), min_correlation=0.5, min_samples=20)
    pairs = {(e.upstream_label, e.downstream_label) for e in edges}
    assert ("AHU-A", "VAV-B") not in pairs
    assert all(e.upstream_point != e.downstream_point or e.upstream_iri == e.downstream_iri for e in edges)
    assert all(e.upstream_point != "SAT shared" or e.downstream_point != "SAT shared" for e in edges)


def test_suggested_links_ttl_flattens_multiline_labels():
    import rdflib

    from open_fdd.rca.infer import InferredEdge, suggested_links_to_ttl

    nl = chr(10)
    edges = [
        InferredEdge(
            upstream_iri="urn:ex:ahu",
            downstream_iri="urn:ex:vav",
            upstream_id="ahu",
            downstream_id="vav",
            upstream_label=f"AHU West{nl}Second floor",
            downstream_label="VAV-1",
            confidence=0.7,
            evidence=(f"line1{nl}line2",),
        )
    ]
    ttl = suggested_links_to_ttl(edges)
    for line in ttl.splitlines():
        stripped = line.strip()
        assert stripped.startswith(("@", "#", "<", "s223:")) or not stripped
    parsed = rdflib.Graph()
    parsed.parse(data=ttl, format="turtle")
    assert len(parsed) == 4


def test_load_telemetry_csv_filters_by_site(tmp_path):
    from datetime import datetime, timedelta

    from open_fdd.rca.infer import load_telemetry_csv

    path = tmp_path / "t.csv"
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    nl = chr(10)
    rows = ["timestamp,site_id,point_key,value" + nl]
    for i in range(5):
        ts = (t0 + timedelta(minutes=15 * i)).isoformat()
        rows.append(f"{ts},plant-a,sat,{280 + i}" + nl)
        rows.append(f"{ts},plant-b,sat,{10 + i}" + nl)
    path.write_text("".join(rows), encoding="utf-8")
    series_a = load_telemetry_csv(path, site_id="plant-a")
    assert len(series_a[("plant-a", "sat")]) == 5
    assert series_a[("plant-a", "sat")][0][1] == 280
    assert ("plant-b", "sat") not in series_a
    series_all = load_telemetry_csv(path)
    assert set(series_all) == {("plant-a", "sat"), ("plant-b", "sat")}
    assert len(series_all[("plant-a", "sat")]) == 5
    assert len(series_all[("plant-b", "sat")]) == 5
    assert series_all[("plant-a", "sat")][0][1] == 280
    assert series_all[("plant-b", "sat")][0][1] == 10


def test_infer_keeps_same_site_iri_with_distinct_site_ids(tmp_path):
    import csv
    from datetime import datetime, timedelta

    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.infer import infer_topology, load_telemetry_csv

    ttl = """
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix s1: <urn:example:site/a#> .

    s1:site a phIoT:site .
    s1:ahu a brick:AHU ; rdfs:label "AHU-A" ; phIoT:siteRef s1:site ; phIoT:siteId "campus-west" .
    s1:vav a brick:VAV ; rdfs:label "VAV-A" ; phIoT:siteRef s1:site ; phIoT:siteId "wing-2" .
    s1:sat a brick:Supply_Air_Temperature_Sensor ; phIoT:equipRef s1:ahu ; rdfs:label "SAT-A" .
    s1:dat a brick:Discharge_Air_Temperature_Sensor ; phIoT:equipRef s1:vav ; rdfs:label "DAT-A" .
    """
    g = load_graph(ttl)
    ahu = g.resolve_node("AHU-A")
    vav = g.resolve_node("VAV-A")
    assert ahu is not None and vav is not None
    assert ahu.site_iri == vav.site_iri != ""
    assert ahu.site_id != vav.site_id
    csv_path = tmp_path / "h.csv"
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "sat", "dat"])
        for i in range(40):
            sig = 285.0 + ((i % 6) - 2.5)
            w.writerow([(t0 + timedelta(minutes=15 * i)).isoformat(), sig, sig + 0.2])
    edges = infer_topology(g, load_telemetry_csv(csv_path), min_correlation=0.5, min_samples=20)
    pairs = {(e.upstream_label, e.downstream_label) for e in edges}
    assert ("AHU-A", "VAV-A") in pairs


def test_cli_infer_warns_when_default_history_table_missing(tmp_path, capsys):
    import json

    from open_fdd.rca.cli import main

    ttl = tmp_path / "model.ttl"
    ttl.write_text(
        """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <urn:test:skip#> .
ex:ahu-1 a brick:AHU ; rdfs:label "AHU-1" .
""",
        encoding="utf-8",
    )
    db = tmp_path / "fdd.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE rule_result (equipment_id TEXT, rule_id TEXT, "
        "window_start TEXT, window_end TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO rule_result VALUES ('ahu-1', 'SAT-HIGH', "
        "'2026-03-01T02:00:00Z', '2026-03-01T04:00:00Z', 'FAULT')"
    )
    conn.commit()
    conn.close()
    out_dir = tmp_path / "out"
    rc = main([
        "--graph", str(ttl),
        "--sqlite", str(db),
        "--infer-topology",
        "--out-dir", str(out_dir),
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "inference skipped" in err
    report = json.loads((out_dir / "rca_report.json").read_text(encoding="utf-8"))
    meta = report["source"]["inferred_topology"]
    assert meta["enabled"] is True
    assert meta["proposed_edges"] == 0
    assert "skipped" in meta


def test_open_sql_collector_rejects_missing_explicit_history_table(tmp_path):
    from open_fdd.rca.cli import _open_sql_collector, build_parser

    db = tmp_path / "fdd.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE rule_result (equipment_id TEXT, rule_id TEXT, "
        "window_start TEXT, window_end TEXT, status TEXT)"
    )
    conn.commit()
    conn.close()
    args = build_parser().parse_args([
        "--sqlite", str(db),
        "--graph", "unused.ttl",
        "--history-table", "nope",
    ])
    with pytest.raises(ValueError, match="history table"):
        _open_sql_collector(args)


def test_unscoped_telemetry_does_not_correlate_across_sites(tmp_path):
    import csv
    from datetime import datetime, timedelta

    from open_fdd.rca.graph import load_graph
    from open_fdd.rca.infer import (
        infer_topology,
        load_telemetry_csv,
        load_telemetry_sql,
    )

    ttl = """
    @prefix brick: <https://brickschema.org/schema/Brick#> .
    @prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix s1: <urn:example:site/a#> .
    @prefix s2: <urn:example:site/b#> .

    s1:site a phIoT:site ; rdfs:label "plant-a" .
    s2:site a phIoT:site ; rdfs:label "plant-b" .
    s1:ahu a brick:AHU ; rdfs:label "AHU-A" ; phIoT:siteRef s1:site .
    s1:vav a brick:VAV ; rdfs:label "VAV-A" ; phIoT:siteRef s1:site .
    s2:ahu a brick:AHU ; rdfs:label "AHU-B" ; phIoT:siteRef s2:site .
    s2:vav a brick:VAV ; rdfs:label "VAV-B" ; phIoT:siteRef s2:site .
    s1:sat a brick:Supply_Air_Temperature_Sensor ; phIoT:equipRef s1:ahu ; rdfs:label "sat" .
    s1:dat a brick:Discharge_Air_Temperature_Sensor ; phIoT:equipRef s1:vav ; rdfs:label "dat" .
    s2:sat a brick:Supply_Air_Temperature_Sensor ; phIoT:equipRef s2:ahu ; rdfs:label "sat" .
    s2:dat a brick:Discharge_Air_Temperature_Sensor ; phIoT:equipRef s2:vav ; rdfs:label "dat" .
    """
    graph = load_graph(ttl)
    csv_path = tmp_path / "h.csv"
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    rows = []
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "site_id", "point_key", "value"])
        for i in range(40):
            ts = (t0 + timedelta(minutes=15 * i)).isoformat()
            sig_a = 285.0 + ((i % 6) - 2.5)
            sig_b = 260.0 + 2.0 * ((i % 5) - 2.0)
            w.writerow([ts, "plant-a", "sat", sig_a])
            w.writerow([ts, "plant-a", "dat", sig_a + 0.2])
            w.writerow([ts, "plant-b", "sat", sig_b])
            w.writerow([ts, "plant-b", "dat", sig_b - 0.2])
            rows.extend(
                [
                    (ts, "plant-a", "sat", sig_a),
                    (ts, "plant-a", "dat", sig_a + 0.2),
                    (ts, "plant-b", "sat", sig_b),
                    (ts, "plant-b", "dat", sig_b - 0.2),
                ]
            )

    csv_series = load_telemetry_csv(csv_path)
    assert set(csv_series) == {
        ("plant-a", "sat"),
        ("plant-a", "dat"),
        ("plant-b", "sat"),
        ("plant-b", "dat"),
    }
    assert csv_series[("plant-a", "sat")][0][1] != csv_series[("plant-b", "sat")][0][1]

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE input_sample (ts TEXT, site_id TEXT, point_key TEXT, value DOUBLE)"
    )
    conn.executemany("INSERT INTO input_sample VALUES (?, ?, ?, ?)", rows)
    sql_series = load_telemetry_sql(conn)
    conn.close()
    assert set(sql_series) == set(csv_series)
    assert [v for _, v in sql_series[("plant-a", "sat")]] == [v for _, v in csv_series[("plant-a", "sat")]]
    assert [v for _, v in sql_series[("plant-b", "dat")]] == [v for _, v in csv_series[("plant-b", "dat")]]

    for telemetry in (csv_series, sql_series):
        edges = infer_topology(graph, telemetry, min_correlation=0.5, min_samples=20)
        pairs = {(e.upstream_label, e.downstream_label) for e in edges}
        assert ("AHU-A", "VAV-A") in pairs
        assert ("AHU-B", "VAV-B") in pairs
        assert ("AHU-A", "VAV-B") not in pairs
        assert ("AHU-B", "VAV-A") not in pairs


def test_hop_limit_records_unresolved_frontier():
    ttl = """
    @prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix ex: <urn:test:hops:> .
    ex:b a s223:Chiller ; s223:connectedTo ex:a .
    ex:a a s223:AirHandlingUnit ; s223:connectedTo ex:zone .
    ex:zone a s223:Zone .
    """
    tr = load_graph(ttl).traverse_upstream("zone", max_hops=1)
    assert [h.node.node_id for h in tr.ancestors] == ["a"]
    assert tr.upstream_status == "partial_unknown_upstream"
    assert tr.unknown_upstream_at == ["a"]
    completed = load_graph(ttl).traverse_upstream("zone", max_hops=4)
    assert completed.upstream_status == "traced"
    assert [h.node.node_id for h in completed.ancestors] == ["a", "b"]


def test_symptom_filter_uses_resolved_iri():
    ttl = """
    @prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <urn:test:alias:> .
    ex:west a s223:AirHandlingUnit ; rdfs:label "AHU West" ; s223:connectedTo ex:z1 .
    ex:other a s223:AirHandlingUnit ; rdfs:label "ahu west" ; s223:connectedTo ex:z2 .
    ex:z1 a s223:Zone ; rdfs:label "z1" .
    ex:z2 a s223:Zone ; rdfs:label "z2" .
    """
    graph = load_graph(ttl)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="AHU West", rule_id="SAT-HIGH"),
            FaultEvidence(equipment_id="ahu west", rule_id="SAT-HIGH"),
            FaultEvidence(equipment_id="z1", rule_id="ZNT-HIGH"),
            FaultEvidence(equipment_id="z2", rule_id="ZNT-HIGH"),
        ]
    )
    report = analyze_rca(graph, collector, symptom_equip="AHU West")
    assert [t.symptom_equipment for t in report.traces] == ["AHU West"]


def test_timestamps_serialize_as_utc():
    from datetime import datetime, timedelta, timezone

    from open_fdd.rca.rank import _ts_iso

    aware = datetime(2026, 11, 24, 10, 0, 5, tzinfo=timezone(timedelta(hours=2)))
    assert _ts_iso(aware) == "2026-11-24T08:00:05Z"
    naive = datetime(2026, 11, 24, 10, 0, 5)
    assert _ts_iso(naive) == "2026-11-24T10:00:05Z"


def test_long_inline_turtle_is_parsed():
    literal = "N" * 300
    ttl = (
        '@prefix s223: <http://data.ashrae.org/standard223#> . '
        '@prefix ex: <urn:test:long:> . '
        f'ex:ahu a s223:AirHandlingUnit ; <urn:test:long:note> "{literal}" .'
    )
    node = load_graph(ttl).resolve_node("ahu")
    assert node is not None
    assert node.label == "ahu"


def test_display_label_prefers_rdfs_label_and_keeps_haystack_alias():
    ttl = """
    @prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ph: <https://project-haystack.org/def/ph/4.0.0#> .
    @prefix ex: <urn:test:label:> .
    ex:ahu a s223:AirHandlingUnit ; ph:dis "Haystack name" ; rdfs:label "RDF name" .
    """
    node = load_graph(ttl).resolve_node("Haystack name")
    assert node is not None
    assert node.label == "RDF name"
    assert load_graph(ttl).resolve_node("RDF name").iri == node.iri


def test_shared_cause_counts_distinct_downstream_nodes():
    ttl = """
    @prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <urn:test:rollup:> .
    ex:ahu a s223:AirHandlingUnit ; rdfs:label "ahu" ; s223:connectedTo ex:zone .
    ex:zone a s223:Zone ; rdfs:label "Zone 1" ; ex:equipmentId "zone-local" .
    """
    graph = load_graph(ttl)
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="ahu", rule_id="SAT-HIGH"),
            FaultEvidence(equipment_id="zone-local", rule_id="ZNT-HIGH"),
            FaultEvidence(equipment_id="Zone 1", rule_id="ZNT-HIGH"),
        ]
    )
    report = analyze_rca(graph, collector)
    assert report.common_causes == []
    assert len(report.traces) == 2
    assert {t.symptom_equipment for t in report.traces} == {"zone-local", "Zone 1"}


def test_upstream_candidate_is_not_reported_as_no_symptoms():
    ttl = """
    @prefix s223: <http://data.ashrae.org/standard223#> .
    @prefix ex: <urn:test:checks:> .
    ex:ahu a s223:AirHandlingUnit ; s223:connectedTo ex:zone .
    ex:zone a s223:Zone .
    """
    collector = InMemoryEvidenceCollector(
        faults=[
            FaultEvidence(equipment_id="ahu", rule_id="SAT-HIGH"),
            FaultEvidence(equipment_id="zone", rule_id="ZNT-HIGH"),
        ]
    )
    report = analyze_rca(load_graph(ttl), collector)
    from open_fdd.rca.report import next_checks

    checks = next_checks(report)
    assert any(line.startswith("Inspect upstream ahu") for line in checks)
    assert all("No active downstream" not in line for line in checks)
    scoped = analyze_rca(load_graph(ttl), collector, site_id="site-a")
    assert scoped.traces
    assert all(trace.symptom_site == "site-a" for trace in scoped.traces)


def test_pyoxigraph_and_rdflib_versions_are_pinned():
    from importlib.metadata import version

    import pyoxigraph
    import rdflib

    assert rdflib.__version__ == "7.6.0"
    assert version("pyoxigraph") == "0.5.13"
    assert pyoxigraph.Store is not None


def test_roles_vocabulary_ships_inside_the_package(monkeypatch):
    monkeypatch.delenv("OPENFDD_ROLES_JSON", raising=False)
    from open_fdd.rca.role_index import (
        load_role_index,
        roles_json_path,
        setpoint_role_for,
    )

    load_role_index.cache_clear()
    path = roles_json_path()
    assert path is not None
    assert path.name == "openfdd-roles.json"
    assert "rca" in path.parts and "data" in path.parts
    assert load_role_index()["by_role"]
    assert setpoint_role_for("discharge_air_temperature") == "discharge_air_temperature_setpoint"


def test_confidence_window_bounds_apply_to_episode_and_quality_flag():
    from open_fdd.rca.evidence import DataFrameEvidenceCollector

    collector = DataFrameEvidenceCollector.from_confidence_episodes(
        [
            {
                "equipment_id": "ahu-1",
                "rule_id": "SAT-HIGH",
                "window_start": "2026-01-15T00:00:00Z",
                "window_end": "2026-01-15T01:00:00Z",
                "evidence": {"poor_data_quality": True},
            }
        ]
    )
    fault = collector.all_faults()[0]
    assert fault.start == parse_utc("2026-01-15T00:00:00Z")
    assert fault.end == parse_utc("2026-01-15T01:00:00Z")
    flags = collector.all_data_quality()
    assert flags[0].start == fault.start
    assert flags[0].end == fault.end


def test_explicit_quality_warning_keeps_bounds():
    from open_fdd.rca.evidence import _parse_dq_rows

    flags = _parse_dq_rows(
        [
            {
                "equipment_id": "ahu-1",
                "flag": "stale",
                "start": "2026-01-15T00:00:00Z",
                "end": "2026-01-15T01:00:00Z",
            }
        ]
    )
    assert flags[0].start == parse_utc("2026-01-15T00:00:00Z")
    assert flags[0].end == parse_utc("2026-01-15T01:00:00Z")
    undated = _parse_dq_rows([{"equipment_id": "ahu-1", "flag": "stale"}])
    assert undated[0].start is None and undated[0].end is None


def test_sql_flags_layout_accepts_numeric_one(monkeypatch):
    from open_fdd.rca import evidence as evmod

    monkeypatch.setattr(evmod, "confidence_sql_module", lambda: None)
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE flags (timestamp TEXT, equipment_id TEXT, rule_id TEXT, flag INT, site_id TEXT)"
    )
    conn.execute(
        "INSERT INTO flags VALUES ('2026-11-24T10:00:00Z', 'ahu-1', 'SAT-HIGH', 1, 'site-a')"
    )
    faults = evmod.SqlEvidenceCollector(conn, table="flags", layout="flags").load(site_id="site-a").all_faults()
    conn.close()
    assert len(faults) == 1
    assert faults[0].equipment_id == "ahu-1"


def test_history_uses_episode_site_and_setpoint_in_effect():
    from datetime import datetime, timedelta

    from open_fdd.rca.evidence import FaultEvidence, SqlEvidenceCollector

    calls: list[list] = []

    class _FakeCsql:
        def paramstyle(self, conn):
            return "?"

        def history_sql(self, hm, ph, by_site=False):
            return "by-site" if by_site else "open"

        def fetch(self, conn, sql, params):
            calls.append([sql, *params])
            cols = ["ts", "point_id", "value"]
            if params[-1] == "site-b":
                rows = [
                    ("2026-03-01T10:00:00Z", "sat", 290.0),
                    ("2026-03-01T10:00:00Z", "sat-sp", 290.0),
                    ("2026-03-01T10:05:00Z", "sat-sp", 295.0),
                ]
            else:
                rows = [("2026-03-01T10:00:00Z", "sat", 280.0), ("2026-03-01T10:00:00Z", "sat-sp", 280.0)]
            return cols, rows

    class _FakeHist:
        def col(self, name):
            return "site_id" if name == "site_id" else None

    start = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    faults = [
        FaultEvidence(equipment_id="ahu-1", rule_id="SAT-HIGH", start=start, end=start + timedelta(hours=1), site_id="site-a"),
        FaultEvidence(equipment_id="ahu-1", rule_id="SAT-HIGH", start=start, end=start + timedelta(hours=1), site_id="site-b"),
    ]
    devs = SqlEvidenceCollector(sqlite3.connect(":memory:"))._load_history_deviations(
        _FakeCsql(), _FakeHist(), faults, site_id="site-a"
    )
    assert [call[0] for call in calls] == ["by-site", "by-site"]
    assert calls[0][-1] == "site-a"
    assert calls[1][-1] == "site-b"
    by_site = {d.site_id: d for d in devs}
    assert by_site["site-b"].value_si == 290.0
    assert by_site["site-b"].setpoint_si == 290.0
    assert by_site["site-a"].setpoint_si == 280.0


def test_conflicting_owner_sites_leave_a_point_unscoped():
    ttl = """
    @prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <urn:test:sites:> .
    ex:site-a a phIoT:site ; rdfs:label "site-a" .
    ex:site-b a phIoT:site ; rdfs:label "site-b" .
    ex:ahu-a a phIoT:ahu ; phIoT:siteRef ex:site-a .
    ex:ahu-b a phIoT:ahu ; phIoT:siteRef ex:site-b .
    ex:sat a phIoT:point ; phIoT:equipRef ex:ahu-a, ex:ahu-b .
    """
    graph = load_graph(ttl)
    point = graph.resolve_node("sat")
    assert point is not None
    assert graph._site_tokens(point) == set()


def test_sparql_store_is_reused():
    graph = load_graph(EXAMPLE_PLANT_TTL)
    zone = graph.resolve_node("zone-1")
    assert zone is not None
    graph.sparql_upstream(zone.iri)
    first = graph._sparql_store
    graph.sparql_upstream(zone.iri)
    assert graph._sparql_store is first
    assert first is not None


def test_setpoint_aspect_is_not_a_topology_signal():
    from open_fdd.rca.graph import S223, GraphNode
    from open_fdd.rca.infer import _classify_point

    setpoint = GraphNode(
        iri="urn:test:sp",
        node_id="opaque-sp",
        label="SAT",
        is_point=True,
        aspects=(S223 + "Aspect-Setpoint",),
    )
    measured = GraphNode(
        iri="urn:test:dat",
        node_id="opaque-dat",
        label="opaque-dat",
        is_point=True,
        property_roles=("discharge_air_temperature",),
    )
    assert _classify_point(setpoint) == ("ignore", "")
    assert _classify_point(measured) == ("temp_air_out", "air")


def test_inferred_connection_iris_do_not_collide():
    import rdflib

    from open_fdd.rca.infer import InferredEdge, suggested_links_to_ttl

    def edge(up, down):
        return InferredEdge(
            upstream_iri=up,
            downstream_iri=down,
            upstream_id=up,
            downstream_id=down,
            upstream_label=up,
            downstream_label=down,
            confidence=0.5,
        )

    first = suggested_links_to_ttl([edge("urn:ex:a", "urn:ex:b")])
    second = suggested_links_to_ttl([edge("urn:ex:c", "urn:ex:d")])
    assert "connection:1" not in first
    assert first.split(" a s223:Connection", 1)[0].split("<")[-1] != second.split(" a s223:Connection", 1)[0].split("<")[-1]
    merged = rdflib.Graph()
    merged.parse(data=first, format="turtle")
    merged.parse(data=second, format="turtle")
    pairs = {
        (str(src), str(dst))
        for conn in merged.subjects(rdflib.RDF.type, rdflib.URIRef("http://data.ashrae.org/standard223#Connection"))
        for src in merged.objects(conn, rdflib.URIRef("http://data.ashrae.org/standard223#connectsFrom"))
        for dst in merged.objects(conn, rdflib.URIRef("http://data.ashrae.org/standard223#connectsTo"))
    }
    assert pairs == {("urn:ex:a", "urn:ex:b"), ("urn:ex:c", "urn:ex:d")}


def test_inferred_node_short_id_resolves():
    from open_fdd.rca.infer import InferredEdge

    graph = load_graph(EXAMPLE_PLANT_TTL).with_inferred_edges(
        [
            InferredEdge(
                upstream_iri="urn:openfdd:inferred:new-ahu",
                downstream_iri="urn:openfdd:example:plant:vav-1",
                upstream_id="new-ahu",
                downstream_id="vav-1",
                upstream_label="new-ahu",
                downstream_label="vav-1",
                confidence=0.6,
            )
        ]
    )
    node = graph.resolve_node("new-ahu")
    assert node is not None
    assert node.iri == "urn:openfdd:inferred:new-ahu"


def test_false_positive_penalty_applies_without_p_real():
    from open_fdd.rca.graph import GraphNode, UpstreamHop
    from open_fdd.rca.rank import _score_candidate

    hop = UpstreamHop(
        node=GraphNode(iri="urn:x:ahu", node_id="ahu", label="ahu"),
        hop=1,
        path=("ahu", "zone"),
        relations=("s223:connectedTo",),
    )
    symptom = FaultEvidence(equipment_id="zone", rule_id="ZNT-HIGH")
    high = _score_candidate(
        symptom,
        hop,
        FaultEvidence(equipment_id="ahu", rule_id="SAT-HIGH", p_false_positive=0.99),
        [],
        [],
        1,
    )
    low = _score_candidate(
        symptom,
        hop,
        FaultEvidence(equipment_id="ahu", rule_id="SAT-HIGH", p_false_positive=0.01),
        [],
        [],
        1,
    )
    assert high.confidence < low.confidence


def test_json_report_rejects_non_finite_numbers():
    from open_fdd.rca.rank import CauseTrace, RCAReport
    from open_fdd.rca.report import report_to_json

    report = RCAReport(
        traces=[
            CauseTrace(
                symptom_equipment="zone-1",
                symptom_rule="ZNT-HIGH",
                symptom_site="site-a",
                symptom_start="2026-01-15T00:00:00Z",
                symptom_end="2026-01-15T01:00:00Z",
                upstream_status="unknown_upstream",
                unknown_upstream=True,
                unknown_upstream_at=["zone-1"],
                candidates=[],
            )
        ],
        common_causes=[],
        totals={"symptoms_analyzed": float("inf")},
    )
    text = report_to_json(report)
    payload = json.loads(text)
    assert payload["totals"]["symptoms_analyzed"] is None
    assert "Infinity" not in text


def test_markdown_trace_names_site_and_window():
    graph = load_graph(EXAMPLE_PLANT_TTL)
    report = analyze_rca(
        graph,
        InMemoryEvidenceCollector(
            faults=[
                FaultEvidence(
                    equipment_id="zone-1",
                    rule_id="ZNT-HIGH",
                    site_id="Example Building",
                    start=parse_utc("2026-11-24T10:00:00Z"),
                    end=parse_utc("2026-11-24T12:00:00Z"),
                )
            ]
        ),
    )
    md = report_to_markdown(report)
    assert "site=Example Building" in md
    assert "window=2026-11-24T10:00:00Z..2026-11-24T12:00:00Z" in md
