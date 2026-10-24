#!/usr/bin/env python3
"""Offline, known-answer qualification for Open-FDD's named-IRI RDF profile.

This independently parses Turtle and executes fixed SPARQL SELECTs. It does not
fetch definitions, follow RDF links, run user-provided queries, infer identities
from names, or confer authorization. Supply an authorized candidate export to
``model``; ``suite`` tests the evaluator and synthetic controls only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "scripts/qualification/fixtures/semantic"
DEFS_DIR = ROOT / "edge/assets/haystack_rdf/defs"
PROFILE = "ofdd_haystack_projection_v1"
SCHEMA = "openfdd_semantic_qualification_v1"
MAX_BYTES = 2 * 1024 * 1024
MAX_TRIPLES = 50_000
MAX_CASES = 32
MAX_ROWS = 1000
BASES = {
    "ph": "https://project-haystack.org/def/ph/4.0.0#",
    "phIoT": "https://project-haystack.org/def/phIoT/4.0.0#",
    "phScience": "https://project-haystack.org/def/phScience/4.0.0#",
    "phIct": "https://project-haystack.org/def/phIct/4.0.0#",
}
OFDD = "urn:openfdd:ns#"
PREFIXES = "\n".join(f"PREFIX {key}: <{value}>" for key, value in BASES.items())
PREFIXES += f"\nPREFIX ofdd: <{OFDD}>\n"
POINT_QUERY = PREFIXES + """
SELECT DISTINCT ?point WHERE {
  ?equip a phIoT:equip ; phIoT:siteRef ?site .
  ?point a phIoT:point ; phIoT:siteRef ?site ; phIoT:equipRef ?equip .
  ?point ph:hasTag ?tag0 .
  %s
} ORDER BY ?point LIMIT 1001
"""
# Local engineering acceptance profile, not an exhaustive Haystack unit registry.
# Units must be explicit; no display-name/column-name inference or conversion here.
UNITS = {
    "temperature": {"°F", "°C", "K"},
    "pressure": {"Pa", "kPa", "inH₂O", "in. w.c."},
    "fraction": {"%", "1"},
    "airflow": {"cfm", "L/s", "m³/s"},
}
REQUIRED_CONTROLS = {
    "VALID", "WRONG_NAMESPACE", "WRONG_CASE", "DANGLING_REFERENCE", "WRONG_QUANTITY_UNIT",
    "WRONG_KIND", "STALE_DECODED_SERIES_KEY", "FALSE_MARKER", "NULL_MARKER", "BOOL_AS_STRING",
    "AMBIGUOUS_FUNCTION", "EMPTY", "MALFORMED",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bounded(path: Path, limit: int = MAX_BYTES) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError("input exceeds byte budget")
    return data


def load_json(path: Path) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(read_bounded(path), object_pairs_hook=no_duplicates)


def rdf() -> Any:
    try:
        import rdflib
    except ImportError as exc:
        raise RuntimeError("rdflib missing; install semantic/requirements.txt in a tooling venv") from exc
    return rdflib


def parse_graph(data: bytes) -> Any:
    if len(data) > MAX_BYTES:
        raise ValueError("model exceeds byte budget")
    lib = rdf()
    graph = lib.Graph()
    # data+format prevents remote URL/context resolution. Turtle has no imports.
    graph.parse(data=data.decode("utf-8"), format="turtle", publicID="urn:openfdd:qualification:")
    if len(graph) > MAX_TRIPLES:
        raise ValueError("graph exceeds triple budget")
    return graph


def parse_model(text: str | bytes) -> Any:
    """Independent, bounded Turtle parser for other qualification gates.

    Raises when the dependency, syntax or byte/triple budget is unavailable.
    Returns an RDFLib Graph, never a text-search-derived approximation.
    """
    return parse_graph(text.encode("utf-8") if isinstance(text, str) else text)


def graph_inventory(graph: Any) -> dict[str, Any]:
    """Small parsed inventory summary; callers must compare independent counts.

    This function alone establishes neither Haystack validity nor authorization.
    """
    lib = rdf()
    iot = lib.Namespace(BASES["phIoT"])
    result: dict[str, Any] = {"triple_count": len(graph)}
    for name in ("site", "equip", "point"):
        nodes = sorted(str(node) for node in set(graph.subjects(lib.RDF.type, iot[name])))
        result[name + "_ids"] = nodes
        result[name + "_count"] = len(nodes)
    return result


def load_defs() -> tuple[Any, dict[str, Any], dict[str, str]]:
    pin_data = read_bounded(DEFS_DIR / "defs.pin.json")
    pin = json.loads(pin_data)
    data = read_bounded(DEFS_DIR / "defs.ttl")
    if digest(data) != pin["sha256"] or pin["defs_pin"] != "haystack-defs-ttl-4.0.0":
        raise ValueError("vendored definitions do not match the pinned digest/profile")
    return parse_graph(data), pin, {"defs_sha256": digest(data), "defs_pin_sha256": digest(pin_data)}


def one(graph: Any, subject: Any, predicate: Any) -> Any | None:
    values = list(graph.objects(subject, predicate))
    return values[0] if len(values) == 1 else None


def add_assertion(report: dict[str, Any], check_id: str, passed: bool, detail: str) -> None:
    report["assertions"].append({"id": check_id, "status": "PASS" if passed else "FAIL", "detail": detail})


def valid_iri(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"(?:urn:|https?://)[^\s<>\"{}|^`\\]+", value))


def validate_expectations(expected: Any) -> None:
    if not isinstance(expected, dict) or expected.get("schema") != "openfdd_semantic_expectations_v1":
        raise ValueError("missing supported expectations schema")
    if expected.get("profile") != PROFILE:
        raise ValueError("expectations use a different compatibility profile")
    if not valid_iri(expected.get("site")):
        raise ValueError("an exact authorized site IRI is required")
    inventory = expected.get("point_ids")
    cases = expected.get("selectors")
    if not isinstance(inventory, list) or not inventory or len(inventory) != len(set(inventory)):
        raise ValueError("expected point inventory must be nonempty and unique")
    if len(inventory) > MAX_ROWS or not all(valid_iri(value) for value in inventory):
        raise ValueError("expected point inventory exceeds bounds or has invalid IRIs")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError("a bounded nonempty selector set is required")
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or case["id"] in ids:
            raise ValueError("selector IDs must be nonempty and unique")
        if not case["id"]:
            raise ValueError("selector ID is empty")
        ids.add(case["id"])
        if not valid_iri(case.get("equipment")):
            raise ValueError("selector equipment must be an exact IRI")
        tags = case.get("tags")
        if not isinstance(tags, list) or not 1 <= len(tags) <= 8 or not all(valid_iri(t) for t in tags):
            raise ValueError("selector requires 1..8 exact marker IRIs")
        candidates = case.get("expected_candidates")
        if not isinstance(candidates, list) or not candidates or len(candidates) != len(set(candidates)):
            raise ValueError("known-answer selector candidates must be nonempty and unique")
        if not set(candidates) <= set(inventory):
            raise ValueError("expected selector candidates must be in expected inventory")
        selected = case.get("selected_point")
        readiness = case.get("expected_readiness")
        if readiness not in {"READY", "AMBIGUOUS"}:
            raise ValueError("explicit READY/AMBIGUOUS readiness is required")
        if readiness == "AMBIGUOUS" and (len(candidates) < 2 or selected is not None):
            raise ValueError("ambiguous contract requires multiple candidates and no selection")
        if readiness == "READY" and selected not in candidates:
            raise ValueError("ready contract requires an explicit selected point")
        if case.get("kind") not in {"Number", "Bool", "Str", "Ref"}:
            raise ValueError("supported typed kind is required")
        if case["kind"] == "Number" and case.get("quantity") not in UNITS:
            raise ValueError("numeric selector requires a supported engineering quantity")
        if readiness == "READY":
            for field in ("series_key", "provider_instance", "remote_point_id"):
                if not isinstance(case.get(field), str) or not case[field].strip():
                    raise ValueError("ready selector requires independently specified key/provider/remote identity")
    for item in expected.get("typed_values", []):
        if not isinstance(item, dict) or item.get("id") in ids or not isinstance(item.get("id"), str):
            raise ValueError("typed-value IDs must be unique")
        ids.add(item["id"])
        if not valid_iri(item.get("subject")) or not valid_iri(item.get("predicate")):
            raise ValueError("typed values require exact subject/predicate IRIs")
        value_type, value = item.get("type"), item.get("value")
        if value_type not in {"Bool", "Number", "Str", "Ref"}:
            raise ValueError("typed-value type is unsupported")
        if value_type == "Bool" and not isinstance(value, bool):
            raise ValueError("Bool expectation requires boolean")
        if value_type == "Number" and (isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value)):
            raise ValueError("Number expectation requires finite numeric value")
        if value_type == "Str" and not isinstance(value, str):
            raise ValueError("Str expectation requires string")
        if value_type == "Ref" and not valid_iri(value):
            raise ValueError("Ref expectation requires IRI")


def qualify(model_data: bytes, expected: dict[str, Any], candidate: str) -> dict[str, Any]:
    """Return FAIL for semantic mismatch, BLOCKED for unavailable execution evidence."""
    started = time.monotonic()
    report: dict[str, Any] = {
        "schema": SCHEMA, "mode": "model", "profile": PROFILE, "candidate": candidate,
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "BLOCKED",
        "assertions": [], "assertions_count": 0, "comparison_count": 0,
        "model_sha256": digest(model_data),
        "expectations_sha256": digest(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()),
        "query_sha256": [], "candidate_product_qualified": False,
        "harness_sha256": digest(Path(__file__).read_bytes()),
        "profile_sha256": digest(json.dumps({"id": PROFILE, "bases": BASES,
            "unit_acceptance": {key: sorted(value) for key, value in UNITS.items()},
            "limits": {"bytes": MAX_BYTES, "triples": MAX_TRIPLES, "cases": MAX_CASES, "rows": MAX_ROWS}},
            sort_keys=True, separators=(",", ":")).encode()),
    }
    try:
        if not re.fullmatch(r"[0-9a-f]{7,64}", candidate):
            raise ValueError("candidate must be an immutable hexadecimal commit/image identity")
        if len(model_data) > MAX_BYTES:
            raise ValueError("model exceeds byte budget")
        validate_expectations(expected)
        lib = rdf()
        defs, pin, hashes = load_defs()
        report.update(hashes)
        report["defs_pin"] = pin["defs_pin"]
        report["tool_versions"] = {"python": sys.version.split()[0], "rdflib": lib.__version__}
        try:
            graph = parse_graph(model_data)
        except (ValueError, UnicodeError, lib.exceptions.ParserError, SyntaxError) as exc:
            add_assertion(report, "RDF-SYNTAX", False, f"RDF parse rejected ({type(exc).__name__})")
            report["status"] = "FAIL"
            return finish(report, started)
        U, L = lib.URIRef, lib.Literal
        ph, iot = lib.Namespace(BASES["ph"]), lib.Namespace(BASES["phIoT"])
        ofdd = lib.Namespace(OFDD)
        site = U(expected["site"])
        points = set(graph.subjects(lib.RDF.type, iot.point))
        scoped = {p for p in points if (p, iot.siteRef, site) in graph}
        report["graph_triples"] = len(graph)
        report["observed_point_count"] = len(scoped)
        add_assertion(report, "RDF-INVENTORY", set(map(str, scoped)) == set(expected["point_ids"]),
                      f"exact site inventory: expected {len(expected['point_ids'])}, observed {len(scoped)}")
        report["comparison_count"] += 1
        add_assertion(report, "SITE-TYPE", (site, lib.RDF.type, iot.site) in graph, "scoped site has site type")
        unknown: set[str] = set()
        bad_markers = 0
        for _s, predicate, value in graph:
            for term in (predicate, value):
                if isinstance(term, U) and any(str(term).startswith(base) for base in BASES.values()):
                    if not any(defs.triples((term, None, None))):
                        unknown.add(str(term))
            if predicate == ph.hasTag and (not isinstance(value, U) or (value, lib.RDF.type, lib.OWL.Class) not in defs):
                bad_markers += 1
        add_assertion(report, "DEFS-RESOLUTION", not unknown,
                      f"{len(unknown)} terms missing from pinned, case-sensitive official definitions")
        add_assertion(report, "MARKER-TERMS", bad_markers == 0,
                      f"{bad_markers} hasTag values are not defined class IRIs (false/null/value tags are not markers)")
        scoped_subjects = set(graph.subjects(iot.siteRef, site)) | {site}
        invalid_refs = 0
        for subject in scoped_subjects:
            for predicate in (iot.siteRef, iot.equipRef, iot.airRef):
                for target in graph.objects(subject, predicate):
                    expected_type = iot.site if predicate == iot.siteRef else iot.equip
                    if (not isinstance(target, U) or (target, lib.RDF.type, expected_type) not in graph or
                            target != site and (target, iot.siteRef, site) not in graph):
                        invalid_refs += 1
        add_assertion(report, "REFERENCE-TOPOLOGY", invalid_refs == 0,
                      f"{invalid_refs} dangling, untyped or cross-site reference targets in scoped entities")
        for item in expected.get("typed_values", []):
            value = one(graph, U(item["subject"]), U(item["predicate"]))
            value_type = item["type"]
            actual = value.toPython() if isinstance(value, L) else None
            type_ok = (value_type == "Ref" and isinstance(value, U) and str(value) == item["value"] and
                       any(graph.triples((value, None, None)))) or (isinstance(value, L) and (
                       value_type == "Bool" and isinstance(actual, bool) and actual == item["value"] or
                       value_type == "Number" and not isinstance(actual, bool) and isinstance(actual, (float, int)) and
                       math.isfinite(actual) and actual == item["value"] or
                       value_type == "Str" and isinstance(actual, str) and actual == item["value"]))
            add_assertion(report, item["id"], bool(type_ok), "exact typed literal/reference value matches the independent contract")
            report["comparison_count"] += 1
        for index, point in enumerate(sorted(scoped, key=str)):
            equip = one(graph, point, iot.equipRef)
            point_site = one(graph, point, iot.siteRef)
            add_assertion(report, f"POINT-{index}-REFS", isinstance(equip, U) and point_site == site and
                          (equip, lib.RDF.type, iot.equip) in graph and (equip, iot.siteRef, site) in graph,
                          "one point equipRef/siteRef resolves to an equipment in the exact scoped site")
            functions = set(graph.objects(point, ph.hasTag)) & {iot.sensor, iot.cmd, iot.sp, iot.synthetic}
            add_assertion(report, f"POINT-{index}-FUNCTION", len(functions) == 1, "exactly one point function")
            kind = one(graph, point, ph.kind)
            add_assertion(report, f"POINT-{index}-KIND", isinstance(kind, L) and str(kind) in {"Number", "Bool", "Str", "Ref"},
                          "one supported literal kind")
            if isinstance(kind, L) and str(kind) == "Number":
                unit = one(graph, point, ph.unit)
                add_assertion(report, f"POINT-{index}-UNIT", isinstance(unit, L) and
                              str(unit) in set().union(*UNITS.values()), "numeric point carries one recognized explicit unit")
            if (point, ph.hasTag, iot.his) in graph:
                tz, mode = one(graph, point, ph.tz), one(graph, point, iot.hisMode)
                add_assertion(report, f"POINT-{index}-HISTORY", isinstance(tz, L) and bool(str(tz)) and
                              isinstance(mode, L) and str(mode) in {"sampled", "cov", "consumption"},
                              "historized point declares timezone and history mode")
        selections: list[dict[str, Any]] = []
        for case in expected["selectors"]:
            query = POINT_QUERY % "\n  ".join(f"?point ph:hasTag ?tag{n} ." for n in range(1, len(case["tags"])))
            report["query_sha256"].append(digest(query.encode()))
            bindings = {"site": site, "equip": U(case["equipment"])}
            bindings.update({f"tag{n}": U(tag) for n, tag in enumerate(case["tags"])})
            selected = sorted({str(row.point) for row in graph.query(query, initBindings=bindings)})
            exact = selected == sorted(case["expected_candidates"])
            add_assertion(report, f"{case['id']}-CANDIDATES", exact and len(selected) <= MAX_ROWS,
                          f"exact SPARQL candidates: expected {len(case['expected_candidates'])}, observed {len(selected)}")
            report["comparison_count"] += 1
            ready = "AMBIGUOUS" if len(selected) > 1 and not case.get("selected_point") else "READY" if selected else "MISSING"
            add_assertion(report, f"{case['id']}-READINESS", ready == case["expected_readiness"],
                          f"observed {ready}; no first-match/fuzzy/label selection")
            for point_iri in selected:
                point = U(point_iri)
                kind = one(graph, point, ph.kind)
                unit = one(graph, point, ph.unit)
                kind_ok = isinstance(kind, L) and str(kind) == case["kind"]
                unit_ok = case["kind"] != "Number" or isinstance(unit, L) and str(unit) in UNITS[case["quantity"]]
                add_assertion(report, f"{case['id']}-TYPED-{digest(point_iri.encode())[:12]}", kind_ok and unit_ok,
                              "candidate kind and explicit unit agree with the independent engineering contract")
                report["comparison_count"] += 1
            chosen = case.get("selected_point")
            if chosen is not None:
                key = one(graph, U(chosen), ofdd.seriesKey)
                provider = one(graph, U(chosen), ofdd.providerInstance)
                remote = one(graph, U(chosen), ofdd.remotePointId)
                add_assertion(report, f"{case['id']}-OPAQUE-BINDING", chosen in selected and isinstance(key, L) and
                              str(key) == case["series_key"] and isinstance(provider, L) and
                              str(provider) == case["provider_instance"] and isinstance(remote, L) and
                              str(remote) == case["remote_point_id"],
                              "selected semantic point resolves to the exact expected opaque key, provider and remote identity")
                report["comparison_count"] += 1
            selections.append({"id": case["id"], "point_ids": selected, "selected_point": chosen, "readiness": ready})
        report["selections"] = selections
        report["status"] = "PASS" if all(a["status"] == "PASS" for a in report["assertions"]) else "FAIL"
    except TimeoutError:
        raise
    except Exception as exc:
        # Never persist model excerpts, exception text, endpoint credentials or arbitrary literals.
        report["blocked_reason"] = type(exc).__name__
        report["status"] = "BLOCKED"
    return finish(report, started)


def finish(report: dict[str, Any], started: float) -> dict[str, Any]:
    report["assertions_count"] = len(report["assertions"])
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    if report["status"] == "PASS" and (report["assertions_count"] == 0 or report["comparison_count"] == 0):
        report["status"] = "BLOCKED"
        report["blocked_reason"] = "NoExecutedComparisons"
    return report


def suite(candidate: str) -> dict[str, Any]:
    manifest = load_json(FIXTURES / "suite.json")
    expected = load_json(FIXTURES / "expected.json")
    results = []
    seen: set[str] = set()
    if not isinstance(manifest, dict) or manifest.get("schema") != "openfdd_semantic_controls_v1":
        raise ValueError("unsupported evaluator control schema")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or {case.get("id") for case in cases} != REQUIRED_CONTROLS:
        raise ValueError("required evaluator controls are missing or unexpected")
    for case in cases:
        required_status = "PASS" if case["id"] == "VALID" else "FAIL"
        if case["id"] in seen or case["expected_status"] != required_status:
            raise ValueError("invalid evaluator control contract")
        if required_status == "FAIL" and not case.get("required_failure_ids"):
            raise ValueError("negative control must name the assertion it is expected to fail")
        seen.add(case["id"])
        model = (FIXTURES / case["model"]).resolve()
        if not model.is_relative_to(FIXTURES.resolve()):
            raise ValueError("fixture escapes suite directory")
        result = qualify(read_bounded(model), expected, candidate)
        rejected_as_expected = result["status"] == case["expected_status"]
        failed_ids = {a["id"] for a in result["assertions"] if a["status"] == "FAIL"}
        required = set(case.get("required_failure_ids", []))
        rejected_as_expected = rejected_as_expected and required <= failed_ids
        results.append({"id": case["id"], "expected_status": case["expected_status"],
                        "control_status": "PASS" if rejected_as_expected else "FAIL", "result": result})
    return {"schema": SCHEMA, "mode": "suite", "candidate": candidate,
            "status": "PASS" if results and all(r["control_status"] == "PASS" for r in results) else "FAIL",
            "candidate_product_qualified": False, "scope": "offline_evaluator_and_synthetic_fixtures_only",
            "suite_sha256": digest(read_bounded(FIXTURES / "suite.json")),
            "harness_sha256": digest(Path(__file__).read_bytes()),
            "assertions_count": sum(r["result"]["assertions_count"] for r in results),
            "comparison_count": sum(r["result"]["comparison_count"] for r in results),
            "control_count": len(results), "cases": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["suite", "model"])
    parser.add_argument("--candidate", required=True, help="immutable candidate SHA/digest, never a mutable tag")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--expectations", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30, choices=range(1, 121), metavar="1..120")
    args = parser.parse_args(argv)
    def deadline(_signum: int, _frame: Any) -> None:
        raise TimeoutError("qualification deadline")
    # Fixed queries and bounded files are the primary budget; a hard deadline
    # stops parser/query work as well, rather than classifying a late response.
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(args.timeout_seconds)
    try:
        if args.mode == "model":
            if args.model is None or args.expectations is None:
                parser.error("model requires --model and --expectations")
            report = qualify(read_bounded(args.model), load_json(args.expectations), args.candidate)
        else:
            report = suite(args.candidate)
    except Exception as exc:
        report = {"schema": SCHEMA, "mode": args.mode, "status": "BLOCKED", "candidate": args.candidate,
                  "blocked_reason": type(exc).__name__, "assertions_count": 0, "comparison_count": 0,
                  "candidate_product_qualified": False}
    finally:
        signal.alarm(0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "assertions_count": report["assertions_count"],
                      "comparison_count": report["comparison_count"], "report": str(args.out)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
