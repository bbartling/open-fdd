"""``open-fdd-rca``: advisory graph-based HVAC root-cause analysis over RDF topology.

Examples::

    open-fdd-rca --example --print md
    open-fdd-rca --graph site.ttl --results rule_results.csv --out-dir rca_out
    open-fdd-rca --graph site.ttl --episodes confidence_out/episodes.jsonl --out-dir rca_out
    open-fdd-rca --from-nf --episodes confidence_out/episodes.jsonl --out-dir rca_out
    open-fdd-rca --graph site.ttl --sqlite fdd.db --out-dir rca_out

Advisory only: reads topology and FDD/confidence outputs and writes ``rca_report.json``
and ``rca_report.md``. Never changes rules, tuners, tags, or setpoints.
"""

from __future__ import annotations

import argparse
import sys
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from open_fdd.rca.evidence import (
    DataFrameEvidenceCollector,
    FaultEvidence,
    InMemoryEvidenceCollector,
    PointDeviation,
    SqlEvidenceCollector,
    parse_utc,
)
from open_fdd.rca.graph import load_graph, load_graph_from_nf
from open_fdd.rca.infer import (
    InferredEdge,
    infer_topology,
    load_telemetry_csv,
    load_telemetry_sql,
    suggested_links_to_csv,
    suggested_links_to_ttl,
)
from open_fdd.rca.rank import analyze_rca
from open_fdd.rca.report import report_to_json, report_to_markdown

