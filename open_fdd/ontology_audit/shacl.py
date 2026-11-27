"""SHACL validation of a building graph or a 223P role file.

The default engine is Shifty (``pyshifty==0.6.0``). The call states the library
defaults: SHACL-AF rules on (``infer=True``), ``graph_mode="union"``,
``on_unsupported="error"``, and ``minimum_severity="Violation"``.

pySHACL (``pyshacl==0.40.2``) is the optional cross-check and the engine for the
Haystack export shapes when ``engine="pyshacl"``. ``advanced=True`` is SHACL-AF;
``inference="none"`` keeps OWL/RDFS entailment off. A cross-check is reported
and does not change the Shifty verdict.

Pass ``closure`` (the OntoEnv graph from :func:`copy_223p_closure`) when the
model ``owl:imports`` 223P. Export-shape checks pass the local shapes file; that
file does not import a remote ontology.
"""
from __future__ import annotations

from importlib.resources import files
from typing import Any

# Same knobs as shifty.validate's defaults, named so a caller can see them.
SHIFTY_SETTINGS = {
    "minimum_severity": "Violation",
    "graph_mode": "union",
    "infer": True,
    "on_unsupported": "error",
}
PYSHACL_SETTINGS = {"advanced": True, "inference": "none", "allow_warnings": True}


def default_shapes_text() -> str:
    """Shapes for the Open-FDD NF export: point / equipment refs and one history id per history reference."""
    return files("open_fdd.ontology_audit").joinpath("data/openfdd_export_shapes.ttl").read_text(encoding="utf-8")


def pyshacl_available() -> bool:
    try:
        import pyshacl  # noqa: F401
    except ImportError:
        return False
    return True


def shifty_available() -> bool:
    try:
        import shifty  # noqa: F401
    except ImportError:
        return False
    return True


def _shapes_graph(shapes):
    from rdflib import Graph

    if shapes is None:
        return Graph().parse(data=default_shapes_text(), format="turtle")
    return shapes


def _result_rows(results) -> list[dict[str, str]]:
    from rdflib import Namespace, RDF, URIRef

    sh = Namespace("http://www.w3.org/ns/shacl#")
    found = []
    for node in results.subjects(RDF.type, URIRef(str(sh.ValidationResult))):
        found.append({
            "focus": str(results.value(node, sh.focusNode) or ""),
            "path": str(results.value(node, sh.resultPath) or ""),
            "severity": str(results.value(node, sh.resultSeverity) or "").rsplit("#", 1)[-1],
            "message": str(results.value(node, sh.resultMessage) or ""),
        })
    found.sort(key=lambda v: (v["severity"], v["focus"], v["path"], v["message"]))
    return found


def _pyshacl(data, shapes) -> dict[str, Any]:
    if not pyshacl_available():
        return {"available": False, "conforms": None, "violations": [], "engine": "pyshacl",
                "detail": 'pySHACL not installed: pip install "open-fdd[ontology-shacl]"',
                **PYSHACL_SETTINGS}
    from pyshacl import validate

    conforms, results, _text = validate(data, shacl_graph=shapes, **PYSHACL_SETTINGS)
    if not hasattr(results, "subjects"):
        raise ValueError(f"SHACL validation failed to run: {results}")
    return {"available": True, "conforms": bool(conforms), "violations": _result_rows(results),
            "detail": "", "engine": "pyshacl", **PYSHACL_SETTINGS}


def _shifty(data, shapes) -> dict[str, Any]:
    if not shifty_available():
        return {"available": False, "conforms": None, "violations": [], "engine": "shifty",
                "detail": 'Shifty not installed: pip install "open-fdd[ontology-align]"',
                **SHIFTY_SETTINGS}
    import shifty

    conforms, report, text = shifty.validate(data, shapes, **SHIFTY_SETTINGS)
    if not hasattr(report, "subjects"):
        raise ValueError(f"SHACL validation failed to run: {report}")
    return {"available": True, "conforms": bool(conforms), "violations": _result_rows(report),
            "detail": "", "engine": "shifty", "report_text": str(text)[:20000], **SHIFTY_SETTINGS}


def validate_shacl(graph, shapes=None, *, engine: str = "shifty", closure=None,
                   cross_check: bool = False) -> dict[str, Any]:
    """Validate ``graph``. ``closure`` is the shapes graph when the model imports 223P.

    Haystack IRIs are normalized first. ``engine`` is ``shifty`` (default) or
    ``pyshacl``. There is no silent fallback from one engine to the other.
    """
    if engine not in ("shifty", "pyshacl"):
        raise ValueError("engine must be 'shifty' or 'pyshacl'")
    from open_fdd.ontology_audit.doctor import normalize_graph

    data = normalize_graph(graph)
    shapes_graph = closure if closure is not None else _shapes_graph(shapes)
    if closure is None:
        shapes_graph = normalize_graph(shapes_graph)
    info = _shifty(data, shapes_graph) if engine == "shifty" else _pyshacl(data, shapes_graph)
    info["closure_loaded"] = closure is not None
    if cross_check and engine == "shifty":
        info["cross_check"] = _pyshacl(data, shapes_graph)
    elif cross_check:
        info["cross_check"] = _shifty(data, shapes_graph)
    return info


def violation_count(report: dict[str, Any]) -> int:
    """Results whose severity is Violation (Shifty's failing severity)."""
    return sum(1 for row in report.get("violations") or [] if str(row.get("severity", "")).lower() == "violation")
