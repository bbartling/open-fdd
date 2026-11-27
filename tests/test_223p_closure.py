"""The 223P import closure is vendored. Resolving it does not open a URL."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from open_fdd.ontology_audit.closure import (
    PINNED_223P_SHA256,
    VENDORED_223P_CLOSURE,
    _read_pinned_rdf,
    materialize_223p_closure,
    vendored_223p_ttl,
    vendored_closure_dir,
)


def test_vendored_223p_matches_the_pin():
    payload = vendored_223p_ttl().read_bytes()
    assert hashlib.sha256(payload).hexdigest() == PINNED_223P_SHA256
    assert not payload.lstrip().lower().startswith(b"<!doctype")


def test_vendored_closure_matches_pins():
    directory = vendored_closure_dir()
    for item in VENDORED_223P_CLOSURE:
        payload = _read_pinned_rdf(directory / item["filename"], item["sha256"])
        assert item["iri"]
        assert payload


def test_html_document_is_rejected(tmp_path: Path):
    payload = b"<!DOCTYPE html><html><body>not rdf</body></html>\n"
    path = tmp_path / "vaem.ttl"
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="HTML"):
        _read_pinned_rdf(path, hashlib.sha256(payload).hexdigest())


def test_materialize_uses_the_vendor_and_does_not_fetch(tmp_path: Path, monkeypatch):
    pytest.importorskip("ontoenv")

    def refuse_network(*_args, **_kwargs):
        raise AssertionError("223P closure must not be fetched")

    monkeypatch.setattr("urllib.request.urlopen", refuse_network)
    names = materialize_223p_closure(tmp_path / "closure")
    assert set(names) == {item["iri"] for item in VENDORED_223P_CLOSURE}
    written = sorted(path.name for path in (tmp_path / "closure").iterdir())
    assert written == sorted(item["filename"] for item in VENDORED_223P_CLOSURE)