DESCRIPTION = (
    "Trace downstream HVAC fault symptoms upstream through Brick, ASHRAE 223P, and Haystack RDF "
    "relationships to rank likely root causes (JSON + Markdown). Advisory only."
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="open-fdd-rca",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = ap.add_argument_group("topology source")
    src.add_argument("--graph", type=Path, help="Site RDF/Turtle model file (.ttl)")
    src.add_argument("--from-nf", action="store_true", help="Fetch Turtle model from a Normal Framework rdf hook")
    src.add_argument("--nf-url", help="NF URL (else NF_URL / NFURL / NF_LAN_URL)")
    src.add_argument("--env", help="KEY=VALUE env file for the NF client")
    src.add_argument("--app", choices=("full", "lite"), default="full")
    src.add_argument("--infer-topology", action="store_true", help="Opt-in read-only topology inference from telemetry + tags (discounted, never written back)")
    src.add_argument("--history-csv", type=Path, help="Wide or long telemetry CSV for --infer-topology")
    src.add_argument("--suggest-links-ttl", type=Path, help="Optional path to write proposed 223P connection Turtle for human review")
    src.add_argument("--suggest-links-csv", type=Path, help="Optional path to write proposed 223P connection CSV for human review")
    src.add_argument("--infer-min-corr", type=float, default=0.50, help="Min |correlation| for --infer-topology (default 0.50)")
    src.add_argument("--infer-max-lag", type=int, default=3, help="Max positive lag steps for --infer-topology (default 3)")
    src.add_argument("--infer-min-samples", type=int, default=24, help="Min aligned samples for --infer-topology (default 24)")

    ev = ap.add_argument_group("fault & evidence input")
    ev.add_argument("--results", type=Path, help="CSV of Open-FDD rule_result or long-format fault flags")
    ev.add_argument("--episodes", type=Path, help="Hand-authored episodes.jsonl, episodes.csv, or report.json (not produced by the open-fdd-ml CLI)")
    ev.add_argument("--deviations", type=Path, help="Optional CSV of SI point deviations (equipment_id, role, value_si, setpoint_si, unit)")
    ev.add_argument("--dq", type=Path, help="Optional CSV of data-quality warnings (equipment_id, flag, point_id, detail)")
    ev.add_argument("--sqlite", type=Path, help="SQLite database of rule results (read-only)")
    ev.add_argument("--duckdb", type=Path, help="DuckDB database of rule results (read-only; pip install duckdb)")
    ev.add_argument("--layout", choices=("results", "flags"), default="results")
    ev.add_argument("--table", help="Rule output table (default rule_result, or fdd.rule_result on DuckDB)")
    ev.add_argument("--map", action="append", default=[], metavar="NAME=COLUMN", help="Rename a rule-output column, e.g. --map equipment_id=equip")
    ev.add_argument("--history-table", help="SI history table for deviations (default input_sample / fdd.input_sample when confidence_sql is present)")
    ev.add_argument("--point-table", help="Point table joined for equipment_id (default point / fdd.point); '' if history has equipment_id")
    ev.add_argument("--history-map", action="append", default=[], metavar="NAME=COLUMN", help="Rename a history column (ts, point_key, value, ...)")
    ev.add_argument("--no-history", action="store_true", help="Skip SI history deviations when reading a database")
    ev.add_argument("--example", action="store_true", help="Run on the shipped synthetic plant fixture and sample faults")

    flt = ap.add_argument_group("filtering & output")
    flt.add_argument("--symptom-equip", help="Focus on one downstream symptom equipment id or label")
    flt.add_argument("--symptom-rule", help="Focus on one symptom rule id")
    flt.add_argument("--site", help="Scope topology and faults to one site id")
    flt.add_argument("--top", type=int, default=5, help="Top candidate causes per symptom (default 5)")
    flt.add_argument("--out-dir", type=Path, default=None, help="Directory to write rca_report.json and rca_report.md")
    flt.add_argument("--print", dest="print_format", choices=("json", "md", "none"), default="json")
    return ap


def _read_csv_dicts(path: Path) -> list[dict[str, Any]]:
    import csv

    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _example_collector() -> InMemoryEvidenceCollector:
    faults = [
        FaultEvidence(
            equipment_id="ahu-1",
            rule_id="SAT-HIGH",
            start=parse_utc("2026-11-24T10:00:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.92,
            p_false_positive=0.04,
            confidence_label="likely_real",
        ),
        FaultEvidence(
            equipment_id="vav-1",
            rule_id="AIRFLOW-LOW",
            start=parse_utc("2026-11-24T10:10:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.10,
            p_false_positive=0.86,
            confidence_label="likely_false_positive",
        ),
        FaultEvidence(
            equipment_id="zone-1",
            rule_id="ZNT-HIGH",
            start=parse_utc("2026-11-24T10:15:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.88,
            p_false_positive=0.06,
            confidence_label="likely_real",
        ),
        FaultEvidence(
            equipment_id="zone-2",
            rule_id="ZNT-HIGH",
            start=parse_utc("2026-11-24T10:20:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.85,
            p_false_positive=0.08,
            confidence_label="likely_real",
        ),
        FaultEvidence(
            equipment_id="zone-unlinked",
            rule_id="ZNT-HIGH",
            start=parse_utc("2026-11-24T10:25:00Z"),
            end=parse_utc("2026-11-24T12:00:00Z"),
            p_real=0.80,
            p_false_positive=0.10,
            confidence_label="likely_real",
        ),
    ]
    devs = [
        PointDeviation(
            equipment_id="ahu-1",
            role="discharge-air-temp",
            value_si=18.5,
            setpoint_si=13.0,
            unit="degC",
            timestamp=parse_utc("2026-11-24T10:30:00Z"),
        )
    ]
    return InMemoryEvidenceCollector(faults=faults, point_deviations=devs)



def _sql_relation_exists(conn: Any, name: str) -> bool:
    """True when ``name`` can be queried (schema.table or table)."""
    if not name or not all(ch.isalnum() or ch in ("_", ".") for ch in name):
        return False
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {name} WHERE 1=0")
    except (OSError, RuntimeError, ValueError, AttributeError):
        return False
    except Exception as exc:  # driver-specific missing-relation errors (sqlite3, duckdb, ...)
        if exc.__class__.__name__ in {"ProgrammingError", "OperationalError", "CatalogException", "BinderException", "Error"}:
            return False
        raise
    return True


def _kv(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"--map expects NAME=COLUMN, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _open_sql_collector(args: argparse.Namespace) -> tuple[SqlEvidenceCollector, Any, str]:
    import sqlite3

    if args.sqlite:
        path = Path(args.sqlite)
        if not path.is_file():
            raise FileNotFoundError(f"no SQLite database at {path}")
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        engine = "sqlite"
        default_table = args.table or "rule_result"
        default_point = "point"
    elif args.duckdb:
        import duckdb

        path = Path(args.duckdb)
        if not path.is_file():
            raise FileNotFoundError(f"no DuckDB database at {path}")
        conn = duckdb.connect(str(path), read_only=True)
        engine = "duckdb"
        default_table = args.table or "fdd.rule_result"
        default_point = "fdd.point"
    else:
        raise ValueError("pick --sqlite or --duckdb")
    if args.no_history:
        history_table = None
    elif args.history_table:
        if not _sql_relation_exists(conn, args.history_table):
            conn.close()
            raise ValueError(f"history table {args.history_table!r} not found")
        history_table = args.history_table
    else:
        candidate = "fdd.input_sample" if engine == "duckdb" else "input_sample"
        history_table = candidate if _sql_relation_exists(conn, candidate) else None
    point_table = args.point_table
    if history_table and point_table is None:
        point_table = default_point
    collector = SqlEvidenceCollector(
        conn,
        table=default_table,
        layout=args.layout,
        columns=_kv(args.map),
        history_table=history_table,
        point_table=point_table,
        history_columns=_kv(args.history_map),
    )
    return collector, conn, engine


def run(args: argparse.Namespace) -> int:
    if args.example:
        data = files("open_fdd.rca").joinpath("data")
        with as_file(data.joinpath("example_plant.ttl")) as ttl_path:
            graph = load_graph(Path(ttl_path))
        collector = _example_collector()
        source_meta: dict[str, Any] = {"mode": "example"}
    else:
        if args.from_nf:
            # TODO(5.0.22): also allow fetching fdd.rule_result / point deviations directly via NF client/hook.
            graph = load_graph_from_nf(url=args.nf_url, env_file=args.env, app=args.app)
            source_meta = {"topology": "nf_rdf_hook", "app": args.app}
        elif args.graph is not None:
            graph = load_graph(args.graph)
            source_meta = {"topology": str(args.graph)}
        else:
            raise ValueError("Provide --graph, --from-nf, or --example")

        devs = _read_csv_dicts(args.deviations) if args.deviations else None
        dq = _read_csv_dicts(args.dq) if args.dq else None
        if args.episodes is not None:
            collector = DataFrameEvidenceCollector.from_confidence_episodes(args.episodes, deviations=devs, data_quality=dq)
            source_meta["evidence"] = str(args.episodes)
        elif args.results is not None:
            collector = DataFrameEvidenceCollector.from_rule_results(_read_csv_dicts(args.results), deviations=devs, data_quality=dq)
            source_meta["evidence"] = str(args.results)
        elif args.sqlite or args.duckdb:
            sql_collector, sql_conn, engine = _open_sql_collector(args)
            try:
                collector = sql_collector.load(site_id=args.site)
            finally:
                sql_conn.close()
            if devs or dq:
                from open_fdd.rca.evidence import _parse_deviation_rows, _parse_dq_rows

                collector = DataFrameEvidenceCollector(
                    faults=collector.all_faults(),
                    data_quality_flags=list(collector.all_data_quality()) + _parse_dq_rows(dq),
                    point_deviations=list(collector.all_deviations()) + _parse_deviation_rows(devs),
                )
            source_meta["evidence"] = engine
        else:
            raise ValueError("Provide --results, --episodes, --sqlite, --duckdb, or --example")

    inferred_edges: list[InferredEdge] = []
    if getattr(args, "infer_topology", False) and not args.example:
        telemetry: dict[str, Any] = {}
        if getattr(args, "history_csv", None) is not None:
            telemetry = load_telemetry_csv(args.history_csv, site_id=args.site)
        elif args.sqlite or args.duckdb:
            sql_collector, sql_conn, engine = _open_sql_collector(args)
            try:
                if args.history_table:
                    htable = args.history_table
                    if not _sql_relation_exists(sql_conn, htable):
                        raise ValueError(f"history table {htable!r} not found")
                else:
                    candidate = "fdd.input_sample" if engine == "duckdb" else "input_sample"
                    htable = candidate if _sql_relation_exists(sql_conn, candidate) else None
                if htable:
                    telemetry = load_telemetry_sql(
                        sql_conn,
                        history_table=htable,
                        columns=_kv(args.history_map),
                        site_id=args.site,
                    )
            finally:
                sql_conn.close()
        infer_skip = None
        if telemetry:
            inferred_edges = infer_topology(
                graph,
                telemetry,
                site_id=args.site,
                min_correlation=args.infer_min_corr,
                max_lag=args.infer_max_lag,
                min_samples=args.infer_min_samples,
            )
            graph = graph.with_inferred_edges(inferred_edges)
        elif not getattr(args, "history_csv", None) and (args.sqlite or args.duckdb):
            infer_skip = "inference skipped: no history telemetry table was available"
            print(f"warning: {infer_skip}", file=sys.stderr)
        elif getattr(args, "history_csv", None) or args.sqlite or args.duckdb:
            infer_skip = "inference skipped: no telemetry rows were loaded"
            print(f"warning: {infer_skip}", file=sys.stderr)
        source_meta["inferred_topology"] = {
            "enabled": True,
            "proposed_edges": len(inferred_edges),
            "edges": [
                {
                    "upstream": e.upstream_label,
                    "downstream": e.downstream_label,
                    "confidence": e.confidence,
                    "status": "inferred, not modeled",
                }
                for e in inferred_edges
            ],
        }
        if infer_skip:
            source_meta["inferred_topology"]["skipped"] = infer_skip

    report = analyze_rca(
        graph,
        collector,
        symptom_equip=args.symptom_equip,
        symptom_rule=args.symptom_rule,
        site_id=args.site,
        top=args.top,
    )
    json_text = report_to_json(report, source=source_meta)
    md_text = report_to_markdown(report)

    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "rca_report.json").write_text(json_text + "\n", encoding="utf-8")
        (args.out_dir / "rca_report.md").write_text(md_text, encoding="utf-8")
        if getattr(args, "infer_topology", False):
            (args.out_dir / "suggested_links.ttl").write_text(suggested_links_to_ttl(inferred_edges), encoding="utf-8")
            (args.out_dir / "suggested_links.csv").write_text(suggested_links_to_csv(inferred_edges), encoding="utf-8")
    if getattr(args, "suggest_links_ttl", None) is not None:
        args.suggest_links_ttl.parent.mkdir(parents=True, exist_ok=True)
        args.suggest_links_ttl.write_text(suggested_links_to_ttl(inferred_edges), encoding="utf-8")
    if getattr(args, "suggest_links_csv", None) is not None:
        args.suggest_links_csv.parent.mkdir(parents=True, exist_ok=True)
        args.suggest_links_csv.write_text(suggested_links_to_csv(inferred_edges), encoding="utf-8")

    if args.print_format == "json":
        print(json_text)
    elif args.print_format == "md":
        print(md_text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())