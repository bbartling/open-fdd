"""
Test raw SPARQL against the Brick model.

Run this to verify the Brick TTL structure before running fault detection.
If this works, the Brick model is valid for open-fdd.

Usage:
    python examples/test_sparql.py
    python examples/test_sparql.py --ttl brick_model.ttl
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Test SPARQL against Brick TTL")
    parser.add_argument("--ttl", default="brick_model.ttl", help="Path to Brick TTL")
    args = parser.parse_args()

    ttl_path = _script_dir / args.ttl
    if not ttl_path.exists():
        print(f"TTL not found: {ttl_path}")
        return 1

    try:
        from rdflib import Graph
    except ImportError:
        print("rdflib required. Run: pip install open-fdd[brick]")
        return 1

    g = Graph()
    g.parse(ttl_path, format="turtle")

    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX ofdd: <http://openfdd.local/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?point ?brick_class ?label ?rule_input WHERE {
        ?point ofdd:mapsToRuleInput ?rule_input .
        ?point a ?brick_type .
        FILTER(STRSTARTS(STR(?brick_type), STR(brick:)))
        BIND(REPLACE(STR(?brick_type), "https://brickschema.org/schema/Brick#", "") AS ?brick_class)
        ?point rdfs:label ?label .
    }
    LIMIT 10
    """
    rows = list(g.query(q))
    if not rows:
        print("No rows returned. Check Brick TTL structure (ofdd:mapsToRuleInput, rdfs:label).")
        return 1

    def _safe(s: str) -> str:
        return s.encode("ascii", "replace").decode() if s else ""

    print(f"SPARQL OK. Sample rows ({len(rows)}):")
    for row in rows:
        bc = str(row.brick_class)
        lbl = str(row.label).strip('"')
        ri = str(row.rule_input).strip('"')
        print(f"  {bc} | {_safe(lbl)} | {ri}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
