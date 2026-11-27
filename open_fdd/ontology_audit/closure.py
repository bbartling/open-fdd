"""ASHRAE 223P import closure. The ontology files are not in git.

``data/223p-closure.json`` pins 223P plus QUDT 3.4.0 ``qudt-all``, SHACL, SKOS
and VAEM by sha256 and by the URL that publishes those bytes. ``ensure_223p_cache``
downloads a missing file into ``$OPENFDD_223P_CACHE`` (default
``~/.cache/open-fdd/223p``) and refuses a hash mismatch or an HTML document.
A file already in that cache is not downloaded again.

OntoEnv resolves ``owl:imports`` from those cached files with ``offline=True``.
The publisher URL for VAEM sometimes returns HTML, so that pin lists a second
URL of the same bytes.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import tempfile
import urllib.request
from importlib.resources import files
from pathlib import Path

S223_ROOT = "http://data.ashrae.org/standard223/1.0/model/all"
_ONTOLOGY_SUFFIXES = {".ttl", ".rdf", ".owl", ".nt", ".n3", ".jsonld"}
_USER_AGENT = "open-fdd-ontology-audit"


def closure_pins() -> list[dict]:
    text = files("open_fdd.ontology_audit").joinpath("data/223p-closure.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    pins = payload["files"]
    if payload.get("root_iri") != S223_ROOT:
        raise ValueError("223p-closure.json root_iri does not match S223_ROOT")
    return pins


def imported_pins() -> list[dict]:
    return [item for item in closure_pins() if item["iri"] != S223_ROOT]


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


def cache_dir() -> Path:
    env = os.environ.get("OPENFDD_223P_CACHE", "").strip()
    return Path(env) if env else Path.home() / ".cache" / "open-fdd" / "223p"


def cached_223p_ttl() -> Path:
    return cache_dir() / "223p.ttl"


def cached_closure_dir() -> Path:
    return cache_dir() / "closure"


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


def _reject_html(payload: bytes, label: str) -> None:
    head = payload.lstrip()[:16].lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        raise ValueError(f"{label} is HTML, not RDF")


def _read_pinned_rdf(path: Path, expected_sha256: str) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = path.read_bytes()
    digest = _sha256(payload)
    if digest != expected_sha256:
        raise ValueError(f"{path} sha256 {digest} != {expected_sha256}")
    _reject_html(payload, str(path))
    return payload


def _download(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def fetch_pin(pin: dict, dest: Path, *, timeout: float = 120.0, urlopen_reader=None) -> str:
    """Write ``pin`` to ``dest`` when the cache misses. Return ``cached`` or ``downloaded``.

    ``urlopen_reader`` is the download function (tests pass a fake). Every URL is
    tried until one matches the pin. A bad hash or an HTML body is not kept.
    """
    expected = pin["sha256"]
    if dest.is_file():
        try:
            _read_pinned_rdf(dest, expected)
        except (OSError, ValueError):
            dest.unlink(missing_ok=True)
        else:
            return "cached"
    dest.parent.mkdir(parents=True, exist_ok=True)
    reader = _download if urlopen_reader is None else urlopen_reader
    errors: list[str] = []
    for url in pin["urls"]:
        fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".part", dir=dest.parent)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            payload = reader(url, timeout)
            _reject_html(payload, url)
            digest = _sha256(payload)
            if digest != expected:
                raise ValueError(f"sha256 {digest} != {expected}")
            tmp.write_bytes(payload)
            tmp.replace(dest)
            return "downloaded"
        except (OSError, ValueError) as exc:
            errors.append(f"{url}: {exc}")
        finally:
            tmp.unlink(missing_ok=True)
    raise ValueError(f"{pin['filename']} pin failed: " + "; ".join(errors))


def ensure_223p_cache(*, timeout: float = 120.0) -> Path:
    """Download any missing pin into the cache. Matching files stay put."""
    root = cache_dir()
    for pin in closure_pins():
        fetch_pin(pin, root / pin["filename"], timeout=timeout)
    return root


def _ontology_files(directory: Path) -> list[Path]:
    return [path for path in sorted(directory.rglob("*"))
            if path.is_file() and path.suffix.lower() in _ONTOLOGY_SUFFIXES]


def materialize_223p_closure(dest: Path, shapes_path: Path | None = None) -> list[str]:
    """Copy the cached imports into ``dest`` and resolve them with OntoEnv offline.

    Returns the imported ontology IRIs. ``missing_imports`` must be empty.
    The copy does not open a URL; ``ensure_223p_cache`` already did, if needed.
    """
    ensure_223p_cache()
    shapes_path = Path(shapes_path) if shapes_path else cached_223p_ttl()
    root_pin = next(item for item in closure_pins() if item["filename"] == "223p.ttl")
    _read_pinned_rdf(shapes_path, root_pin["sha256"])
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for item in imported_pins():
        source = cache_dir() / item["filename"]
        body = _read_pinned_rdf(source, item["sha256"])
        target = dest / Path(item["filename"]).name
        if source.resolve() != target.resolve():
            target.write_bytes(body)
    try:
        from ontoenv import OntoEnv
    except ImportError as exc:
        raise ValueError('OntoEnv needed: pip install "open-fdd[ontology-align]"') from exc
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
    ensure_223p_cache()
    shapes_path = Path(shapes_path) if shapes_path else cached_223p_ttl()
    root_pin = next(item for item in closure_pins() if item["filename"] == "223p.ttl")
    _read_pinned_rdf(shapes_path, root_pin["sha256"])
    files_to_add = [shapes_path]
    if ontology_dir is not None:
        files_to_add.extend(_ontology_files(Path(ontology_dir)))
    else:
        for item in imported_pins():
            source = cache_dir() / item["filename"]
            _read_pinned_rdf(source, item["sha256"])
            files_to_add.append(source)
    try:
        from ontoenv import OntoEnv
    except ImportError as exc:
        raise ValueError('OntoEnv needed: pip install "open-fdd[ontology-align]"') from exc
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


def main(argv: list[str] | None = None) -> int:
    """Download the pins (no-op when the cache already matches) and print the cache path."""
    del argv
    print(ensure_223p_cache())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
