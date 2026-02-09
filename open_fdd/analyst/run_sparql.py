#!/usr/bin/env python3
"""
Run SPARQL queries against the Brick TTL to test and inspect the data model.

Usage:
    python -m open_fdd.analyst.run_sparql
    python -m open_fdd.analyst.run_sparql --ttl data/brick_model.ttl sparql/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from open_fdd.analyst.config import AnalystConfig, default_analyst_config


def run_query(g, query_path: Path) -> bool:
    """Run a SPARQL file and print results. Returns True if OK."""
    try:
        from rdflib import Graph
    except ImportError:
        print("rdflib required. Run: pip install open-fdd[brick]")
        return False

    q = query_path.read_text(encoding="utf-8")
    lines = [l for l in q.splitlines() if l.strip() and not l.strip().startswith("#")]
    sparql = "\n".join(lines)

    try:
        rows = list(g.query(sparql))
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

    if not rows:
        print("  (no rows)")
        return True

    print(f"  {len(rows)} row(s):")
    for row in rows:
        parts = [str(v).strip('"') if v else "" for v in row]
        print(f"    | ".join(parts[:8]))
    return True


def run_sparql_main(
    ttl_path: Path | None = None,
    query_paths: list[Path] | None = None,
    config: AnalystConfig | None = None,
) -> int:
    """Run SPARQL queries. Returns exit code."""
    cfg = config or default_analyst_config()
    ttl = ttl_path or cfg.brick_ttl
    sparql_dir = cfg.sparql_dir

    if not ttl.exists():
        print(f"TTL not found: {ttl}")
        return 1

    try:
        from rdflib import Graph
    except ImportError:
        print("rdflib required. Run: pip install open-fdd[brick]")
        return 1

    g = Graph()
    g.parse(ttl, format="turtle")
    print(f"Loaded: {ttl} ({len(g)} triples)\n")

    if query_paths:
        paths = query_paths
    elif sparql_dir.exists():
        paths = sorted(sparql_dir.glob("*.sparql"))
    else:
        paths = []
    if not paths:
        print("No .sparql files found.")
        return 1

    ok = True
    for qp in sorted(paths):
        if qp.suffix != ".sparql" or not qp.exists():
            continue
        print(f"--- {qp.name} ---")
        if not run_query(g, qp):
            ok = False
        print()

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SPARQL against Brick TTL")
    cfg = default_analyst_config()
    parser.add_argument("--ttl", default=str(cfg.brick_ttl), help="Path to Brick TTL")
    parser.add_argument("queries", nargs="*", help=".sparql file(s) or directory")
    args = parser.parse_args()

    ttl_path = Path(args.ttl)
    query_paths = []
    for q in args.queries or [str(cfg.sparql_dir)]:
        p = Path(q)
        if p.is_dir():
            query_paths.extend(sorted(p.glob("*.sparql")))
        elif p.suffix == ".sparql" and p.exists():
            query_paths.append(p)

    return run_sparql_main(
        ttl_path=ttl_path, query_paths=query_paths or None, config=cfg
    )


if __name__ == "__main__":
    sys.exit(main())
