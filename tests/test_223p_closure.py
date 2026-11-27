"""The 223P closure is vendored and hashed. Validation does not open a URL.

Unit tests stub OntoEnv and Shifty. The real closure runs when those libraries
are installed (the 223P alignment workflow). A skipped real-closure test fails
that workflow.
"""
from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path

import pytest
from rdflib import BNode, Graph
from rdflib.namespace import RDF, SH

from open_fdd.ontology_audit.closure import (
    PINNED_223P_SHA256,
    PINNED_223P_URL,
    S223_ROOT,
    closure_pins,
    imported_pins,
    materialize_223p_closure,
    vendored_223p_dir,
)
from open_fdd.ontology_audit.shacl import validate_223p

ROOT = Path(__file__).resolve().parents[1]
EDGE_STYLE = ROOT / "open_fdd" / "ontology_audit" / "data" / "edge-style-223p.ttl"


def test_pins_name_the_vendored_files_and_the_open223_hash():
    pins = closure_pins()
    assert [item["filename"] for item in pins] == [
        "223p.ttl",
        "closure/shacl.ttl",
        "closure/qudt-3.4.0-shacl-all.ttl",
        "closure/skos.rdf",
        "closure/vaem.ttl",
    ]
    root = pins[0]
    assert root["sha256"] == PINNED_223P_SHA256
    assert root["source"] == PINNED_223P_URL
    assert root["iri"] == S223_ROOT
    iris = {item["iri"] for item in imported_pins()}
    assert "http://qudt.org/3.4.0/shacl/qudt-all" in iris
    assert S223_ROOT not in iris
    for item in pins:
        path = vendored_223p_dir() / item["filename"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == item["sha256"]
        assert not path.read_bytes().lstrip()[:16].lower().startswith(b"<html")


def test_html_document_is_rejected(tmp_path: Path):
    from open_fdd.ontology_audit.closure import _read_pinned_rdf

    payload = b"<!DOCTYPE html><html><body>not rdf</body></html>\n"
    path = tmp_path / "vaem.ttl"
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="HTML"):
        _read_pinned_rdf(path, hashlib.sha256(payload).hexdigest())


def _pin(shapes: Path) -> None:
    shapes.write_text("pinned-223p\n", encoding="utf-8")


def _install_engines(monkeypatch, *, missing: list[str] | None = None, shifty_conforms: bool = True):
    calls: dict = {}

    class StubEnv:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def add(self, path, **kwargs):
            calls.setdefault("add", []).append(kwargs)

        def missing_imports(self, root):
            return list(missing or [])

        def copy_closure(self, root):
            graph = Graph()
            graph.add((BNode(), RDF.type, SH.NodeShape))
            return graph, [root]

    def fake_validate(data, shapes, **opts):
        calls["shifty"] = opts
        return shifty_conforms, Graph(), "shifty-report"

    def pyshacl_validate(**kwargs):
        calls["pyshacl"] = kwargs
        return False, Graph(), "pyshacl-report"

    monkeypatch.setattr(
        "open_fdd.ontology_audit.closure._read_pinned_rdf",
        lambda path, expected: b"pinned",
    )
    monkeypatch.setitem(sys.modules, "ontoenv", types.SimpleNamespace(OntoEnv=StubEnv))
    monkeypatch.setitem(sys.modules, "shifty", types.SimpleNamespace(validate=fake_validate))
    monkeypatch.setitem(sys.modules, "pyshacl", types.SimpleNamespace(validate=pyshacl_validate))
    return calls


def test_validate_223p_uses_the_offline_closure_and_shifty_defaults(tmp_path, monkeypatch):
    shapes = tmp_path / "223p.ttl"
    model = tmp_path / "model.ttl"
    model.write_text("@prefix ex: <http://example.org/> .\n", encoding="utf-8")
    _pin(shapes)
    calls = _install_engines(monkeypatch)
    monkeypatch.setattr(
        "open_fdd.ontology_audit.closure._ontology_files",
        lambda directory: [],
    )

    result = validate_223p(model, shapes_path=shapes, ontology_dir=tmp_path)

    assert result["conforms"] is True
    assert result["engine"] == "shifty"
    assert result["minimum_severity"] == "Violation"
    assert calls["init"] == {"temporary": True, "offline": True, "strict": True}
    assert calls["shifty"] == {"minimum_severity": "Violation"}
    assert calls["add"][0]["fetch_imports"] is False
    assert "pyshacl" not in calls


def test_unresolved_imports_are_an_error(tmp_path, monkeypatch):
    shapes = tmp_path / "223p.ttl"
    model = tmp_path / "model.ttl"
    model.write_text("@prefix ex: <http://example.org/> .\n", encoding="utf-8")
    _pin(shapes)
    _install_engines(monkeypatch, missing=["http://qudt.org/3.4.0/shacl/qudt-all"])
    monkeypatch.setattr("open_fdd.ontology_audit.closure._ontology_files", lambda directory: [])

    with pytest.raises(ValueError, match="Unresolved owl:imports"):
        validate_223p(model, shapes_path=shapes, ontology_dir=tmp_path)


def test_pyshacl_cross_check_does_not_set_conforms(tmp_path, monkeypatch):
    shapes = tmp_path / "223p.ttl"
    model = tmp_path / "model.ttl"
    model.write_text("@prefix ex: <http://example.org/> .\n", encoding="utf-8")
    _pin(shapes)
    calls = _install_engines(monkeypatch, shifty_conforms=True)
    monkeypatch.setattr("open_fdd.ontology_audit.closure._ontology_files", lambda directory: [])

    result = validate_223p(model, shapes_path=shapes, ontology_dir=tmp_path, cross_check="pyshacl")

    assert result["conforms"] is True
    assert result["cross_check"]["engine"] == "pyshacl"
    assert result["cross_check"]["conforms"] is False
    assert calls["pyshacl"]["advanced"] is True
    assert calls["pyshacl"]["inference"] == "none"


def test_materialize_reads_the_vendored_files_and_does_not_fetch(tmp_path: Path, monkeypatch):
    pytest.importorskip("ontoenv")

    def refuse_network(*_args, **_kwargs):
        raise AssertionError("223P closure must not be fetched")

    monkeypatch.setattr("urllib.request.urlopen", refuse_network)
    names = materialize_223p_closure(tmp_path / "closure")
    assert set(names) == {item["iri"] for item in imported_pins()}
    written = sorted(path.name for path in (tmp_path / "closure").iterdir())
    assert written == sorted(Path(item["filename"]).name for item in imported_pins())


def test_edge_style_bacnet_and_qudt_model_conforms():
    pytest.importorskip("ontoenv")
    pytest.importorskip("shifty")
    text = EDGE_STYLE.read_text(encoding="utf-8")
    assert "bacnet://" in text
    assert "unit:DEG_C" in text
    result = validate_223p(EDGE_STYLE)
    assert result["conforms"] is True, result["violations"]
    assert result["engine"] == "shifty"
    assert result["minimum_severity"] == "Violation"
    assert result["violation_count"] == 0
