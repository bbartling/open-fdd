"""
Resolve open-fdd rule inputs from a Brick TTL model.

Returns column_map keyed by BRICK class names (e.g. Supply_Air_Temperature_Sensor)
for use with RuleRunner.run(column_map=...). When a Brick class appears multiple
times (e.g. two Valve_Command), uses composite key BrickClass|rule_input.

Requires: pip install open-fdd[brick]  # or pip install rdflib
"""

from pathlib import Path
from typing import Dict, Union

BRICK = "https://brickschema.org/schema/Brick#"
OFDD = "http://openfdd.local/ontology#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"


def resolve_from_ttl(ttl_path: Union[str, Path]) -> Dict[str, str]:
    """
    Load Brick TTL and return column_map keyed by BRICK class names.

    SPARQL-driven: Brick type + rdfs:label (external_id) provide the mapping.
    ofdd:mapsToRuleInput is optional (used for disambiguation when multiple
    points share the same Brick class).

    Returns:
        Dict mapping Brick class names (and rule_input when present) to DataFrame
        column names (rdfs:label = external_id from the data model).
    """
    try:
        from rdflib import Graph
    except ImportError:
        raise ImportError(
            "rdflib required for Brick resolution. Run: pip install open-fdd[brick]"
        ) from None

    g = Graph()
    g.parse(ttl_path, format="turtle")
    mapping: Dict[str, str] = {}

    # SPARQL: brick_type + rdfs:label. mapsToRuleInput optional for disambiguation.
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX ofdd: <http://openfdd.local/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?brick_class ?label ?rule_input WHERE {
        ?point a ?brick_type .
        FILTER(STRSTARTS(STR(?brick_type), STR(brick:)))
        BIND(REPLACE(STR(?brick_type), "https://brickschema.org/schema/Brick#", "") AS ?brick_class)
        ?point rdfs:label ?label .
        OPTIONAL { ?point ofdd:mapsToRuleInput ?rule_input . }
    }
    """
    rows = list(g.query(q))

    brick_counts: Dict[str, int] = {}
    for row in rows:
        bc = str(row.brick_class)
        brick_counts[bc] = brick_counts.get(bc, 0) + 1

    for row in rows:
        brick_class = str(row.brick_class)
        label = str(row.label).strip('"')
        rule_input = str(row.rule_input).strip('"') if row.rule_input and str(row.rule_input).strip() else None

        if brick_counts[brick_class] > 1 and rule_input:
            key = f"{brick_class}|{rule_input}"
        else:
            key = brick_class
        mapping[key] = label

        if rule_input:
            mapping[rule_input] = label

    return mapping


def get_equipment_types_from_ttl(ttl_path: Union[str, Path]) -> list:
    """
    Load Brick TTL and return list of equipment types (e.g. ["VAV_AHU", "AHU"]).
    Used to filter which rules apply to the equipment in the data model.
    """
    try:
        from rdflib import Graph
    except ImportError:
        raise ImportError(
            "rdflib required for Brick resolution. Run: pip install open-fdd[brick]"
        ) from None

    g = Graph()
    g.parse(ttl_path, format="turtle")
    types = []
    q = """
    PREFIX ofdd: <http://openfdd.local/ontology#>
    SELECT DISTINCT ?equipmentType WHERE {
        ?equipment ofdd:equipmentType ?equipmentType .
    }
    """
    for row in g.query(q):
        t = str(row.equipmentType).strip('"')
        if t and t not in types:
            types.append(t)
    return types
