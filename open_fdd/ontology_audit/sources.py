"""Pinned ontology sources: manifest, explicit download (``refresh``) and offline loading.

Nothing is downloaded unless ``refresh`` is called (``--refresh``). A downloaded file must match the pinned sha256,
else it is rejected, so CI and repeat runs never pick up a changed "latest". Any other ``*.ttl`` / ``*.nt`` /
``*.jsonld`` / ``*.rdf`` file in the ontology directory is loaded as a local vocabulary with its own hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Iterable

RDF_SUFFIXES = {".ttl": "turtle", ".nt": "nt", ".jsonld": "json-ld", ".json-ld": "json-ld", ".rdf": "xml",
                ".owl": "xml", ".n3": "n3", ".trig": "trig"}


def _manifest() -> list[dict[str, Any]]:
    text = files("open_fdd.ontology_audit").joinpath("data/sources.json").read_text(encoding="utf-8")
    return json.loads(text)["sources"]


SOURCES: list[dict[str, Any]] = _manifest()


def default_ontology_dir() -> Path:
    """``$OPENFDD_ONTOLOGY_DIR`` or ``~/.cache/open-fdd/ontologies`` (outside Git)."""
    env = os.environ.get("OPENFDD_ONTOLOGY_DIR")
    return Path(env) if env else Path.home() / ".cache" / "open-fdd" / "ontologies"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class LoadedSource:
    """One vocabulary snapshot: where it came from and whether it loaded."""

    name: str
    vocabulary: str
    version: str
    url: str
    sha256: str
    license: str
    namespaces: list[str]
    path: str = ""
    status: str = "SOURCE_UNAVAILABLE"
    detail: str = ""
    graph: Any = field(default=None, repr=False)

    @property
    def loaded(self) -> bool:
        return self.graph is not None

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("name", "vocabulary", "version", "url", "sha256", "license",
                                                "namespaces", "path", "status", "detail")}


def refresh(ontology_dir: Path | None = None, names: Iterable[str] | None = None, *, timeout: float = 120.0,
            log: Callable[[str], None] | None = print) -> list[LoadedSource]:
    """Download the pinned sources (all, or ``names``) into ``ontology_dir``; reject any hash mismatch."""
    target = Path(ontology_dir or default_ontology_dir())
    target.mkdir(parents=True, exist_ok=True)
    wanted = set(names) if names else None
    out = []
    for spec in SOURCES:
        if wanted is not None and spec["name"] not in wanted:
            continue
        dest = target / spec["file"]
        src = _from_spec(spec, dest)
        if dest.is_file() and sha256_file(dest) == spec["sha256"]:
            src.status, src.detail = "CACHED", "already cached"
            out.append(src)
            continue
        fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".part", dir=target)
        tmp = Path(tmp_name)
        try:
            req = urllib.request.Request(spec["url"], headers={"User-Agent": "open-fdd-ontology-audit"})
            with urllib.request.urlopen(req, timeout=timeout) as resp, os.fdopen(fd, "wb") as f:  # noqa: S310
                while chunk := resp.read(1 << 20):
                    f.write(chunk)
        except OSError as exc:
            try:
                os.close(fd)
            except OSError:
                pass
            tmp.unlink(missing_ok=True)
            src.detail = f"download failed: {exc}"
            out.append(src)
            if log:
                log(f"{spec['name']}: {src.detail}")
            continue
        got = sha256_file(tmp)
        if got != spec["sha256"]:
            tmp.unlink(missing_ok=True)
            src.detail = f"sha256 {got} differs from the pinned {spec['sha256']}: not used"
        else:
            tmp.replace(dest)
            src.status, src.detail = "DOWNLOADED", f"{dest.stat().st_size} bytes"
        out.append(src)
        if log:
            log(f"{spec['name']}: {src.status} {src.detail}")
    return out


def _from_spec(spec: dict[str, Any], path: Path) -> LoadedSource:
    return LoadedSource(name=spec["name"], vocabulary=spec["vocabulary"], version=spec["version"], url=spec["url"],
                        sha256=spec["sha256"], license=spec["license"], namespaces=list(spec["namespaces"]),
                        path=str(path))


def _external_contexts(node) -> list[str]:
    """Remote / file ``@context`` references anywhere in a JSON-LD document."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "@import" and isinstance(value, str):  # JSON-LD 1.1 context import is a fetch too
                found.append(value)
            elif key == "@context":
                for ctx in value if isinstance(value, list) else [value]:
                    if isinstance(ctx, str):
                        found.append(ctx)
                    else:
                        found.extend(_external_contexts(ctx))
            else:
                found.extend(_external_contexts(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_external_contexts(item))
    return found


def parse_rdf(path: Path):
    """Parse a local RDF file without any network or file side loads.

    JSON-LD with a remote or file ``@context`` and RDF/XML with a DOCTYPE (external entities) are rejected with
    ``ValueError``: offline means only this file's own bytes, which are what the recorded hash covers.
    """
    from rdflib import Graph

    path = Path(path)
    fmt = RDF_SUFFIXES.get(path.suffix.lower(), "turtle")
    data = path.read_bytes()
    if fmt == "json-ld":
        external = _external_contexts(json.loads(data.decode("utf-8")))
        if external:
            raise ValueError(f"{path.name}: external JSON-LD @context not loaded offline: {', '.join(external[:3])}")
    if fmt == "xml" and b"<!DOCTYPE" in data[:4096].upper():
        raise ValueError(f"{path.name}: RDF/XML with a DOCTYPE (external entities) is not loaded")
    # the file URI as base, so relative IRIs such as <#AHU> resolve to the file, not the working directory
    return Graph().parse(data=data, format=fmt, publicID=path.resolve().as_uri())


def _namespaces_of(graph) -> list[str]:
    """Namespaces a local vocabulary declares terms in (from its typed subjects), most used first."""
    from collections import Counter

    from rdflib import RDF, URIRef

    from open_fdd.ontology_audit.terms import canonical_iri, split_iri

    counts = Counter(split_iri(canonical_iri(str(s)))[0] for s in set(graph.subjects(RDF.type, None))
                     if isinstance(s, URIRef))
    return [ns for ns, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if ns]


def load_sources(ontology_dir: Path | None = None, names: Iterable[str] | None = None,
                 extra_files: Iterable[Path] = ()) -> list[LoadedSource]:
    """Load the pinned snapshots found in ``ontology_dir`` (offline) plus any other RDF file there or in ``extra_files``.

    A pinned source that is missing or whose hash differs comes back with ``status="SOURCE_UNAVAILABLE"``.
    """
    base = Path(ontology_dir) if ontology_dir else default_ontology_dir()
    wanted = set(names) if names else None
    out: list[LoadedSource] = []
    pinned_files = set()
    for spec in SOURCES:
        pinned_files.add(spec["file"])
        if wanted is not None and spec["name"] not in wanted:
            continue
        path = base / spec["file"]
        src = _from_spec(spec, path)
        if not path.is_file():
            src.detail = f"not cached: run with --refresh (downloads {spec['url']})"
            out.append(src)
            continue
        try:
            got = sha256_file(path)
            if got != spec["sha256"]:
                src.detail = f"sha256 {got} differs from the pinned {spec['sha256']}"
            else:
                src.graph = parse_rdf(path)
                src.status, src.detail = "LOADED", f"{len(src.graph)} triples"
        except Exception as exc:  # noqa: BLE001 - one bad source must not stop the audit
            src.detail = f"unreadable: {exc}"
        out.append(src)
    local = [p for p in sorted(base.glob("*")) if p.suffix.lower() in RDF_SUFFIXES and p.name not in pinned_files] \
        if base.is_dir() else []
    for path in [*local, *[Path(p) for p in extra_files]]:
        src = LoadedSource(name=f"local:{path.stem}", vocabulary="local file", version="", url=path.as_uri()
                           if path.is_absolute() else str(path), sha256="", license="as supplied", namespaces=[],
                           path=str(path))
        try:
            src.sha256 = sha256_file(path)
            src.graph = parse_rdf(path)
            src.namespaces = _namespaces_of(src.graph)
            src.status, src.detail = "LOADED", f"{len(src.graph)} triples"
        except Exception as exc:  # noqa: BLE001
            src.detail = f"load failed: {exc}"
        out.append(src)
    return out
