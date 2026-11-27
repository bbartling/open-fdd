"""open_fdd.ontology_audit: requirements audit, pinned sources, model doctor, SHACL and the CLI.

Offline: tiny synthetic vocabularies written here (real Brick / Haystack / 223 namespace IRIs, no copied content),
the shipped synthetic two-sensor AHU graph, and a fake HTTP server for ``refresh``. The JS-exporter drift test runs
only when Node is available.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
pytest.importorskip("openpyxl")

from open_fdd.ontology_audit import audit_requirements, doctor, load_sources, read_requirements, run_query  # noqa: E402
from open_fdd.ontology_audit import sources as sources_mod  # noqa: E402
from open_fdd.ontology_audit.audit import summary  # noqa: E402
from open_fdd.ontology_audit.cli import main  # noqa: E402
from open_fdd.ontology_audit.report import write_audit  # noqa: E402
from open_fdd.ontology_audit.terms import canonical_iri  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "open_fdd" / "ontology_audit" / "data"
EXAMPLE_TTL = DATA / "example_building.ttl"
EXAMPLE_REQ = DATA / "example_requirements.csv"
MODEL_JSON = ROOT / "tests" / "fixtures" / "ontology_audit" / "two_sat_ahu_model.json"
U = "urn:test:22222222-0000-4000-8000-0000000000"

MINI_BRICK = """@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
brick:Air_Handling_Unit a owl:Class ; rdfs:label "Air Handling Unit" ; skos:definition "Test definition." .
brick:Supply_Air_Temperature_Sensor a owl:Class ; rdfs:label "Supply Air Temperature Sensor" .
brick:Mixed_Air_Temperature_Sensor a owl:Class ; rdfs:label "Mixed Air Temperature Sensor" .
brick:feeds a owl:ObjectProperty ; rdfs:label "Feeds" .
ref:hasExternalReference a owl:ObjectProperty ; rdfs:label "hasExternalReference" .
"""
# Haystack defs and the NF export use versioned 4.0.0 IRIs. canonical_iri also accepts the old form.
MINI_HAYSTACK = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
phIoT:ahu a owl:Class ; rdfs:label "ahu" .
"""


def _mini(tmp_path: Path) -> list[Path]:
    paths = []
    for name, text in (("mini_brick.ttl", MINI_BRICK), ("mini_haystack.ttl", MINI_HAYSTACK)):
        p = tmp_path / name
        p.write_bytes(text.encode("utf-8"))  # bytes: the hash must not depend on the platform's newline
        paths.append(p)
    return paths


def _example_graph():
    return rdflib.Graph().parse(str(EXAMPLE_TTL), format="turtle")


# ---- requirements --------------------------------------------------------------------------------------------

def test_csv_and_xlsx_requirements_read_the_same(tmp_path):
    from openpyxl import Workbook

    rows = read_requirements(EXAMPLE_REQ)
    assert len(rows) == 11 and rows[0].candidate_uri == "brick:Air_Handling_Unit"
    wb = Workbook()
    ws = wb.active
    import csv

    with open(EXAMPLE_REQ, newline="", encoding="utf-8") as f:
        for r in csv.reader(f):
            ws.append(r)
    wb.save(tmp_path / "req.xlsx")
    assert [r.__dict__ for r in read_requirements(tmp_path / "req.xlsx")] == [r.__dict__ for r in rows]


