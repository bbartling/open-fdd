"""The 223P import closure is a sha256 pin, not a file in git.

Unit tests fake the download. The OntoEnv resolve runs only when
``OPENFDD_FETCH_223P=1`` (the 223P alignment workflow). After the cache is
full, that resolve does not open a URL.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from open_fdd.ontology_audit.closure import (
    S223_ROOT,
    _read_pinned_rdf,
    cache_dir,
    closure_pins,
    ensure_223p_cache,
    fetch_pin,
    imported_pins,
    materialize_223p_closure,
)


def test_pins_name_five_files_and_a_root():
    pins = closure_pins()
    assert [item["filename"] for item in pins] == [
        "223p.ttl",
        "closure/shacl.ttl",
        "closure/qudt-3.4.0-shacl-all.ttl",
        "closure/skos.rdf",
        "closure/vaem.ttl",
    ]
    assert all(len(item["sha256"]) == 64 and item["urls"] for item in pins)
    assert pins[0]["iri"] == S223_ROOT
    iris = {item["iri"] for item in imported_pins()}
    assert "http://qudt.org/3.4.0/shacl/qudt-all" in iris
    assert S223_ROOT not in iris


def test_html_document_is_rejected(tmp_path: Path):
    payload = b"<!DOCTYPE html><html><body>not rdf</body></html>\n"
    path = tmp_path / "vaem.ttl"
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="HTML"):
        _read_pinned_rdf(path, hashlib.sha256(payload).hexdigest())


def test_fetch_uses_the_cache_and_rejects_a_bad_hash(tmp_path: Path):
    body = b"@prefix ex: <urn:ex:> .\nex:a ex:b ex:c .\n"
    digest = hashlib.sha256(body).hexdigest()
    pin = {"filename": "sample.ttl", "sha256": digest, "urls": ["https://example.invalid/sample.ttl"]}
    calls = []

    def reader(url, timeout):
        calls.append((url, timeout))
        return body

    dest = tmp_path / "sample.ttl"
    assert fetch_pin(pin, dest, urlopen_reader=reader) == "downloaded"
    assert dest.read_bytes() == body
    assert fetch_pin(pin, dest, urlopen_reader=reader) == "cached"
    assert calls == [("https://example.invalid/sample.ttl", 120.0)]

    pin["sha256"] = "0" * 64
    dest.write_bytes(body)
    with pytest.raises(ValueError, match="pin failed"):
        fetch_pin(pin, dest, urlopen_reader=reader)
    assert not dest.exists()


def test_fetch_skips_html_and_tries_the_next_url(tmp_path: Path):
    good = b"@prefix ex: <urn:ex:> .\n"
    pin = {
        "filename": "vaem.ttl",
        "sha256": hashlib.sha256(good).hexdigest(),
        "urls": ["https://example.invalid/html", "https://example.invalid/ttl"],
    }

    def reader(url, _timeout):
        if url.endswith("html"):
            return b"<!DOCTYPE html><html></html>"
        return good

    dest = tmp_path / "vaem.ttl"
    assert fetch_pin(pin, dest, urlopen_reader=reader) == "downloaded"
    assert dest.read_bytes() == good


def test_ensure_writes_every_pin(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENFDD_223P_CACHE", str(tmp_path))
    bodies = {}
    pins = []
    for item in closure_pins():
        raw = b"@prefix ex: <urn:ex:> . # " + item["filename"].encode()
        bodies[item["urls"][0]] = raw
        pins.append({**item, "sha256": hashlib.sha256(raw).hexdigest()})

    def reader(url, _timeout):
        return bodies[url]

    monkeypatch.setattr("open_fdd.ontology_audit.closure._download", reader)
    monkeypatch.setattr("open_fdd.ontology_audit.closure.closure_pins", lambda: pins)
    root = ensure_223p_cache()
    assert root == tmp_path
    for pin in pins:
        assert (tmp_path / pin["filename"]).read_bytes() == bodies[pin["urls"][0]]
    assert cache_dir() == tmp_path


@pytest.mark.skipif(os.environ.get("OPENFDD_FETCH_223P") != "1", reason="set OPENFDD_FETCH_223P=1")
def test_materialize_uses_the_cache_and_does_not_fetch(tmp_path: Path, monkeypatch):
    pytest.importorskip("ontoenv")
    ensure_223p_cache()

    def refuse_network(*_args, **_kwargs):
        raise AssertionError("223P closure must not be fetched once it is cached")

    monkeypatch.setattr("urllib.request.urlopen", refuse_network)
    names = materialize_223p_closure(tmp_path / "closure")
    assert set(names) == {item["iri"] for item in imported_pins()}
    written = sorted(path.name for path in (tmp_path / "closure").iterdir())
    assert written == sorted(Path(item["filename"]).name for item in imported_pins())
