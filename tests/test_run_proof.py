"""Run-proof resolution and gate (#1608): the pure resolver on an NF model and on the RDF export (same answers, same as the
JS twin nf-app/static/run-proof.js), and the pandas gate: no proof -> SKIPPED no_run_proof, proof -> off samples do not count."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from open_fdd.nf.model import Model, to_point
from open_fdd.rules import RULES_BY_ID
from open_fdd.rules.runner import run_cookbook_rule
from open_fdd.run_proof import (
    ProofNode, derive_run_proof, nodes_from_graph, nodes_from_model, proof_on, resolve_run_proof, run_proof_gated_ids,
    spec, sweep_gate_mask,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "run_proof_model.json"

# (tier, source, equip that carries the proof, via) per site/equip; None = no proof (SKIPPED no_run_proof)
EXPECTED = {
    "s1/AHU-1": ("own", "status", "AHU-1", "self"),
    "s1/AHU-2": ("own", "command", "AHU-2", "self"),
    "s1/AHU-3": None,
    "s1/VAV-1": ("feeder", "status", "AHU-1", "airRef"),
    "s1/VAV-2": ("feeder", "command", "AHU-2", "airRef"),
    "s1/VAV-3": None,
    "s1/VAV-4": None,                                            # its AHU has no proof either
    "s1/CHWP-1": ("own", "status", "CHWP-1", "self"),
    "s1/CHWP-B": ("own", "status", "CHWP-B", "self"),
    "s1/HWP-1": ("own", "status", "HWP-1", "self"),
    "s1/CHW-LOOP-A": ("feeder", "status", "CHWP-1", "chilledWaterRef"),
    "s1/CHW-LOOP-B": ("feeder", "status", "CHWP-B", "feeds"),   # brick:feeds from the pump
    "s1/CHW-LOOP-C": ("feeder", "status", "CHWP-1", "isFedBy"),  # brick:isFedBy to the pump
    "s1/CHW-LOOP-D": None,
    "s1/HW-LOOP": ("feeder", "status", "HWP-1", "hotWaterRef"),
    "s2/VAV-9": None,                                            # airRef AHU-1 exists only in the other site
}


def _records():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]


def _model() -> Model:
    recs = _records()
    of = lambda t: [r for r in recs if r["pointType"] == t]  # noqa: E731
    return Model(of("SITE"), of("EQUIPMENT"), [], [to_point(r) for r in of("POINT")])


def _shape(r):
    return None if not r.found else (r.tier, r.source, r.equip, r.via)


def _resolve_all(nodes):
    contract = spec()
    return {f"{n.site}/{n.id}": _shape(resolve_run_proof(n, nodes, contract)) for n in nodes}


def test_resolution_on_an_nf_model():
    assert _resolve_all(nodes_from_model(_model())) == EXPECTED


def _graph():
    rdflib = pytest.importorskip("rdflib")
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required")
    out = ROOT / "tests" / "fixtures" / "_run_proof.ttl"
    try:
        subprocess.run([node, str(ROOT / "tools/rdf-check/gen_ttl.js"), str(FIXTURE), str(out)], check=True, capture_output=True)
        g = rdflib.Graph()
        g.parse(str(out), format="turtle")
    finally:
        out.unlink(missing_ok=True)
    return g


def test_resolution_on_the_rdf_export_gives_the_same_answers():
    g = _graph()
    nodes = nodes_from_graph(g)
    got = _resolve_all(nodes)
    # the Turtle subject of a site is its id; the RDF site key is therefore the same
    assert got == EXPECTED


def test_rdf_carries_airref_and_brick_feeds_and_isfedby():
    g = _graph()
    text = g.serialize(format="nt")
    assert "airRef" in text and "chilledWaterRef" in text and "hotWaterRef" in text
    assert "Brick#feeds" in text and "Brick#isFedBy" in text


def test_sparql_finds_the_feeding_equipment():
    g = _graph()
    q = """
    PREFIX phIoT: <https://project-haystack.org/def/phIoT/>
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?consumer ?feeder WHERE {
      { ?c phIoT:airRef ?f } UNION { ?c phIoT:chilledWaterRef ?f } UNION { ?c phIoT:hotWaterRef ?f }
      UNION { ?c brick:isFedBy ?f } UNION { ?f brick:feeds ?c }
      ?c rdfs:label ?consumer . ?f rdfs:label ?feeder }
    """
    pairs = {(str(a), str(b)) for a, b in g.query(q)}
    assert {("VAV-1", "AHU-1"), ("VAV-2", "AHU-2"), ("CHW-LOOP-A", "CHWP-1"), ("CHW-LOOP-B", "CHWP-B"),
            ("CHW-LOOP-C", "CHWP-1"), ("HW-LOOP", "HWP-1")} <= pairs


def test_a_ref_never_crosses_sites_and_never_guesses():
    a = ProofNode("AHU-1", "x", roles=frozenset({"fan_status"}))
    v = ProofNode("VAV-1", "y", refs={"airRef": "AHU-1"})
    assert not resolve_run_proof(v, [a, v], spec()).found
    v2 = ProofNode("VAV-2", "x")                                  # no ref: the only AHU of the site is NOT assumed
    assert not resolve_run_proof(v2, [a, v2], spec()).found


def test_own_status_beats_own_command_and_feeder_order_is_the_contract_order():
    c = spec()
    both = ProofNode("A", "s", roles=frozenset({"fan_cmd", "fan_status"}))
    assert resolve_run_proof(both, [both], c).role == "fan_status"
    p1 = ProofNode("P1", "s", roles=frozenset({"pump_status"}))
    p2 = ProofNode("P2", "s", roles=frozenset({"fan_status"}))
    loop = ProofNode("L", "s", refs={"hotWaterRef": "P1", "airRef": "P2"})
    r = resolve_run_proof(loop, [p1, p2, loop], c)
    assert (r.equip, r.via) == ("P2", "airRef")                   # airRef is listed before hotWaterRef


# ---------------------------------------------------------------------------- the pandas gate
def _vav(proof: str = "none", hours: int = 12):
    """A VAV frame for VAV-3 (excessive reheat): reheat valve open all the time against a hot outside-air temperature.
    proof: none | resolved (a run-proof column that is on for the first half) | status (its own fan status)."""
    idx = pd.date_range("2026-01-05", periods=hours * 12, freq="5min", tz="UTC")
    df = pd.DataFrame(index=idx)
    df["outside-air-temp"] = 30.0                  # hot outside while the reheat valve is wide open
    df["reheat-valve"] = 0.9
    df["zone-airflow"] = 100.0                     # air is on (VAV-3 also needs it)
    on = [1.0 if i < len(idx) // 2 else 0.0 for i in range(len(idx))]
    if proof == "resolved":
        df["run-proof"] = on
    elif proof == "status":
        df["fan-status"] = on
    df.attrs["equipment_id"] = "EQ"
    df.attrs["equipment_type"] = "VAV"
    return df


def _run(rule_id, df, **params):
    return run_cookbook_rule(RULES_BY_ID[rule_id], df.copy(), equipment_id="EQ", equipment_kind="vav", poll_seconds=300.0,
                             params_by_rule={rule_id: {"confirm_min": 0, "startup_delay_min": 0, **params}})


def test_derive_run_proof_prefers_the_resolved_column_then_own_status_then_command():
    s, src = derive_run_proof(_vav("status"))
    assert src == "fan-status" and int(proof_on(s).sum()) == 6 * 12
    df = _vav("status")
    df["run-proof"] = 1.0
    s, src = derive_run_proof(df)
    assert src == "run-proof" and bool(proof_on(s).all())
    cmd = _vav()
    cmd["fan-cmd"] = 0.5
    assert derive_run_proof(cmd)[1] == "fan-cmd"
    assert derive_run_proof(_vav())[0] is None


def test_gated_rule_without_proof_is_skipped_never_pass():
    res = _run("VAV-3", _vav())
    assert res.status == "SKIPPED_NO_RUN_PROOF" and res.metrics["skip_reason"] == "no_run_proof"
    assert res.fault_hours is None and res.confirmed_fault is None
    assert "VAV-3" in run_proof_gated_ids() and "CMD-1" not in run_proof_gated_ids()


def test_off_samples_do_not_count_and_the_gate_off_restores_the_ungated_verdict():
    gated = _run("VAV-3", _vav("resolved"))
    assert gated.status == "FAULT"
    assert gated.fault_hours == pytest.approx(5.9167, abs=0.1)         # only the first (running) half: 6 h minus the last hold
    ungated = _run("VAV-3", _vav("resolved"), require_run_proof=0)
    assert ungated.fault_hours > gated.fault_hours * 1.8                  # the off half counts again with the gate off
    alias = _run("VAV-3", _vav("resolved"), require_operational_gate=0)   # the old name is an alias
    assert alias.fault_hours == pytest.approx(ungated.fault_hours)


def test_own_status_is_the_proof_without_a_resolved_column():
    own = _run("VAV-3", _vav("status"))
    resolved = _run("VAV-3", _vav("resolved"))
    assert own.fault_hours == pytest.approx(resolved.fault_hours)


def test_sweep_gate_mask():
    df = _vav("resolved")
    assert int(sweep_gate_mask(df, {}).sum()) == 6 * 12
    assert bool(sweep_gate_mask(df, {"require_run_proof": 0}).all())
    assert not sweep_gate_mask(_vav(), {}).any()


def test_sensor_sweeps_honour_the_gate():
    idx = pd.date_range("2026-01-05", periods=288, freq="5min", tz="UTC")
    df = pd.DataFrame({"outside-air-temp": 90.0, "run-proof": [1.0 if i < 144 else 0.0 for i in range(288)]}, index=idx)
    df.attrs.update(equipment_id="EQ", equipment_type="AHU", role_units={"outside-air-temp": "°C"})
    on = run_cookbook_rule(RULES_BY_ID["SV-RANGE"], df.copy(), equipment_id="EQ", equipment_kind="ahu", poll_seconds=300.0,
                           params_by_rule={"SV-RANGE": {"confirm_min": 0}})
    off = run_cookbook_rule(RULES_BY_ID["SV-RANGE"], df.copy(), equipment_id="EQ", equipment_kind="ahu", poll_seconds=300.0,
                            params_by_rule={"SV-RANGE": {"confirm_min": 0, "require_run_proof": 0}})
    assert 0 < on.fault_hours < off.fault_hours
    none = df.drop(columns=["run-proof"])
    res = run_cookbook_rule(RULES_BY_ID["SV-RANGE"], none, equipment_id="EQ", equipment_kind="ahu", poll_seconds=300.0)
    assert res.status == "SKIPPED_NO_RUN_PROOF"

def test_the_global_gate_switch_also_ungates_sweeps():
    idx = pd.date_range("2026-01-05", periods=288, freq="5min", tz="UTC")
    none = pd.DataFrame({"outside-air-temp": 90.0}, index=idx)
    none.attrs.update(equipment_id="EQ", equipment_type="AHU", role_units={"outside-air-temp": "\u00b0C"})
    gated = run_cookbook_rule(RULES_BY_ID["SV-RANGE"], none.copy(), equipment_id="EQ", equipment_kind="ahu", poll_seconds=300.0,
                              params_by_rule={"SV-RANGE": {"confirm_min": 0}})
    assert gated.status == "SKIPPED_NO_RUN_PROOF"
    ungated = run_cookbook_rule(RULES_BY_ID["SV-RANGE"], none.copy(), equipment_id="EQ", equipment_kind="ahu", poll_seconds=300.0,
                                params_by_rule={"SV-RANGE": {"confirm_min": 0}}, require_operational_gates=False)
    assert ungated.fault_hours and ungated.fault_hours > 0


def test_ambiguous_feeder_name_binds_nothing():
    a = ProofNode("A", "s", aliases=("shared",), roles=frozenset({"fan_status"}))
    b = ProofNode("B", "s", aliases=("shared",), roles=frozenset({"fan_status"}))
    v = ProofNode("V", "s", refs={"airRef": "shared"})
    assert not resolve_run_proof(v, [a, b, v], spec()).found


def test_a_ref_that_also_names_the_requester_binds_nothing():
    # the requester carries the referenced alias too: two same-site matches, so the reference is ambiguous
    a = ProofNode("A", "s", aliases=("shared",), roles=frozenset({"fan_status"}))
    v = ProofNode("V", "s", aliases=("shared",), refs={"airRef": "shared"})
    assert not resolve_run_proof(v, [a, v], spec()).found
    # a ref that names only the requester is not a feeder either
    w = ProofNode("W", "s", aliases=("me",), refs={"airRef": "me"})
    assert not resolve_run_proof(w, [a, w], spec()).found


def test_explicit_off_proof_is_assessed_zero_not_missing_proof():
    df = _vav("resolved")
    df["run-proof"] = 0.0
    result = _run("VAV-3", df)
    assert result.status != "SKIPPED_NO_RUN_PROOF"
    assert result.fault_hours == 0


def test_stale_proof_samples_do_not_prove_operation():
    stale = _vav("resolved")
    stale["run-proof"] = [1.0 if i < len(stale) // 2 else float("nan") for i in range(len(stale))]   # proof stops reporting
    assert _run("VAV-3", stale).fault_hours == pytest.approx(_run("VAV-3", _vav("resolved")).fault_hours)   # missing != running
    gone = _vav("resolved")
    gone["run-proof"] = float("nan")                                                     # no proof sample at all: skipped
    assert _run("VAV-3", gone).status == "SKIPPED_NO_RUN_PROOF"


def test_rdf_equipment_sharing_a_label_keeps_its_own_identity():
    rdflib = pytest.importorskip("rdflib")
    ttl = """
