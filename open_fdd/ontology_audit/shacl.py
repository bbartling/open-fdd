"""Optional SHACL validation (pySHACL, extra ``ontology-shacl``) of a building graph."""
from __future__ import annotations

from importlib.resources import files
from typing import Any


def default_shapes_text() -> str:
    """Shapes for the Open-FDD NF export: point / equipment refs and one history id per history reference."""
    return files("open_fdd.ontology_audit").joinpath("data/openfdd_export_shapes.ttl").read_text(encoding="utf-8")


def pyshacl_available() -> bool:
    try:
        import pyshacl  # noqa: F401
    except ImportError:
        return False
    return True


def validate_shacl(graph, shapes=None) -> dict[str, Any]:
    """``{"available", "conforms", "violations": [...]}``; Haystack IRIs normalized first (see ``doctor``)."""
    if not pyshacl_available():
        return {"available": False, "conforms": None, "violations": [],
                "detail": 'pySHACL not installed: pip install "open-fdd[ontology-shacl]"'}
    from pyshacl import validate
    from rdflib import Graph, Namespace, URIRef

    from open_fdd.ontology_audit.doctor import normalize_graph

    if shapes is None:
        shapes = Graph().parse(data=default_shapes_text(), format="turtle")
    conforms, results, _ = validate(normalize_graph(graph), shacl_graph=shapes, inference="none",
                                    allow_warnings=True)
    sh = Namespace("http://www.w3.org/ns/shacl#")
    violations = []
    for r in results.subjects(URIRef(str(sh) + "focusNode"), None):
        violations.append({
            "focus": str(results.value(r, sh.focusNode)),
            "path": str(results.value(r, sh.resultPath) or ""),
            "severity": str(results.value(r, sh.resultSeverity) or "").rsplit("#", 1)[-1],
            "message": str(results.value(r, sh.resultMessage) or ""),
        })
    violations.sort(key=lambda v: (v["focus"], v["path"], v["message"]))
    return {"available": True, "conforms": bool(conforms), "violations": violations, "detail": ""}