def test_requirements_need_a_requirement_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("category,uri\nx,y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="requirement"):
        read_requirements(p)


# ---- audit statuses ------------------------------------------------------------------------------------------

def test_without_sources_everything_is_source_unavailable(tmp_path):
    srcs = load_sources(tmp_path / "empty")
    rows = audit_requirements(read_requirements(EXAMPLE_REQ), srcs)
    counts = summary(rows)
    assert counts["SOURCE_UNAVAILABLE"] == 10 and counts["EXTENSION_REVIEW"] == 1  # only the urn:openfdd term
    assert counts["VERIFIED_TERM"] == 0


def test_statuses_with_local_vocabularies(tmp_path):
    srcs = load_sources(tmp_path / "empty", extra_files=_mini(tmp_path))
    rows = {r.requirement: r for r in audit_requirements(read_requirements(EXAMPLE_REQ), srcs, _example_graph())}
    aircon = rows["Air handling unit"]
    assert aircon.status == "VERIFIED_TERM" and aircon.term_kind == "class" and aircon.evidence == "Test definition."
    assert aircon.sha256 == hashlib.sha256(MINI_BRICK.encode()).hexdigest()
    hay = rows["Air handling unit (Haystack)"]
    assert hay.status == "VERIFIED_TERM" and hay.graph_uses == 1  # export IRI and defs IRI share the 4.0.0 form
    assert rows["Supply air temperature sensr"].status == "MAPPING_REVIEW"
    mixed = rows["Mixed air temperature sensor"]
    assert mixed.status == "CANDIDATE_REVIEW"
    assert mixed.candidates[0]["iri"].endswith("#Mixed_Air_Temperature_Sensor")
    assert rows["Duct connection between two pieces of equipment"].status == "SOURCE_UNAVAILABLE"  # 223P not loaded
    assert rows["Assessed zero versus missing coverage"].status == "EXTENSION_REVIEW"
    assert rows["Rule reference on a result point"].status == "EXTENSION_REVIEW"
    assert rows["Link from a point to its stored history"].graph_uses == 6


def test_graph_uses_count_versioned_haystack_iris(tmp_path):
    from rdflib import URIRef

    g = _example_graph()
    old = URIRef("https://project-haystack.org/def/phIoT/ahu")
    new = URIRef("https://project-haystack.org/def/phIoT/4.0.0#ahu")
    for s_, p_, _ in list(g.triples((None, None, old))):
        g.remove((s_, p_, old))
        g.add((s_, p_, new))
    srcs = load_sources(tmp_path / "empty", extra_files=_mini(tmp_path))
    rows = {r.requirement: r for r in audit_requirements(read_requirements(EXAMPLE_REQ), srcs, g)}
    assert rows["Air handling unit (Haystack)"].graph_uses == 1


def test_offline_parsing_rejects_external_resources(tmp_path):
    from open_fdd.ontology_audit.sources import parse_rdf

    remote = tmp_path / "remote.jsonld"
    remote.write_text(json.dumps({"@context": "https://example.invalid/ctx.jsonld", "@id": "urn:x:a",
                                  "name": "a"}), encoding="utf-8")
    nested = tmp_path / "nested.jsonld"
    nested.write_text(json.dumps({"@graph": [{"@context": ["file:///etc/passwd"], "@id": "urn:x:b"}]}),
                      encoding="utf-8")
    xml = tmp_path / "ent.rdf"
    xml.write_text('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
                   '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>', encoding="utf-8")
    imported = tmp_path / "import.jsonld"
    imported.write_text(json.dumps({"@context": {"@import": "https://example.invalid/context"}, "@id": "urn:x:d"}),
                        encoding="utf-8")
    for path in (remote, nested, xml, imported):
        with pytest.raises(ValueError):
            parse_rdf(path)
    inline = tmp_path / "inline.jsonld"
    inline.write_text(json.dumps({"@context": {"name": "http://schema.org/name"}, "@id": "urn:x:c", "name": "c"}),
                      encoding="utf-8")
    assert len(parse_rdf(inline)) == 1
    (src,) = [s for s in load_sources(tmp_path / "none", extra_files=[remote]) if s.name == "local:remote"]
    assert src.status == "SOURCE_UNAVAILABLE" and "external" in src.detail
    assert main(["--graph", str(remote), "--out", str(tmp_path / "o")]) == 2


def test_relative_iris_resolve_against_the_file(tmp_path):
    from rdflib import URIRef

    from open_fdd.ontology_audit.sources import parse_rdf

    vocab = tmp_path / "vocab.ttl"
    vocab.write_text("<#AHU> a <http://www.w3.org/2002/07/owl#Class> .\n", encoding="utf-8")
    (subject,) = set(parse_rdf(vocab).subjects())
    assert subject == URIRef(vocab.resolve().as_uri() + "#AHU")


def test_canonical_haystack_iris():
    versioned = "https://project-haystack.org/def/phIoT/4.0.0#ahu"
    assert canonical_iri("https://project-haystack.org/def/phIoT/4.0.0#ahu") == \
        canonical_iri("https://project-haystack.org/def/phIoT/ahu") == versioned
    assert canonical_iri("https://project-haystack.org/def/phIoT/3.9.13#ahu") == versioned
    assert canonical_iri("https://brickschema.org/schema/Brick#AHU") == "https://brickschema.org/schema/Brick#AHU"


def test_reports_are_stable_between_runs(tmp_path):
    from openpyxl import load_workbook

    srcs = load_sources(tmp_path / "empty", extra_files=_mini(tmp_path))
    reqs = read_requirements(EXAMPLE_REQ)
    a = write_audit(audit_requirements(reqs, srcs), srcs, tmp_path / "a")
    b = write_audit(audit_requirements(reqs, srcs), srcs, tmp_path / "b")
    for kind in ("json", "csv"):
        assert a[kind].read_bytes() == b[kind].read_bytes()
    wb = load_workbook(a["xlsx"])
    assert wb.sheetnames == ["Audit", "Sources", "Statuses"] and wb["Audit"].max_row == 12


# ---- pinned sources -------------------------------------------------------------------------------------------

def _pin(monkeypatch, text: str) -> dict:
    spec = {"name": "brick", "vocabulary": "Brick", "version": "test", "url": "https://example.invalid/Brick.ttl",
            "sha256": hashlib.sha256(text.encode()).hexdigest(), "license": "BSD-3-Clause", "file": "Brick-test.ttl",
            "namespaces": ["https://brickschema.org/schema/Brick#"]}
    monkeypatch.setattr(sources_mod, "SOURCES", [spec])
    return spec


def test_pinned_source_loads_only_with_the_pinned_hash(tmp_path, monkeypatch):
    spec = _pin(monkeypatch, MINI_BRICK)
    (tmp_path / spec["file"]).write_bytes(MINI_BRICK.encode("utf-8"))
    (src,) = load_sources(tmp_path)
    assert src.status == "LOADED" and src.loaded
    (tmp_path / spec["file"]).write_bytes((MINI_BRICK + "\n# changed\n").encode("utf-8"))
    (src,) = load_sources(tmp_path)
    assert src.status == "SOURCE_UNAVAILABLE" and "differs" in src.detail and not src.loaded


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_refresh_checks_the_hash(tmp_path, monkeypatch):
    spec = _pin(monkeypatch, MINI_BRICK)
    monkeypatch.setattr(sources_mod.urllib.request, "urlopen", lambda req, timeout=None: _Resp(MINI_BRICK.encode()))
    (got,) = sources_mod.refresh(tmp_path, log=None)
    assert got.status == "DOWNLOADED" and (tmp_path / spec["file"]).is_file()
    (got,) = sources_mod.refresh(tmp_path, log=None)
    assert got.status == "CACHED"
    (tmp_path / spec["file"]).unlink()
    monkeypatch.setattr(sources_mod.urllib.request, "urlopen", lambda req, timeout=None: _Resp(b"tampered"))
    (got,) = sources_mod.refresh(tmp_path, log=None)
    assert got.status == "SOURCE_UNAVAILABLE" and "differs" in got.detail
    assert not (tmp_path / spec["file"]).exists() and not list(tmp_path.glob("*.part"))


def test_unreadable_pinned_source_does_not_stop_the_audit(tmp_path, monkeypatch):
    spec = _pin(monkeypatch, MINI_BRICK)
    (tmp_path / spec["file"]).write_bytes(MINI_BRICK.encode("utf-8"))

    def denied(path):
        raise PermissionError("denied")

    monkeypatch.setattr(sources_mod, "sha256_file", denied)
    (src,) = load_sources(tmp_path)
    assert src.status == "SOURCE_UNAVAILABLE" and "unreadable" in src.detail


def test_manifest_pins_every_source():
    for spec in sources_mod.SOURCES:
        assert len(spec["sha256"]) == 64 and spec["url"].startswith("https://") and spec["license"]


# ---- doctor ---------------------------------------------------------------------------------------------------

def test_doctor_keeps_two_sensors_on_one_role_apart():
    rep = doctor(_example_graph())
    assert rep.points == 6 and rep.problems == []
    (binding,) = rep.role_bindings
    assert binding["role"] == "discharge-air-temp" and binding["points"] == [U + "10", U + "11"]
    sats = rep.queries["ahu_discharge_air_temp_sensors"]
    assert [r["historyId"] for r in sats] == ["22222222-0000-4000-8000-000000000010",
                                             "22222222-0000-4000-8000-000000000011"]
    (fault,) = rep.queries["fault_results"]
    assert fault["rule"] == "SV-RATE" and fault["equip"] == U + "02"
    tags = {r["tag"].rsplit(":", 1)[-1] for r in rep.queries["non_haystack_tags"]}
    assert tags == {"fault", "fdd"}
    by_class = {t["name"]: t["classification"] for t in rep.terms}
    assert by_class["ruleRef"] == by_class["ofddRole"] == "open-fdd"
    assert by_class["fault"] == "site-specific" and by_class["ahu"] == "standard"
    assert {t["defined"] for t in rep.terms if t["classification"] == "standard"} <= {"builtin", "unchecked"}


def test_doctor_flags_undefined_standard_terms_against_a_loaded_vocabulary(tmp_path):
    srcs = load_sources(tmp_path / "empty", extra_files=_mini(tmp_path)[1:])  # haystack mini: only `ahu`
    rep = doctor(_example_graph(), srcs)
    states = {t["name"]: t["defined"] for t in rep.terms if "project-haystack" in t["iri"] and t["used_as"] == "tag"}
    assert states["ahu"] == "defined" and states["sensor"] == "undefined"
    assert any("undefined standard tag" in p and p.endswith("4.0.0#sensor") for p in rep.problems)


def test_doctor_catches_broken_identity_and_history_links():
    from rdflib import URIRef

    g = _example_graph()
    ext = URIRef("https://brickschema.org/schema/Brick/ref#hasExternalReference")
    tsid = URIRef("https://brickschema.org/schema/Brick/ref#hasTimeseriesId")
    sat2 = URIRef(U + "11")
    for ref in list(g.objects(sat2, ext)):
        g.set((ref, tsid, rdflib.Literal("22222222-0000-4000-8000-000000000010")))  # SAT-2 points at SAT-1 history
    mat = URIRef(U + "12")
    g.remove((mat, ext, None))
    g.add((mat, URIRef("https://project-haystack.org/def/phIoT/4.0.0#equipRef"), URIRef("urn:test:missing")))
    problems = doctor(g).problems
    assert any("shared by 2 points" in p for p in problems)
    assert any(p.startswith("point without a history reference") and p.endswith("12") for p in problems)
    assert any(p.startswith("dangling reference") and "missing" in p for p in problems)


def test_run_query_accepts_plain_sparql():
    rows = run_query(_example_graph(), "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
    assert rows == [{"n": "149"}]


# ---- SHACL ----------------------------------------------------------------------------------------------------

def test_shacl_shapes_pass_the_example_and_catch_a_missing_site_ref():
    pytest.importorskip("pyshacl")
    from rdflib import URIRef

    from open_fdd.ontology_audit.shacl import validate_shacl

    assert validate_shacl(_example_graph(), engine="pyshacl")["conforms"] is True
    g = _example_graph()
    g.remove((URIRef(U + "12"), URIRef(canonical_iri("https://project-haystack.org/def/phIoT/siteRef")), None))
    res = validate_shacl(g, engine="pyshacl")
    assert res["conforms"] is False and any("siteRef" in v["message"] for v in res["violations"])


def test_shacl_validation_failure_is_a_clean_error(monkeypatch):
    pyshacl = pytest.importorskip("pyshacl")

    from open_fdd.ontology_audit.shacl import validate_shacl

    monkeypatch.setattr(pyshacl, "validate", lambda *a, **k: (False, Exception("VALUES not supported"), ""))
    with pytest.raises(ValueError, match="failed to run"):
        validate_shacl(_example_graph(), engine="pyshacl")


def test_shacl_without_pyshacl_reports_unavailable(monkeypatch):
    from open_fdd.ontology_audit import shacl

    monkeypatch.setattr(shacl, "pyshacl_available", lambda: False)
    assert shacl.validate_shacl(_example_graph(), engine="pyshacl")["available"] is False


def test_shacl_without_shifty_does_not_fall_back(monkeypatch):
    from open_fdd.ontology_audit import shacl

    monkeypatch.setattr(shacl, "shifty_available", lambda: False)
    report = shacl.validate_shacl(_example_graph(), engine="shifty")
    assert report["available"] is False and report["engine"] == "shifty"


# ---- the real JS exporter -------------------------------------------------------------------------------------

def test_example_graph_matches_the_js_exporter_and_the_neutral_fixture(tmp_path):
    from rdflib import URIRef
    from rdflib.compare import isomorphic

    model = json.loads(MODEL_JSON.read_text(encoding="utf-8"))
    g = _example_graph()
    # expected relationships derived from the neutral model, independent of the exporter
    equips = {r["attrs"]["id"]: r["uuid"] for r in model["records"] if r["pointType"] == "EQUIPMENT"}
    tsid = URIRef("https://brickschema.org/schema/Brick/ref#hasTimeseriesId")
    for rec in (r for r in model["records"] if r["pointType"] == "POINT"):
        subject = URIRef("urn:test:" + rec["uuid"])
        assert rec["uuid"] in {str(o) for _, _, o in g.triples((None, tsid, None))}
        if "equipRef" in rec["attrs"]:
            eq = URIRef("urn:test:" + equips[rec["attrs"]["equipRef"]])
            assert (subject, URIRef(canonical_iri("https://project-haystack.org/def/phIoT/equipRef")), eq) in g
    node = shutil.which("node")
    gen = ROOT / "tools" / "rdf-check" / "gen_ttl.js"
    if node is None or not gen.is_file():
        pytest.skip("node or tools/rdf-check not available: drift check skipped")
    out = tmp_path / "regen.ttl"
    subprocess.run([node, str(gen), str(MODEL_JSON), str(out)], check=True, capture_output=True, timeout=120)
    assert isomorphic(rdflib.Graph().parse(str(out), format="turtle"), g), \
        "open_fdd/ontology_audit/data/example_building.ttl is stale: regenerate it with tools/rdf-check/gen_ttl.js"


# ---- CLI ------------------------------------------------------------------------------------------------------

def test_cli_example_offline(tmp_path, capsys):
    out = tmp_path / "r"
    assert main(["--example", "--out", str(out), "--ontology-dir", str(tmp_path / "none")]) == 0
    for name in ("audit.json", "audit.csv", "audit.xlsx", "doctor.json", "doctor.md", "terms.csv"):
        assert (out / name).is_file()
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert printed[0]["audit"]["SOURCE_UNAVAILABLE"] == 10 and printed[1]["problems"] == 0


def test_cli_errors_and_sources(tmp_path, capsys):
    assert main(["--out", str(tmp_path)]) == 2
    assert main([str(tmp_path / "missing.csv"), "--out", str(tmp_path)]) == 2
    assert main(["--sources"]) == 0
    assert {s["name"] for s in json.loads(capsys.readouterr().out)} == {"brick", "s223p", "haystack"}


NF_VARS = ("NF_URL", "NFURL", "NF_LAN_URL", "NF_ENV_FILE", "NF_CLIENT_ID", "NF_CLIENT_SECRET", "NF_CONSOLE_USER",
           "NF_CONSOLE_PASSWORD", "NF_CA_FILE")


def test_from_nf_without_configuration_exits_2(tmp_path, monkeypatch, capsys):
    for var in NF_VARS:
        monkeypatch.delenv(var, raising=False)
    assert main(["--from-nf", "--out", str(tmp_path)]) == 2
    assert "NF" in capsys.readouterr().err


def test_from_nf_url_keeps_credentials_from_the_environment(monkeypatch):
    from open_fdd.nf import client as nf_client
    from open_fdd.nf import sparql_data
    from open_fdd.ontology_audit import nf_adapter

    seen = {}

    def fake_from_env(cls, via=None, env_file=None, env=None, **kw):
        seen.update(via=via, env=dict(env or {}))
        return object()

    monkeypatch.setenv("NF_CLIENT_ID", "id-from-env")
    monkeypatch.setattr(nf_client.NFClient, "from_env", classmethod(fake_from_env))
    monkeypatch.setattr(sparql_data, "hook_transport", lambda client, app: ("t", app))
    monkeypatch.setattr(sparql_data, "rdf_turtle", lambda transport: ("@prefix x: <urn:x:> .", transport[1]))
    turtle, app = nf_adapter.fetch_turtle(url="https://nf.example.test", via="portal", app="lite")
    assert seen["env"]["NF_URL"] == "https://nf.example.test" and seen["env"]["NF_CLIENT_ID"] == "id-from-env"
    assert seen["via"] is None and app == sparql_data.APP_LITE


def test_check_ttl_exempts_only_literal_rule_refs(tmp_path):
    pytest.importorskip("pyoxigraph")
    script = ROOT / "tools" / "rdf-check" / "check_ttl.py"
    ok = subprocess.run([sys.executable, str(script), str(EXAMPLE_TTL)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = tmp_path / "literal_siteref.ttl"
    bad.write_text(EXAMPLE_TTL.read_text(encoding="utf-8").replace(
        "phIoT:siteRef local:22222222-0000-4000-8000-000000000001", 'phIoT:siteRef "site-1"', 1), encoding="utf-8")
    res = subprocess.run([sys.executable, str(script), str(bad)], capture_output=True, text=True)
    assert res.returncode == 1 and "dangling ref" in res.stdout


def test_audit_does_not_import_the_nf_client():
    code = ("import sys, open_fdd.ontology_audit, open_fdd.ontology_audit.cli; "
            "print(any(m.startswith('open_fdd.nf') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT)
    assert out.stdout.strip() == "False"