@prefix phIoT: <https://project-haystack.org/def/phIoT/3.9.13#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix local: <urn:test:> .
local:s1 a phIoT:site ; rdfs:label "Site" .
local:AHU-1 a phIoT:equip ; rdfs:label "AHU" ; phIoT:siteRef local:s1 .
local:AHU-2 a phIoT:equip ; rdfs:label "AHU" ; phIoT:siteRef local:s1 .
local:VAV-1 a phIoT:equip ; rdfs:label "VAV" ; phIoT:siteRef local:s1 ; phIoT:airRef local:AHU-2 .
"""
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    nodes = {n.id: n for n in nodes_from_graph(g)}
    assert {"AHU-1", "AHU-2", "VAV"} <= set(nodes)  # a shared label falls back to each subject's own name
    assert nodes["VAV"].refs.get("airRef") == "AHU-2"


def test_rdf_a_fallback_name_never_collides_with_another_subjects_label():
    rdflib = pytest.importorskip("rdflib")
    ttl = """
@prefix phIoT: <https://project-haystack.org/def/phIoT/3.9.13#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix local: <urn:test:> .
local:s1 a phIoT:site ; rdfs:label "Site" .
local:s2 a phIoT:site ; rdfs:label "Site" .
local:s3 a phIoT:site ; rdfs:label "s1" .
local:A1 a phIoT:equip ; rdfs:label "A1" ; phIoT:siteRef local:s1 .
local:A3 a phIoT:equip ; rdfs:label "A3" ; phIoT:siteRef local:s3 .
"""
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    sites = {n.id: n.site for n in nodes_from_graph(g)}
    assert sites["A1"] != sites["A3"]


def test_rdf_identities_stay_unique_even_when_a_label_spells_another_subjects_iri():
    rdflib = pytest.importorskip("rdflib")
    ttl = """
