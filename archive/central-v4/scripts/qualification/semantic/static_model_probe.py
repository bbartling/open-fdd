#!/usr/bin/env python3
"""Fail-closed check of static UI model loading against server projection contract.

The RDFLib graph is the independent oracle for Turtle equivalence. The candidate
exercises ``loadModelProjection`` and ``loadModelFromTtl`` from the shipped
``ttl-model.js`` module (Node). When a central binary is available, responses
from ``GET /api/model/projection`` must match the same counts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import rdflib
from rdflib import Graph, Namespace, RDF
from rdflib.compare import isomorphic

ROOT = Path(__file__).resolve().parents[3]
TTL_MODEL = ROOT / "services/central/static/product/assets/js/ttl-model.js"
PHIOT = Namespace("https://project-haystack.org/def/phIoT/4.0.0#")
BASE = '''@prefix local: <urn:qa:> .
@prefix ofdd: <urn:openfdd:ns#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
@prefix phScience: <https://project-haystack.org/def/phScience/4.0.0#> .
@prefix ph: <https://project-haystack.org/def/ph/4.0.0#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

local:e a phIoT:equip ;
 ofdd:equipmentId "SYN_EQUIP" ;
 ph:hasTag phIoT:equip ;
 rdfs:label "Synthetic equip" .

local:p a phIoT:point ;
 ofdd:pointId "SYN_POINT" ;
 ofdd:column "SYN_COL" ;
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
PROBE_BUILDING = "STATIC_MODEL_PROBE_SITE"
PROBE_EQUIP = "SYN_EQUIP"
PROBE_POINT = "SYN_POINT"
UI_SCHEMA = "ofdd_static_ui_model_projection_v1"
NODE_PROGRAM = r"""
const { loadModelFromTtl, loadModelProjection } = await import(process.argv[1]);
let input = "";
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
const buildingId = request.buildingId;
const projection = request.projection;
const ttlText = request.ttl;
const liveBase = request.liveBase || "";

async function apiFetch(path) {
  if (liveBase) {
    const res = await fetch(`${liveBase}${path}`);
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res.text();
  }
  if (path.includes("/api/model/projection")) return projection;
  if (path.includes("/api/model/ttl")) return ttlText;
  throw new Error(`unexpected apiFetch path in offline mode: ${path}`);
}

