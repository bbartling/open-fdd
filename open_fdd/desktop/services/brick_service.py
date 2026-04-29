from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import warnings


@dataclass
class BrickService:
    ttl_path: Path

    @staticmethod
    def _safe_query(graph: Any, query: str) -> list[Any]:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="'count' is passed as positional argument",
                category=DeprecationWarning,
            )
            return list(graph.query(query))

    def resolve_column_map(self) -> dict[str, str]:
        """
        Resolve BRICK/fdd_input keys to point labels.
        Note: mapping is last-write-wins for duplicate keys.
        """
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
        SELECT ?brick_class ?label ?rule_input WHERE {
          ?p a ?b .
          FILTER(STRSTARTS(STR(?b), STR(brick:)))
          BIND(REPLACE(STR(?b), "https://brickschema.org/schema/Brick#", "") AS ?brick_class)
          ?p rdfs:label ?label .
          OPTIONAL { ?p ofdd:mapsToRuleInput ?rule_input . }
        }
        ORDER BY ?brick_class ?rule_input ?label
        """
        out: dict[str, str] = {}
        rows = self._safe_query(graph, query)
        for row in rows:
            row_map = row.asdict() if hasattr(row, "asdict") else {}
            brick_class = str(row_map.get("brick_class") or getattr(row, "brick_class", "")).strip()
            label = str(row_map.get("label") or getattr(row, "label", "")).strip()
            if brick_class and label:
                out[brick_class] = label
            rule_input = str(row_map.get("rule_input") or getattr(row, "rule_input", "") or "").strip()
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
        rows = self._safe_query(graph, query)
        for row in rows:
            t = str(getattr(row, "t", "")).strip()
            if t and t not in vals:
                vals.append(t)
        return vals

