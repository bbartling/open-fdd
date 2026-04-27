from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BrickService:
    ttl_path: Path

    def resolve_column_map(self) -> dict[str, str]:
        try:
            from rdflib import Graph
        except ImportError:
            return {}
        if not self.ttl_path.exists():
            return {}
        graph = Graph()
        graph.parse(self.ttl_path, format="turtle")
        query = """
        PREFIX brick: <https://brickschema.org/schema/Brick#>
        PREFIX ofdd: <http://openfdd.local/ontology#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?brickClass ?label ?ruleInput WHERE {
          ?p a ?b .
          FILTER(STRSTARTS(STR(?b), STR(brick:)))
          BIND(REPLACE(STR(?b), "https://brickschema.org/schema/Brick#", "") AS ?brickClass)
          ?p rdfs:label ?label .
          OPTIONAL { ?p ofdd:mapsToRuleInput ?ruleInput . }
        }
        """
        out: dict[str, str] = {}
        for row in graph.query(query):
            brick_class = str(getattr(row, "brickClass", "")).strip()
            label = str(getattr(row, "label", "")).strip()
            if brick_class and label:
                out[brick_class] = label
            rule_input = str(getattr(row, "ruleInput", "") or "").strip()
            if rule_input and label:
                out[rule_input] = label
        return out

    def equipment_types(self) -> list[str]:
        try:
            from rdflib import Graph
        except ImportError:
            return []
        if not self.ttl_path.exists():
            return []
        graph = Graph()
        graph.parse(self.ttl_path, format="turtle")
        query = """
        PREFIX ofdd: <http://openfdd.local/ontology#>
        SELECT DISTINCT ?t WHERE {
          ?e ofdd:equipmentType ?t .
        }
        """
        vals: list[str] = []
        for row in graph.query(query):
            t = str(getattr(row, "t", "")).strip()
            if t and t not in vals:
                vals.append(t)
        return vals

