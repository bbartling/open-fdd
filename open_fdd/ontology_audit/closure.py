"""Vendored ASHRAE 223P import closure. OntoEnv resolves it offline.

The files under ``data/223p/`` are the same bytes open-hvac-edge vendors: 223P
(sha256 ``08f80bd6…``) plus QUDT 3.4.0 ``qudt-all``, SHACL, SKOS and VAEM.
``https://www.linkedmodel.org/schema/vaem.ttl`` is HTML on some networks, so a
live fetch is not a closure. Tests and CI copy these files and never open a URL.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

PINNED_223P_SHA256 = "08f80bd6e15052f28cdfd354bdf46ff96e5e1afdba36a4dbed5186fc1ea51c41"
S223_ROOT = "http://data.ashrae.org/standard223/1.0/model/all"
_ONTOLOGY_SUFFIXES = {".ttl", ".rdf", ".owl", ".nt", ".n3", ".jsonld"}

# Resolved once with OntoEnv 0.6.4. Do not fetch these at runtime.
VENDORED_223P_CLOSURE = (
    {
        "filename": "shacl.ttl",
        "sha256": "0e5d8aea0eab98a072d4a02faaee1ee914ec99eab2ca473429726faed4a13f69",
        "iri": "http://www.w3.org/ns/shacl#",
    },
    {
        "filename": "qudt-3.4.0-shacl-all.ttl",
        "sha256": "fc7ab1041a382e18fccdda7a99bd2c2a5a3d27e2aaa407561d68c3cf089b562c",
        "iri": "http://qudt.org/3.4.0/shacl/qudt-all",
    },
    {
        "filename": "skos.rdf",
        "sha256": "e79633b8d0564816cee8a99f5c9acf9a0e6fc7257c7209acd684ecad53a89dd6",
        "iri": "http://www.w3.org/2004/02/skos/core",
    },
    {
        "filename": "vaem.ttl",
        "sha256": "c20ef803616277ff6683edb5fb70aa8931e9e867e864d2f06bb4acfe3238774f",
        "iri": "http://www.linkedmodel.org/schema/vaem",
    },
)


def vendored_223p_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "223p"


def vendored_223p_ttl() -> Path:
    return vendored_223p_dir() / "223p.ttl"


def vendored_closure_dir() -> Path:
    return vendored_223p_dir() / "closure"


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


def _read_pinned_rdf(path: Path, expected_sha256: str) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256:
        raise ValueError(f"{path} sha256 {digest} != {expected_sha256}")
    head = payload.lstrip()[:16].lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        raise ValueError(f"{path} is HTML, not RDF")
    return payload


def _ontology_files(directory: Path) -> list[Path]:
    return [path for path in sorted(directory.rglob("*"))
            if path.is_file() and path.suffix.lower() in _ONTOLOGY_SUFFIXES]


def materialize_223p_closure(dest: Path, shapes_path: Path | None = None) -> list[str]:
    """Copy the vendored imports into ``dest`` and resolve them with OntoEnv offline.

    Returns the imported ontology IRIs. ``missing_imports`` must be empty.
    """
    shapes_path = Path(shapes_path) if shapes_path else vendored_223p_ttl()
    _read_pinned_rdf(shapes_path, PINNED_223P_SHA256)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for item in VENDORED_223P_CLOSURE:
        source = vendored_closure_dir() / item["filename"]
        body = _read_pinned_rdf(source, item["sha256"])
        target = dest / item["filename"]
        if source.resolve() != target.resolve():
            target.write_bytes(body)
    try:
        from ontoenv import OntoEnv
    except ImportError as exc:
        raise RuntimeError('OntoEnv needed: pip install "open-fdd[ontology-align]"') from exc
    with OntoEnv(temporary=True, offline=True, strict=True) as env:
        _add_local_ontology(env, str(shapes_path))
        for path in _ontology_files(dest):
            _add_local_ontology(env, str(path))
        missing = [str(item) for item in env.missing_imports(S223_ROOT)]
        if missing:
            raise ValueError("Unresolved owl:imports: " + ", ".join(missing))
        names = [str(name) for name in env.list_closure(S223_ROOT) if str(name) != S223_ROOT]
    expected = {item["iri"] for item in VENDORED_223P_CLOSURE}
    if set(names) != expected:
        raise ValueError(f"Expected imported ontologies {sorted(expected)}, got {names}")
    return names


def copy_223p_closure(shapes_path: Path | None = None, ontology_dir: Path | None = None):
    """``(closure graph, ontology IRIs)`` for the pinned 223P file. Offline and strict."""
    shapes_path = Path(shapes_path) if shapes_path else vendored_223p_ttl()
    _read_pinned_rdf(shapes_path, PINNED_223P_SHA256)
    files = [shapes_path]
    if ontology_dir is not None:
        files.extend(_ontology_files(Path(ontology_dir)))
    else:
        files.extend(_ontology_files(vendored_closure_dir()))
    try:
        from ontoenv import OntoEnv
    except ImportError as exc:
        raise RuntimeError('OntoEnv needed: pip install "open-fdd[ontology-align]"') from exc
    with OntoEnv(temporary=True, offline=True, strict=True) as env:
        for path in files:
            _add_local_ontology(env, str(path))
        missing = [str(item) for item in env.missing_imports(S223_ROOT)]
        if missing:
            raise ValueError("Unresolved owl:imports: " + ", ".join(missing))
        closure, names = env.copy_closure(S223_ROOT)
    if not len(closure):
        raise ValueError(f"Empty dependency closure for {S223_ROOT}")
    return closure, [str(name) for name in names]
