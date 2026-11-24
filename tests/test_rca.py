"""Tests for open_fdd.rca: RDF topology traversal, evidence, ranking, and CLI."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")

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
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/> .
@prefix local: <urn:test:partial:> .

local:ahu-1 a brick:Air_Handling_Unit ; phIoT:siteRef local:site-1 .
local:vav-orphan a brick:VAV ; brick:feeds local:zone-orphan .
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
@prefix phIoT: <https://project-haystack.org/def/phIoT/> .
@prefix local: <urn:test:multi:> .

local:boiler-1 a phIoT:boiler .
local:ahu-a a brick:Air_Handling_Unit ; phIoT:hotWaterRef local:boiler-1 .
local:vav-a a brick:VAV ; phIoT:airRef local:ahu-a .
local:zone-a a brick:HVAC_Zone ; brick:isFedBy local:vav-a .

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
local:loop-1 a brick:AHU ; brick:feeds local:loop-2 .
local:loop-2 a brick:AHU ; brick:feeds local:loop-1 .
"""
    graph = load_graph(ttl)

    # SPARQL property path on Brick + Haystack chain
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

    # Custom SPARQL runner fallback/extension
    tr_custom = graph.traverse_upstream(
        "zone-a",
        sparql_runner=lambda _q: [{"upstream": "urn:test:multi:extra-plant"}],
    )
    assert any(h.node.node_id == "extra-plant" for h in tr_custom.ancestors)


def test_temporal_precedence_and_data_quality_discount():
    ttl = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/> .
@prefix local: <urn:test:prec:> .

local:chiller-1 a brick:Chiller ; brick:feeds local:ahu-1 .
local:ahu-1 a brick:Air_Handling_Unit ; brick:feeds local:zone-1 .
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
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix local: <urn:test:sites:> .

local:site-a a phIoT:site ; rdfs:label "site-a" .
local:site-b a phIoT:site ; rdfs:label "site-b" .

local:a-ahu-1 a brick:Air_Handling_Unit ; rdfs:label "AHU-1" ; phIoT:siteRef local:site-a ; brick:feeds local:a-zone-1 .
local:a-zone-1 a brick:HVAC_Zone ; rdfs:label "Zone-1" ; phIoT:siteRef local:site-a .

local:b-ahu-1 a brick:Air_Handling_Unit ; rdfs:label "AHU-1" ; phIoT:siteRef local:site-b ; brick:feeds local:b-zone-1 .
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
    conn.execute("INSERT INTO point VALUES ('site-a', 'discharge-air-temp', 'ahu-1', 'Number')")
    conn.execute("INSERT INTO point VALUES ('site-a', 'discharge-air-temp-sp', 'ahu-1', 'Number')")
    conn.execute("INSERT INTO input_sample VALUES ('site-a', 'discharge-air-temp', '2026-11-24T10:10:00Z', 18.5)")
    conn.execute("INSERT INTO input_sample VALUES ('site-a', 'discharge-air-temp-sp', '2026-11-24T10:10:00Z', 13.0)")
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
    assert "discharge-air-temp" in devs
    assert devs["discharge-air-temp"].value_si == 18.5
    assert devs["discharge-air-temp"].setpoint_si == 13.0
    assert devs["discharge-air-temp"].resolved_deviation_si == 5.5
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