const fromProjection = await loadModelProjection(buildingId, apiFetch);
const fromTtl = await loadModelFromTtl(buildingId, apiFetch);
console.log(JSON.stringify({
  projection: { equipment: fromProjection.equips.length, points: fromProjection.points.length },
  load_from_ttl: { equipment: fromTtl.model.equips.length, points: fromTtl.model.points.length },
}));
"""


@dataclass
class CaseResult:
    name: str
    rdf_isomorphic: bool
    expected_equipment: int
    expected_points: int
    candidate_equipment: int | None
    candidate_points: int | None
    central_equipment: int | None
    central_points: int | None
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


def _probe_meta(building_id: str) -> dict[str, Any]:
    return {
        "schema": "openfdd_semantic_meta_v1",
        "building_id": building_id,
        "equipment": [{"equipment_id": PROBE_EQUIP, "haystack_tags": ["equip"]}],
        "points": [{
            "equipment_id": PROBE_EQUIP,
            "column": "SYN_COL",
            "point_id": PROBE_POINT,
            "haystack_tags": ["point", "sensor", "temp"],
            "unit": "°C",
            "kind": "Number",
        }],
    }


def _projection_fixture(equipment: int, points: int, building_id: str) -> dict[str, Any]:
    equips = [{"id": PROBE_EQUIP, "equipmentId": PROBE_EQUIP, "tags": ["equip"]} for _ in range(equipment)]
    pts = [{
        "id": PROBE_POINT,
        "pointId": PROBE_POINT,
        "equipmentId": PROBE_EQUIP,
        "column": "SYN_COL",
        "tags": ["point", "sensor"],
        "unit": "°C",
        "kind": "Number",
    } for _ in range(points)]
    return {
        "ok": True,
        "schema": UI_SCHEMA,
        "site": {"id": building_id, "name": building_id},
        "equips": equips,
        "devices": [],
        "points": pts,
        "equipment_count": equipment,
        "point_count": points,
        "query_engine": "static_ui_model_sparql_v1",
    }


def _resolve_central_bin() -> Path | None:
    env = os.environ.get("OPENFDD_CENTRAL_BIN", "").strip()
    if env:
        path = Path(env)
        return path if path.is_file() else None
    found = shutil.which("openfdd-central")
    return Path(found) if found else None


class _CentralProbe:
    def __init__(self, bin_path: Path) -> None:
        self.bin_path = bin_path
        self.workspace = Path(tempfile.mkdtemp(prefix="openfdd-static-model-probe-"))
        self.port = 0
        self.proc: subprocess.Popen[Any] | None = None
        self.sql_rules = ROOT / "sql_rules"

    def start(self) -> None:
        if self.proc is not None:
            return
        import socket

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = int(sock.getsockname()[1])
        sock.close()
        if self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({
            "OPENFDD_CENTRAL_HOST": "127.0.0.1",
            "OPENFDD_CENTRAL_PORT": str(self.port),
            "OPENFDD_MQTT_ENABLED": "0",
            "OPENFDD_WORKSPACE": str(self.workspace),
            "OPENFDD_SQL_RULES_DIR": str(self.sql_rules),
        })
        self.proc = subprocess.Popen(
            [str(self.bin_path)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/api/health", timeout=2
                ) as resp:
                    if resp.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        raise RuntimeError("central did not become ready for static model probe")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait(timeout=30)
            self.proc = None
        shutil.rmtree(self.workspace, ignore_errors=True)

    def seed_building(self) -> None:
        root = self.workspace / "data" / "csv_buildings" / PROBE_BUILDING
        root.mkdir(parents=True, exist_ok=True)
        meta_path = root / "semantic_meta.json"
        meta_path.write_text(json.dumps(_probe_meta(PROBE_BUILDING), indent=2) + "\n", encoding="utf-8")

    def projection_counts(self) -> tuple[int, int]:
        url = (
            f"http://127.0.0.1:{self.port}/api/model/projection"
            f"?building_id={PROBE_BUILDING}"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("schema") != UI_SCHEMA:
            raise ValueError("projection schema mismatch")
        equip = body.get("equipment_count")
        points = body.get("point_count")
        if type(equip) is not int or type(points) is not int:
            raise ValueError("projection missing equipment_count/point_count")
        return equip, points


def parse_with_node(
    ttl: str,
    *,
    projection: dict[str, Any],
    live_base: str = "",
) -> dict[str, Any]:
    if not TTL_MODEL.is_file():
        raise FileNotFoundError(f"static UI ttl-model module missing: {TTL_MODEL}")
    payload = {
        "buildingId": PROBE_BUILDING,
        "ttl": ttl,
        "projection": projection,
        "liveBase": live_base,
    }
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_PROGRAM, TTL_MODEL.as_uri()],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode:
        raise RuntimeError(f"node ttl-model exited {proc.returncode}: {proc.stderr.strip()[:400]}")
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("ttl-model emitted malformed JSON") from exc
    proj = raw.get("projection") or {}
    ttl_side = raw.get("load_from_ttl") or {}
    equip = proj.get("equipment")
    points = proj.get("points")
    ttl_equip = ttl_side.get("equipment")
    ttl_points = ttl_side.get("points")
    if (
        type(equip) is not int
        or type(points) is not int
        or equip != ttl_equip
        or points != ttl_points
    ):
        raise ValueError("loadModelProjection and loadModelFromTtl disagree on counts")
    return {"equipment": equip, "points": points}


def evaluate_cases(
    cases: list[dict[str, Any]],
    parser: Callable[[str], Any],
    *,
    central: Callable[[], tuple[int, int] | None] | None = None,
) -> dict[str, Any]:
    if not isinstance(cases, list) or not cases:
        raise ValueError("at least one case is required")
    reference = _parse_turtle(cases[0].get("ttl"))
    expected_equipment, expected_points = _oracle_counts(reference)
    if (expected_equipment, expected_points) != (1, 1):
        raise ValueError("reference RDF must parse to exactly one equipment and one point")
    central_counts: tuple[int, int] | None = None
    if central is not None:
        central_counts = central()
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
        cent_equip = cent_points = None
        try:
            raw = parser(case["ttl"])
            if not isinstance(raw, dict):
                raise ValueError("candidate output must be an object")
            equip = raw.get("equipment")
            points = raw.get("points")
            if type(equip) is not int or type(points) is not int or equip < 0 or points < 0:
                raise ValueError("candidate equipment/points must be non-negative integers")
            if central_counts is not None:
                cent_equip, cent_points = central_counts
                if equip != cent_equip or points != cent_points:
                    raise ValueError(
                        f"JS counts {equip}/{points} != central projection {cent_equip}/{cent_points}"
                    )
        except Exception as exc:
            equip = points = None
            error = f"{type(exc).__name__}: {exc}"
        passed = (
            equivalent
            and (case_equipment, case_points) == (1, 1)
            and equip == case_equipment
            and points == case_points
            and (
                central_counts is None
                or (cent_equip == case_equipment and cent_points == case_points)
            )
        )
        results.append(CaseResult(
            name=name,
            rdf_isomorphic=equivalent,
            expected_equipment=case_equipment,
            expected_points=case_points,
            candidate_equipment=equip,
            candidate_points=points,
            central_equipment=cent_equip,
            central_points=cent_points,
            status="PASS" if passed else "FAIL",
            error=error,
        ))
    passed = all(row.status == "PASS" for row in results)
    return {
        "schema": "openfdd_static_model_probe_v1",
        "scope": "RDF oracle + ttl-model.js projection client (+ optional live central GET /api/model/projection)",
        "case_count": len(results),
        "comparison_count": len(results),
        "status": "PASS" if passed else "FAIL",
        "pass": passed,
        "central_live": central_counts is not None,
        "cases": [asdict(row) for row in results],
    }


def probe_identity() -> dict[str, str]:
    return {
        "candidate_git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=30
        ).strip(),
        "ttl_model_sha256": hashlib.sha256(TTL_MODEL.read_bytes()).hexdigest(),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rdflib_version": rdflib.__version__,
        "node_version": subprocess.check_output(
            ["node", "--version"], text=True, timeout=30
        ).strip(),
    }


def default_parser_factory(central: _CentralProbe | None) -> Callable[[str], dict[str, int]]:
    live_base = f"http://127.0.0.1:{central.port}" if central else ""

    def parser(ttl: str) -> dict[str, int]:
        graph = _parse_turtle(ttl)
        equip, points = _oracle_counts(graph)
        projection = _projection_fixture(equip, points, PROBE_BUILDING)
        if central is not None:
            return parse_with_node(ttl, projection=projection, live_base=live_base)
        return parse_with_node(ttl, projection=projection, live_base="")

    return parser


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, help="JSON array of named {name, ttl} cases")
    ap.add_argument("--json-out", type=Path, help="Optional machine-readable result path")
    ap.add_argument(
        "--skip-central",
        action="store_true",
        help="Do not spawn openfdd-central even when the binary exists",
    )
    args = ap.parse_args(argv)
    central_ctx: _CentralProbe | None = None
    central_fn: Callable[[], tuple[int, int] | None] | None = None
    try:
        cases = DEFAULT_CASES if args.cases is None else json.loads(args.cases.read_text(encoding="utf-8"))
        bin_path = None if args.skip_central else _resolve_central_bin()
        if bin_path is not None:
            central_ctx = _CentralProbe(bin_path)
            central_ctx.start()
            central_ctx.seed_building()
            counts = central_ctx.projection_counts()
            central_fn = lambda: counts  # noqa: E731
        parser = default_parser_factory(central_ctx)
        result = evaluate_cases(cases, parser, central=central_fn)
    except Exception as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        if central_ctx is not None:
            central_ctx.stop()
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
