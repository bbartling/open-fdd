"""ASHRAE 223P import closure. The ontology files are vendored, not downloaded.

``data/223p/223p.ttl`` is the file published at ``https://open223.info/223p.ttl``
(sha256 ``08f80bd6…``). ``data/223p/closure/`` holds the same QUDT 3.4.0, SHACL,
SKOS and VAEM bytes the edge validator loads. ``data/223p-closure.json`` records
those hashes. A mismatch or an HTML body is an error.

OntoEnv resolves ``owl:imports`` from those files with ``offline=True``. Nothing
in this module opens a URL.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from importlib.resources import files
from pathlib import Path

S223_ROOT = "http://data.ashrae.org/standard223/1.0/model/all"
PINNED_223P_SHA256 = "08f80bd6e15052f28cdfd354bdf46ff96e5e1afdba36a4dbed5186fc1ea51c41"
PINNED_223P_URL = "https://open223.info/223p.ttl"
_ONTOLOGY_SUFFIXES = {".ttl", ".rdf", ".owl", ".nt", ".n3", ".jsonld"}


def closure_pins() -> list[dict]:
    text = files("open_fdd.ontology_audit").joinpath("data/223p-closure.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    pins = payload["files"]
    if payload.get("root_iri") != S223_ROOT:
        raise ValueError("223p-closure.json root_iri does not match S223_ROOT")
    root = next(item for item in pins if item["filename"] == "223p.ttl")
    if root["sha256"] != PINNED_223P_SHA256 or root.get("source") != PINNED_223P_URL:
        raise ValueError("223p-closure.json does not pin https://open223.info/223p.ttl")
    return pins


def imported_pins() -> list[dict]:
    return [item for item in closure_pins() if item["iri"] != S223_ROOT]


def vendored_223p_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "223p"


def vendored_223p_ttl() -> Path:
    return vendored_223p_dir() / "223p.ttl"


def vendored_closure_dir() -> Path:
    return vendored_223p_dir() / "closure"


def unknown_model_imports(graph) -> list[str]:
    """``owl:imports`` on the model that are not the pinned 223P root.

    The closure passed to Shifty is that root. An import of anything else is
    not resolved, including when the network is off.
    """
    from rdflib.namespace import OWL, RDF

    found = set()
    for subject in graph.subjects(RDF.type, OWL.Ontology):
        for obj in graph.objects(subject, OWL.imports):
            iri = str(obj)
            if iri != S223_ROOT:
                found.add(iri)
    return sorted(found)


def _accepts_kwarg(fn, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _add_local_ontology(env, location: str) -> None:
    """Register a local ontology without fetching remote ``owl:imports``.

    OntoEnv 0.6.4 ``search_directories=`` plus ``offline=True`` and ``strict=True``
    tries to HTTP-fetch import IRIs during construction. Each file is added with
    imports-fetch disabled, then the already-loaded graphs resolve the closure.
    """
    add = getattr(env, "add", None)
    if callable(add) and _accepts_kwarg(add, "fetch_imports"):
        add(location, fetch_imports=False)
        return
    no_imports = getattr(env, "add_no_imports", None)
    if callable(no_imports):
        no_imports(location)
        return
    if add is None:
        raise RuntimeError("OntoEnv has no add() method")
    add(location)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_pinned_rdf(path: Path, expected_sha256: str) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = path.read_bytes()
    digest = _sha256(payload)
    if digest != expected_sha256:
        raise ValueError(f"{path} sha256 {digest} != {expected_sha256}")
    head = payload.lstrip()[:16].lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        raise ValueError(f"{path} is HTML, not RDF")
    return payload


def _ontology_files(directory: Path) -> list[Path]:
    return [path for path in sorted(directory.rglob("*"))
            if path.is_file() and path.suffix.lower() in _ONTOLOGY_SUFFIXES]


def _require_ontoenv():
    try:
        from ontoenv import OntoEnv
    except ImportError as exc:
        raise ValueError('OntoEnv needed: pip install "open-fdd[ontology-align]"') from exc
    return OntoEnv


def _check_vendored() -> None:
    for item in closure_pins():
        _read_pinned_rdf(vendored_223p_dir() / item["filename"], item["sha256"])


def materialize_223p_closure(dest: Path, shapes_path: Path | None = None) -> list[str]:
    """Copy the vendored imports into ``dest`` and resolve them with OntoEnv offline.

    Returns the imported ontology IRIs. ``missing_imports`` must be empty.
    This does not open a URL.
    """
    _check_vendored()
    shapes_path = Path(shapes_path) if shapes_path else vendored_223p_ttl()
    root_pin = next(item for item in closure_pins() if item["filename"] == "223p.ttl")
    _read_pinned_rdf(shapes_path, root_pin["sha256"])
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for item in imported_pins():
        source = vendored_223p_dir() / item["filename"]
        body = _read_pinned_rdf(source, item["sha256"])
        target = dest / Path(item["filename"]).name
        if source.resolve() != target.resolve():
            target.write_bytes(body)
    OntoEnv = _require_ontoenv()
    with OntoEnv(temporary=True, offline=True, strict=True) as env:
        _add_local_ontology(env, str(shapes_path))
        for path in _ontology_files(dest):
            _add_local_ontology(env, str(path))
        missing = [str(item) for item in env.missing_imports(S223_ROOT)]
        if missing:
            raise ValueError("Unresolved owl:imports: " + ", ".join(missing))
        names = [str(name) for name in env.list_closure(S223_ROOT) if str(name) != S223_ROOT]
    expected = {item["iri"] for item in imported_pins()}
    if set(names) != expected:
        raise ValueError(f"Expected imported ontologies {sorted(expected)}, got {names}")
    return names


def copy_223p_closure(shapes_path: Path | None = None, ontology_dir: Path | None = None):
    """``(closure graph, ontology IRIs)`` for the pinned 223P file. Offline and strict."""
    _check_vendored()
    shapes_path = Path(shapes_path) if shapes_path else vendored_223p_ttl()
    root_pin = next(item for item in closure_pins() if item["filename"] == "223p.ttl")
    _read_pinned_rdf(shapes_path, root_pin["sha256"])
    files_to_add = [shapes_path]
    if ontology_dir is not None:
        files_to_add.extend(_ontology_files(Path(ontology_dir)))
    else:
        for item in imported_pins():
            source = vendored_223p_dir() / item["filename"]
            _read_pinned_rdf(source, item["sha256"])
            files_to_add.append(source)
    OntoEnv = _require_ontoenv()
    with OntoEnv(temporary=True, offline=True, strict=True) as env:
        for path in files_to_add:
            _add_local_ontology(env, str(path))
        missing = [str(item) for item in env.missing_imports(S223_ROOT)]
        if missing:
            raise ValueError("Unresolved owl:imports: " + ", ".join(missing))
        closure, names = env.copy_closure(S223_ROOT)
    if not len(closure):
        raise ValueError(f"Empty dependency closure for {S223_ROOT}")
    return closure, [str(name) for name in names]