@prefix phIoT: <https://project-haystack.org/def/phIoT/3.9.13#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix local: <urn:test:> .
@prefix other: <urn:other:> .
local:s1 a phIoT:site ; rdfs:label "Site" .
other:s1 a phIoT:site ; rdfs:label "Site" .
local:s3 a phIoT:site ; rdfs:label "urn:test:s1" .
local:A1 a phIoT:equip ; rdfs:label "A1" ; phIoT:siteRef local:s1 .
local:A2 a phIoT:equip ; rdfs:label "A2" ; phIoT:siteRef other:s1 .
local:A3 a phIoT:equip ; rdfs:label "A3" ; phIoT:siteRef local:s3 .
"""
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    sites = {n.id: n.site for n in nodes_from_graph(g)}
    assert len({sites["A1"], sites["A2"], sites["A3"]}) == 3


def test_rdf_a_shared_subject_name_is_not_an_alias():
    pytest.importorskip("rdflib")
    import rdflib
    ttl = """
@prefix phIoT: <https://project-haystack.org/def/phIoT/3.9.13#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix local: <urn:test:> .
@prefix other: <urn:other:> .
local:s1 a phIoT:site ; rdfs:label "Site" .
local:unit a phIoT:equip ; rdfs:label "A" ; phIoT:siteRef local:s1 .
other:unit a phIoT:equip ; rdfs:label "unit" ; phIoT:siteRef local:s1 .
"""
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    names = [n.names() for n in nodes_from_graph(g)]
    assert sum("unit" in ns for ns in names) <= 1


def test_a_ref_matching_one_id_and_another_dis_binds_nothing_in_both_resolvers():
    rdflib = pytest.importorskip("rdflib")
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required")
    fx = ROOT / "tests" / "fixtures" / "run_proof_collision.json"
    recs = json.loads(fx.read_text(encoding="utf-8"))["records"]
    of = lambda t: [r for r in recs if r["pointType"] == t]  # noqa: E731
    model_nodes = nodes_from_model(Model(of("SITE"), of("EQUIPMENT"), [], [to_point(r) for r in of("POINT")]))
    out = ROOT / "tests" / "fixtures" / "_run_proof_collision.ttl"
    try:
        subprocess.run([node, str(ROOT / "tools/rdf-check/gen_ttl.js"), str(fx), str(out)], check=True, capture_output=True)
        g = rdflib.Graph()
        g.parse(str(out), format="turtle")
    finally:
        out.unlink(missing_ok=True)
    for nodes in (model_nodes, nodes_from_graph(g)):
        got = {k.split("/", 1)[1]: v for k, v in _resolve_all(nodes).items()}   # the RDF site key is its label
        assert got["VAV-1"] is None, got          # ambiguous: binds nothing even though both candidates have proof
        assert got["VAV-2"] is not None and got["VAV-2"][2] == "B", got      # control: an unambiguous ref to a proven unit does bind

