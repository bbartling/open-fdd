#!/usr/bin/env python3
"""Fail-closed check of equivalent parsed RDF through the static UI TTL parser.

The RDFLib graph is the independent oracle. The candidate is the actual
``parseTtlModel`` JavaScript module, invoked with Node; no RDF text heuristics
are used to derive expected equipment or point counts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import rdflib
from rdflib import Graph, Namespace, RDF
from rdflib.compare import isomorphic

ROOT = Path(__file__).resolve().parents[3]
PARSER = ROOT / "services/central/static/product/assets/js/ttl-model.js"
PHIOT = Namespace("https://project-haystack.org/def/phIoT/4.0.0#")
BASE = '''@prefix local: <urn:qa:> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
@prefix phScience: <https://project-haystack.org/def/phScience/4.0.0#> .
@prefix ph: <https://project-haystack.org/def/ph/4.0.0#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

local:e a phIoT:equip ;
 ph:hasTag phIoT:equip ;
 rdfs:label "Synthetic equip" .

local:p a phIoT:point ;
 ph:hasTag phIoT:point ;
 ph:hasTag phIoT:zone, phScience:air, phScience:temp, phIoT:sensor ;
 phIoT:equipRef local:e ;
 ph:unit "°C" ;
 rdfs:label "Synthetic point" .
'''
DEFAULT_CASES = [
    {"name": "control", "ttl": BASE},
    {"name": "reflow", "ttl": BASE.replace("\n\n", "\n")},
    {"name": "renamed_prefix", "ttl": BASE.replace("local:", "qa:")},
    {"name": "full_iri", "ttl": Graph().parse(data=BASE, format="turtle").serialize(format="nt")},
]
NODE_PROGRAM = r"""
const {parseTtlModel}=await import(process.argv[1]);
let input=''; for await (const chunk of process.stdin) input += chunk;
const request=JSON.parse(input);
const model=parseTtlModel('SYN-RDF', request.ttl);
console.log(JSON.stringify({equipment:model.equips.length, points:model.points.length}));
"""


@dataclass
class CaseResult:
    name: str
    rdf_isomorphic: bool
    expected_equipment: int
    expected_points: int
    candidate_equipment: int | None
    candidate_points: int | None
    status: str
    error: str | None = None


def _parse_turtle(text: Any) -> Graph:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("case ttl must be non-empty text")
    graph = Graph()
    stripped = text.lstrip()
    if stripped.startswith("<") and " .\n" in stripped:
        return graph.parse(data=text, format="nt")
    return graph.parse(data=text, format="turtle")


def _oracle_counts(graph: Graph) -> tuple[int, int]:
    return (
        len(set(graph.subjects(RDF.type, PHIOT.equip))),
        len(set(graph.subjects(RDF.type, PHIOT.point))),
    )


def evaluate_cases(
    cases: list[dict[str, Any]],
    parser: Callable[[str], Any],
) -> dict[str, Any]:
    if not isinstance(cases, list) or not cases:
        raise ValueError("at least one case is required")
    reference = _parse_turtle(cases[0].get("ttl"))
    expected_equipment, expected_points = _oracle_counts(reference)
    if (expected_equipment, expected_points) != (1, 1):
        raise ValueError("reference RDF must parse to exactly one equipment and one point")
    names: set[str] = set()
    results: list[CaseResult] = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each case must be an object")
        name = case.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("each case needs a unique non-empty name")
        names.add(name)
        graph = _parse_turtle(case.get("ttl"))
        equivalent = isomorphic(reference, graph)
        case_equipment, case_points = _oracle_counts(graph)
        raw: Any = None
        error = None
        try:
            raw = parser(case["ttl"])
            if not isinstance(raw, dict):
                raise ValueError("candidate output must be an object")
            equip = raw.get("equipment")
            points = raw.get("points")
            if type(equip) is not int or type(points) is not int or equip < 0 or points < 0:
                raise ValueError("candidate equipment/points must be non-negative integers")
        except Exception as exc:  # Candidate parser failures are qualification failures.
            equip = points = None
            error = f"{type(exc).__name__}: {exc}"
        passed = (equivalent and (case_equipment, case_points) == (1, 1)
                  and equip == case_equipment and points == case_points)
        results.append(CaseResult(
            name=name,
            rdf_isomorphic=equivalent,
            expected_equipment=case_equipment,
            expected_points=case_points,
            candidate_equipment=equip,
            candidate_points=points,
            status="PASS" if passed else "FAIL",
            error=error,
        ))
    passed = all(row.status == "PASS" for row in results)
    return {
        "schema": "openfdd_static_model_probe_v1",
        "scope": "synthetic parsed RDF through actual static UI parser",
        "case_count": len(results),
        "comparison_count": len(results),
        "status": "PASS" if passed else "FAIL",
        "pass": passed,
        "cases": [asdict(row) for row in results],
    }


def probe_identity() -> dict[str, str]:
    return {
        "candidate_git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=30
        ).strip(),
        "parser_sha256": hashlib.sha256(PARSER.read_bytes()).hexdigest(),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rdflib_version": rdflib.__version__,
        "node_version": subprocess.check_output(
            ["node", "--version"], text=True, timeout=30
        ).strip(),
    }


def parse_with_node(ttl: str) -> dict[str, Any]:
    if not PARSER.is_file():
        raise FileNotFoundError(f"static UI parser missing: {PARSER}")
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_PROGRAM, PARSER.as_uri()],
        input=json.dumps({"ttl": ttl}), text=True, capture_output=True, timeout=10,
    )
    if proc.returncode:
        raise RuntimeError(f"node parser exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("candidate emitted malformed JSON") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, help="JSON array of named {name, ttl} cases")
    ap.add_argument("--json-out", type=Path, help="Optional machine-readable result path")
    args = ap.parse_args(argv)
    try:
        cases = DEFAULT_CASES if args.cases is None else json.loads(args.cases.read_text(encoding="utf-8"))
        result = evaluate_cases(cases, parse_with_node)
    except Exception as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    try:
        result["identity"] = probe_identity()
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"BLOCKED: identity unavailable ({type(exc).__name__})", file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        try:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            print(f"BLOCKED: cannot write result: {exc}", file=sys.stderr)
            return 2
    print(rendered, end="")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
