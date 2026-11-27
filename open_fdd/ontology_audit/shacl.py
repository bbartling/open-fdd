"""SHACL validation of a building graph or a 223P role file.

The default engine is Shifty (``pyshifty==0.6.0``). ``infer=True``,
``graph_mode="union"`` and ``on_unsupported="error"`` are that library's
defaults. ``minimum_severity="Violation"`` is this project's CI threshold:
Shifty 0.6.0 itself defaults to ``"info"``, which would fail a Warning-only report.

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

# infer, graph_mode and on_unsupported match shifty.validate. minimum_severity
# is the project threshold (the library default is "info").
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


def _data_with_subclass_axioms(data, shapes):
    """Copy ``rdfs:subClassOf`` from the shapes graph onto the data graph.

    pySHACL with ``inference="none"`` still applies ``sh:class``, and that check
    looks in the data graph. The axioms are the closure's stated hierarchy, not
    an OWL or RDFS entailment.
    """
    from rdflib import Graph, RDFS

    axioms = list(shapes.triples((None, RDFS.subClassOf, None)))
    if not axioms:
        return data
    out = Graph()
    out += data
    for triple in axioms:
        out.add(triple)
    return out


def _pyshacl(data, shapes) -> dict[str, Any]:
    if not pyshacl_available():
        return {"available": False, "conforms": None, "violations": [], "engine": "pyshacl",
                "detail": 'pySHACL not installed: pip install "open-fdd[ontology-shacl]"',
                **PYSHACL_SETTINGS}
    from pyshacl import validate

    conforms, results, _text = validate(
        _data_with_subclass_axioms(data, shapes), shacl_graph=shapes, **PYSHACL_SETTINGS)
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


def _shapes_for(closure, shapes):
    """Closure alone, local shapes alone, or both when the caller passed a file and a closure."""
    from rdflib import Graph

    if closure is None:
        return normalize_ready(shapes)
    if shapes is None:
        return closure
    combined = Graph()
    combined += closure
    combined += normalize_ready(shapes)
    return combined


def normalize_ready(shapes):
    from open_fdd.ontology_audit.doctor import normalize_graph

    return normalize_graph(_shapes_graph(shapes))


def validate_shacl(graph, shapes=None, *, engine: str = "shifty", closure=None,
                   cross_check: bool = False) -> dict[str, Any]:
    """Validate ``graph``. ``closure`` is the shapes graph when the model imports 223P.

    A shapes graph passed together with ``closure`` is added to that closure.
    Haystack IRIs are normalized first. ``engine`` is ``shifty`` (default) or
    ``pyshacl``. There is no silent fallback from one engine to the other.
    A cross-check that raises is recorded and does not replace the primary verdict.
    """
    if engine not in ("shifty", "pyshacl"):
        raise ValueError("engine must be 'shifty' or 'pyshacl'")
    from open_fdd.ontology_audit.doctor import normalize_graph

    data = normalize_graph(graph)
    shapes_graph = _shapes_for(closure, shapes)
    info = _shifty(data, shapes_graph) if engine == "shifty" else _pyshacl(data, shapes_graph)
    info["closure_loaded"] = closure is not None
    if cross_check:
        other = _pyshacl if engine == "shifty" else _shifty
        other_name = "pyshacl" if engine == "shifty" else "shifty"
        try:
            info["cross_check"] = other(data, shapes_graph)
        except (OSError, ValueError, RuntimeError) as exc:
            info["cross_check"] = {
                "available": False, "conforms": None, "violations": [],
                "engine": other_name, "detail": str(exc),
            }
    return info


def violation_count(report: dict[str, Any]) -> int:
    """Results whose severity is Violation (Shifty's failing severity)."""
    return sum(1 for row in report.get("violations") or [] if str(row.get("severity", "")).lower() == "violation")
