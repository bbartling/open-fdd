"""SHACL validation of a building graph or a 223P model.

:func:`validate_223p` is the 223P check. It matches the edge validator:
OntoEnv 0.6.4 loads the vendored closure offline, and Shifty 0.6.0 is called
with ``minimum_severity="Violation"`` only (the other arguments stay the
library defaults: ``infer=True``, ``graph_mode="union"``,
``on_unsupported="error"``). The library default severity is ``"info"``.
``conforms`` is that Shifty result. A pySHACL cross-check is recorded only
when asked and does not replace it. This function is Python CI tooling. The
NF plugin does not import it.

:func:`validate_shacl` checks a Haystack export against the local shapes file.
pySHACL (``pyshacl==0.40.2``) is that file's optional engine. ``advanced=True``
is SHACL-AF; ``inference="none"`` keeps OWL/RDFS entailment off.
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


def _223p_result_rows(report) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    from rdflib import RDF
    from rdflib.namespace import SH

    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        severity = str(report.value(result, SH.resultSeverity) or "")
        row = {
            "severity": severity.rsplit("#", 1)[-1],
            "focus": str(report.value(result, SH.focusNode) or ""),
            "path": str(report.value(result, SH.resultPath) or ""),
            "message": str(report.value(result, SH.resultMessage) or ""),
            "shape": str(report.value(result, SH.sourceShape) or ""),
        }
        if severity.endswith("Warning"):
            warnings.append(row)
        elif severity.endswith("Info"):
            continue
        else:
            violations.append(row)
    return violations, warnings


def validate_223p(model_path, *, shapes_path=None, ontology_dir=None, cross_check=None) -> dict[str, Any]:
    """OntoEnv 0.6.4 closure plus Shifty 0.6.0, same call as the edge validator.

    ``conforms`` is Shifty's result at ``minimum_severity="Violation"``.
    ``cross_check="pyshacl"`` records a second result and does not set ``conforms``.
    """
    from pathlib import Path

    from open_fdd.ontology_audit.closure import (
        PINNED_223P_SHA256,
        S223_ROOT,
        _add_local_ontology,
        _ontology_files,
        _read_pinned_rdf,
        vendored_223p_ttl,
        vendored_closure_dir,
    )

    model_path = Path(model_path)
    if not model_path.is_file():
        raise FileNotFoundError(model_path)
    shapes_path = Path(shapes_path) if shapes_path else vendored_223p_ttl()
    _read_pinned_rdf(shapes_path, PINNED_223P_SHA256)
    if cross_check not in {None, "pyshacl"}:
        raise ValueError("cross_check must be 'pyshacl' or omitted")
    try:
        from ontoenv import OntoEnv
    except ImportError as exc:
        raise ValueError('OntoEnv needed: pip install "open-fdd[ontology-align]"') from exc
    try:
        import shifty
    except ImportError as exc:
        raise ValueError('Shifty needed: pip install "open-fdd[ontology-align]"') from exc

    extra = vendored_closure_dir() if ontology_dir is None else Path(ontology_dir)
    with OntoEnv(temporary=True, offline=True, strict=True) as env:
        for path in [shapes_path, *_ontology_files(extra)]:
            _add_local_ontology(env, str(path))
        missing = [str(item) for item in env.missing_imports(S223_ROOT)]
        if missing:
            raise ValueError("Unresolved owl:imports: " + ", ".join(missing))
        closure, names = env.copy_closure(S223_ROOT)
    if not len(closure):
        raise ValueError(f"Empty dependency closure for {S223_ROOT}")

    from rdflib import Graph

    data = Graph().parse(str(model_path))
    conforms, report, text = shifty.validate(data, closure, minimum_severity="Violation")
    violations, warnings = _223p_result_rows(report)
    info = {
        "conforms": bool(conforms),
        "engine": "shifty",
        "shapes": str(shapes_path),
        "closure": [str(name) for name in names],
        "violations": violations,
        "warnings": warnings,
        "violation_count": len(violations),
        "warning_count": len(warnings),
        "report_text": str(text)[:20000],
        "minimum_severity": "Violation",
    }
    if cross_check == "pyshacl":
        from pyshacl import validate as pyshacl_validate

        cross_conforms, _cross_report, cross_text = pyshacl_validate(
            data_graph=data,
            shacl_graph=closure,
            advanced=True,
            inference="none",
            abort_on_first=False,
        )
        info["cross_check"] = {
            "engine": "pyshacl",
            "advanced": True,
            "conforms": bool(cross_conforms),
            "report_text": str(cross_text)[:4000],
        }
    return info
