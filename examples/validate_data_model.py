"""
Validate Brick data model and YAML rules before running fault detection.

Prerequisites before running fault equations:
1. Brick TTL parses and contains expected equipment types
2. All rule inputs required by applicable rules are mapped to CSV columns
3. Optional: run raw SPARQL against the model to verify queries work

Usage:
    python validate_data_model.py
    python validate_data_model.py --ttl brick_model.ttl --rules my_rules
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add examples to path for brick_resolver
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))


def _load_rules(rules_dir: Path) -> list[dict]:
    """Load all YAML rules from directory."""
    import yaml
    rules = []
    for f in sorted(rules_dir.glob("*.yaml")):
        with open(f, encoding="utf-8") as fp:
            rules.append(yaml.safe_load(fp))
    return rules


def _get_required_inputs(rule: dict) -> list[tuple[str, str, str]]:
    """Return list of (input_name, brick_class, column) for each rule input."""
    out = []
    for key, val in rule.get("inputs", {}).items():
        if isinstance(val, str):
            out.append((key, key, val))
        elif isinstance(val, dict):
            brick = val.get("brick", key)
            col = val.get("column", key)
            out.append((key, brick, col))
    return out


def validate_brick_model(ttl_path: Path) -> tuple[dict[str, str], list[str], list[str]]:
    """
    Validate Brick TTL and return (column_map, equipment_types, errors).
    """
    from open_fdd.engine.brick_resolver import resolve_from_ttl, get_equipment_types_from_ttl

    errors = []
    column_map = {}
    equipment_types = []

    if not ttl_path.exists():
        errors.append(f"Brick TTL not found: {ttl_path}")
        return column_map, equipment_types, errors

    try:
        column_map = resolve_from_ttl(ttl_path)
        equipment_types = get_equipment_types_from_ttl(ttl_path)
    except Exception as e:
        errors.append(f"Failed to load Brick TTL: {e}")
        return column_map, equipment_types, errors

    if not column_map:
        errors.append("Brick TTL produced empty column map (no points with ofdd:mapsToRuleInput)")

    return column_map, equipment_types, errors


def validate_rules_against_model(
    rules: list[dict],
    column_map: dict[str, str],
    equipment_types: list[str],
) -> list[str]:
    """
    Check that all rule inputs required by applicable rules are mapped.
    Returns list of error messages.
    """
    errors = []

    for rule in rules:
        rule_types = rule.get("equipment_type")
        if rule_types and equipment_types:
            # Rule is equipment-specific; only validate if model has matching equipment
            if not any(rt in equipment_types for rt in rule_types):
                continue  # Skip rule, not applicable
        # Rule applies (no equipment_type) or equipment matches
        for inp_name, brick_class, col in _get_required_inputs(rule):
            resolved = (
                column_map.get(brick_class)
                or column_map.get(f"{brick_class}|{col}")
                or column_map.get(col)
                or column_map.get(inp_name)
            )
            if not resolved:
                errors.append(
                    f"Rule '{rule.get('name', '?')}' input '{inp_name}' "
                    f"(brick={brick_class}, col={col}) has no mapping in Brick model"
                )

    return errors


def run_sparql_test(ttl_path: Path) -> list[str]:
    """
    Run a simple SPARQL query against the Brick model to verify it works.
    Returns list of error messages (empty if OK).
    """
    errors = []
    try:
        from rdflib import Graph
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
        } LIMIT 5
        """
        rows = list(g.query(q))
        if not rows:
            errors.append("SPARQL test query returned no rows (check Brick TTL structure)")
    except Exception as e:
        errors.append(f"SPARQL test failed: {e}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Brick data model and YAML rules")
    parser.add_argument("--ttl", default="brick_model.ttl", help="Path to Brick TTL")
    parser.add_argument("--rules", default="my_rules", help="Path to rules directory")
    args = parser.parse_args()

    ttl_path = _script_dir / args.ttl
    rules_dir = _script_dir / args.rules

    print("=== Brick Data Model Validation ===\n")
    print(f"TTL: {ttl_path}")
    print(f"Rules: {rules_dir}\n")
    print("Validates: Can open-fdd run your rules against your CSV using this Brick model?\n")

    # 1. SPARQL prereq
    print("1. SPARQL test (prereq)")
    print("   Checks: TTL parses; points have ofdd:mapsToRuleInput + rdfs:label (Brick->CSV mapping)")
    sparql_errors = run_sparql_test(ttl_path)
    if sparql_errors:
        for e in sparql_errors:
            print(f"   ERROR: {e}")
    else:
        print("   OK\n")

    # 2. Brick model
    print("2. Brick model (column map, equipment types)")
    print("   Checks: Resolved Brick class -> CSV column; equipment_type for rule filtering")
    column_map, equipment_types, model_errors = validate_brick_model(ttl_path)
    if model_errors:
        for e in model_errors:
            print(f"   ERROR: {e}")
    else:
        print(f"   Column map: {len(column_map)} mappings (Brick class -> CSV column)")
        print(f"   Equipment types: {equipment_types or ['(none)']}\n")

    # 3. Rules vs model
    if not rules_dir.is_dir():
        print(f"3. Rules vs model — dir not found: {rules_dir}")
        return 1

    rules = _load_rules(rules_dir)
    print("3. Rules vs model")
    print(f"   Checks: Each rule input (brick class) has a mapping; {len(rules)} rules loaded")
    rule_errors = validate_rules_against_model(rules, column_map, equipment_types)
    if rule_errors:
        for e in rule_errors:
            print(f"   ERROR: {e}")
    else:
        print("   All applicable rule inputs mapped\n")

    # 4. Optional: Brick schema validation (SHACL) — warning only, does not fail validation
    try:
        from brickschema import Graph as BrickGraph
        print("4. Brick schema (SHACL) — optional")
        print("   Checks: TTL conforms to Brick ontology (classes, relationships); SHACL shapes")
        g = BrickGraph(load_brick=True)
        g.load_file(str(ttl_path))
        valid, _, report = g.validate()
        if not valid:
            print("   WARN: Brick schema violations (open-fdd may still run):")
            for line in str(report).splitlines()[:8]:
                print(f"      {line}")
        else:
            print("   OK\n")
    except ImportError:
        print("4. Brick schema (SHACL) - skipped (pip install brickschema to validate ontology)\n")

    all_errors = sparql_errors + model_errors + rule_errors
    if all_errors:
        print("=== VALIDATION FAILED ===\n")
        return 1

    print("=== VALIDATION PASSED ===\n")
    print("Data model and rules are ready. Run: python run_all_rules_brick.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
