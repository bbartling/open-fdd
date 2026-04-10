"""
Brick TTL → column_map and equipment types for the AFDD platform.

**Dumbed way down:** your building model (Brick) lives in a **text graph file** (TTL).
The **rules engine** wants **spreadsheet column names** (``external_id`` on each point).
This helper reads the TTL once and says “Brick class X → use column Y” so the engine
can line up data without you hand-wiring every tag.

**VOLTTRON direction:** live BACnet values arrive on the **edge** (topics like
``devices/MyAHU/all``). You still keep **Brick + external_id** in the DB/TTL for
**what each point means**; ``volttron_bridge`` maps scrape paths → ``external_id``.
This module is only about that **Brick ↔ column** side.

SPARQL over the unified ``data_model.ttl`` (same file as the API graph). The PyPI
``open-fdd`` engine stays RDF-free; this module is **stack-only**.

Requires **rdflib** (monorepo ``pyproject.toml`` optional extra ``stack``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Union


def resolve_from_ttl(ttl_path: Union[str, Path]) -> Dict[str, str]:
    """
    Load Brick TTL and return column_map keyed by BRICK class names.

    Brick type + rdfs:label (external_id) are sufficient for the mapping.
    ofdd:mapsToRuleInput is optional and only used for disambiguation when
    multiple points share the same Brick class (e.g. two Valve_Command);
    when there is a single point per Brick class, Brick alone is used.

    Returns:
        Dict mapping Brick class names (and rule_input when present) to DataFrame
        column names (rdfs:label = external_id from the data model).
    """
    try:
        from rdflib import Graph
    except ImportError as e:
        raise ImportError(
            "rdflib required for Brick TTL resolution. Install stack dependencies "
            "(pip install -e \".[stack]\") or: pip install rdflib"
        ) from e

    g = Graph()
    g.parse(ttl_path, format="turtle")
    mapping: Dict[str, str] = {}

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
        rule_input = (
            str(row.rule_input).strip('"')
            if row.rule_input and str(row.rule_input).strip()
            else None
        )

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
    except ImportError as e:
        raise ImportError(
            "rdflib required for Brick TTL resolution. Install stack dependencies "
            "(pip install -e \".[stack]\") or: pip install rdflib"
        ) from e

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


class BrickTtlColumnMapResolver:
    """
    Default stack resolver: SPARQL over Brick TTL (``fdd-loop`` / ``run_fdd_loop``).
    Satisfies :class:`open_fdd.engine.column_map_resolver.ColumnMapResolver`.
    """

    def build_column_map(self, *, ttl_path: Path) -> Dict[str, str]:
        if ttl_path.exists():
            return dict(resolve_from_ttl(str(ttl_path)))
        return {}
