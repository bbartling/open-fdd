"""
Resolve open-fdd rule inputs from a Brick TTL model.

Queries the Brick model for ofdd:mapsToRuleInput and rdfs:label to build
{rule_input: csv_column} for RuleRunner.run(column_map=...).

Requires: pip install open-fdd[brick]  # or pip install rdflib
"""

from pathlib import Path
from typing import Dict, Optional

OFDD = "http://openfdd.local/ontology#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"


def resolve_from_ttl(ttl_path: str | Path) -> Dict[str, str]:
    """
    Load Brick TTL and return {rule_input: csv_column} from ofdd:mapsToRuleInput + rdfs:label.

    Returns:
        Dict mapping rule input names (e.g. "oat", "sat") to DataFrame column names
        (e.g. "OAT (°F)", "SAT (°F)") as defined by rdfs:label in the Brick model.
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

    # SPARQL: find points with ofdd:mapsToRuleInput and rdfs:label
    q = """
    PREFIX ofdd: <http://openfdd.local/ontology#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?rule_input ?label WHERE {
        ?point ofdd:mapsToRuleInput ?rule_input .
        ?point rdfs:label ?label .
    }
    """
    for row in g.query(q):
        rule_input = str(row.rule_input).strip('"')
        label = str(row.label).strip('"')
        mapping[rule_input] = label

    return mapping
