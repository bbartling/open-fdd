"""Predefined BRICK SPARQL catalog and read-only ad-hoc execution for the Data Model tab."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from .ttl_graph import TtlGraphError, load_graph, run_sparql
from .ttl_service import TtlService

BRICK = "https://brickschema.org/schema/Brick#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OFDD = "http://openfdd.local/ontology#"

MAX_SPARQL_ROWS = 5000

_FORBIDDEN_FORMS = frozenset(
    {
        "INSERT",
        "DELETE",
        "UPDATE",
        "LOAD",
        "CLEAR",
        "DROP",
        "CREATE",
        "MOVE",
        "COPY",
        "ADD",
    }
)
_READONLY_FORMS = frozenset({"SELECT", "ASK", "DESCRIBE", "CONSTRUCT"})


def _equipment_points_with_bacnet(equipment_type: str) -> str:
    return f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {{
  ?equipment a brick:{equipment_type} .
  OPTIONAL {{ ?equipment rdfs:label ?equipment_label . }}
  ?point brick:isPointOf ?equipment .
  OPTIONAL {{ ?point rdfs:label ?point_label . }}
  OPTIONAL {{ ?point ofdd:bacnetDeviceId ?bacnet_device_id . }}
  OPTIONAL {{ ?point ofdd:objectIdentifier ?object_identifier . }}
}}
ORDER BY ?equipment ?point"""


PREDEFINED_QUERIES: list[dict[str, Any]] = [
    {
        "id": "sites",
        "label": "List sites",
        "short_label": "Sites",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
SELECT ?site ?site_label WHERE {{
  ?site a brick:Site .
  OPTIONAL {{ ?site rdfs:label ?site_label }}
}}""",
        "query_with_bacnet": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?site ?site_label ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {{
  ?site a brick:Site .
  OPTIONAL {{ ?site rdfs:label ?site_label . }}
  ?equipment brick:isPartOf ?site .
  OPTIONAL {{ ?equipment rdfs:label ?equipment_label . }}
  ?point brick:isPointOf ?equipment .
  OPTIONAL {{ ?point rdfs:label ?point_label . }}
  OPTIONAL {{ ?point ofdd:bacnetDeviceId ?bacnet_device_id . }}
  OPTIONAL {{ ?point ofdd:objectIdentifier ?object_identifier . }}
}}
ORDER BY ?site ?equipment ?point""",
    },
    {
        "id": "ahu_information",
        "label": "Count Air Handling Units",
        "short_label": "AHUs",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(?ahu) AS ?count) WHERE {{
  ?ahu a brick:Air_Handling_Unit .
}}""",
        "query_with_bacnet": _equipment_points_with_bacnet("Air_Handling_Unit"),
    },
    {
        "id": "zone_information",
        "label": "Count zones",
        "short_label": "Zones",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(?z) AS ?count) WHERE {{
  ?z a brick:HVAC_Zone .
}}""",
        "query_with_bacnet": _equipment_points_with_bacnet("HVAC_Zone"),
    },
    {
        "id": "building_information",
        "label": "Building and HVAC counts",
        "short_label": "Building",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(DISTINCT ?b) AS ?buildings) (COUNT(DISTINCT ?f) AS ?floors) (COUNT(DISTINCT ?e) AS ?hvac_equipment) (COUNT(DISTINCT ?z) AS ?zones) WHERE {{
  OPTIONAL {{ ?b a brick:Building . }}
  OPTIONAL {{ ?f a brick:Floor . }}
  OPTIONAL {{ ?e a brick:HVAC_Equipment . }}
  OPTIONAL {{ ?z a brick:HVAC_Zone . }}
}}""",
        "query_with_bacnet": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {{
  ?equipment a brick:HVAC_Equipment .
  OPTIONAL {{ ?equipment rdfs:label ?equipment_label . }}
  ?point brick:isPointOf ?equipment .
  OPTIONAL {{ ?point rdfs:label ?point_label . }}
  OPTIONAL {{ ?point ofdd:bacnetDeviceId ?bacnet_device_id . }}
  OPTIONAL {{ ?point ofdd:objectIdentifier ?object_identifier . }}
}}
ORDER BY ?equipment ?point""",
    },
    {
        "id": "count-vavs",
        "label": "Count VAV boxes",
        "short_label": "VAV boxes",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(?vav) AS ?count) WHERE {{
  {{ ?vav a brick:Variable_Air_Volume_Box . }}
  UNION
  {{ ?vav a brick:Variable_Air_Volume_Box_With_Reheat . }}
}}""",
        "query_with_bacnet": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {{
  {{ ?equipment a brick:Variable_Air_Volume_Box . }}
  UNION
  {{ ?equipment a brick:Variable_Air_Volume_Box_With_Reheat . }}
  OPTIONAL {{ ?equipment rdfs:label ?equipment_label . }}
  ?point brick:isPointOf ?equipment .
  OPTIONAL {{ ?point rdfs:label ?point_label . }}
  OPTIONAL {{ ?point ofdd:bacnetDeviceId ?bacnet_device_id . }}
  OPTIONAL {{ ?point ofdd:objectIdentifier ?object_identifier . }}
}}
ORDER BY ?equipment ?point""",
    },
    {
        "id": "number_of_vav_boxes_per_ahu",
        "label": "VAV boxes per AHU",
        "short_label": "VAVs per AHU",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT ?ahu (COUNT(?vav) AS ?vav_count) WHERE {{
  ?ahu a brick:Air_Handling_Unit .
  ?vav brick:isPartOf ?ahu .
  {{ ?vav a brick:Variable_Air_Volume_Box . }} UNION {{ ?vav a brick:Variable_Air_Volume_Box_With_Reheat . }}
}} GROUP BY ?ahu
ORDER BY DESC(?vav_count)""",
        "query_with_bacnet": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?ahu ?ahu_label ?vav ?vav_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {{
  ?ahu a brick:Air_Handling_Unit .
  OPTIONAL {{ ?ahu rdfs:label ?ahu_label . }}
  ?vav brick:isPartOf ?ahu .
  {{ ?vav a brick:Variable_Air_Volume_Box . }} UNION {{ ?vav a brick:Variable_Air_Volume_Box_With_Reheat . }}
  OPTIONAL {{ ?vav rdfs:label ?vav_label . }}
  ?point brick:isPointOf ?vav .
  OPTIONAL {{ ?point rdfs:label ?point_label . }}
  OPTIONAL {{ ?point ofdd:bacnetDeviceId ?bacnet_device_id . }}
  OPTIONAL {{ ?point ofdd:objectIdentifier ?object_identifier . }}
}}
ORDER BY ?ahu ?vav ?point""",
    },
    {
        "id": "equipment_feeds_topology",
        "label": "Equipment feeds and fed-by (Brick topology)",
        "short_label": "Feed topology",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
SELECT ?site_label ?from_label ?relationship ?to_label WHERE {{
  {{
    ?from brick:feeds ?to .
    BIND("feeds" AS ?relationship)
    OPTIONAL {{
      ?from brick:isPartOf ?site .
      OPTIONAL {{ ?site rdfs:label ?site_label . }}
    }}
    OPTIONAL {{ ?from rdfs:label ?from_label . }}
    OPTIONAL {{ ?to rdfs:label ?to_label . }}
  }}
  UNION
  {{
    ?from brick:isFedBy ?to .
    BIND("fed_by" AS ?relationship)
    OPTIONAL {{
      ?from brick:isPartOf ?site .
      OPTIONAL {{ ?site rdfs:label ?site_label . }}
    }}
    OPTIONAL {{ ?from rdfs:label ?from_label . }}
    OPTIONAL {{ ?to rdfs:label ?to_label . }}
  }}
}}
ORDER BY ?site_label ?from_label ?relationship ?to_label""",
    },
    {
        "id": "count-chillers",
        "label": "Count chillers",
        "short_label": "Chillers",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(?c) AS ?count) WHERE {{
  ?c a brick:Chiller .
}}""",
        "query_with_bacnet": _equipment_points_with_bacnet("Chiller"),
    },
    {
        "id": "count-cooling-towers",
        "label": "Count cooling towers",
        "short_label": "Cooling towers",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(?c) AS ?count) WHERE {{
  ?c a brick:Cooling_Tower .
}}""",
        "query_with_bacnet": _equipment_points_with_bacnet("Cooling_Tower"),
    },
    {
        "id": "count-boilers",
        "label": "Count boilers",
        "short_label": "Boilers",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(?b) AS ?count) WHERE {{
  ?b a brick:Boiler .
}}""",
        "query_with_bacnet": _equipment_points_with_bacnet("Boiler"),
    },
    {
        "id": "central_plant_information",
        "label": "Central plant (heat exchangers, pumps)",
        "short_label": "Central plant",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT ?type (COUNT(?e) AS ?count) WHERE {{
  ?e a ?type .
  FILTER(?type IN (
    brick:Heat_Exchanger,
    brick:Water_Pump,
    brick:Chilled_Water_System,
    brick:Condenser_Water_System,
    brick:Hot_Water_System
  ))
}} GROUP BY ?type
ORDER BY DESC(?count)""",
        "query_with_bacnet": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {{
  ?equipment a ?type .
  FILTER(?type IN (brick:Heat_Exchanger, brick:Water_Pump, brick:Chilled_Water_System, brick:Condenser_Water_System, brick:Hot_Water_System))
  OPTIONAL {{ ?equipment rdfs:label ?equipment_label . }}
  ?point brick:isPointOf ?equipment .
  OPTIONAL {{ ?point rdfs:label ?point_label . }}
  OPTIONAL {{ ?point ofdd:bacnetDeviceId ?bacnet_device_id . }}
  OPTIONAL {{ ?point ofdd:objectIdentifier ?object_identifier . }}
}}
ORDER BY ?equipment ?point""",
    },
    {
        "id": "count-hvac-equipment",
        "label": "Count HVAC equipment (all types)",
        "short_label": "HVAC equipment",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(?e) AS ?count) WHERE {{
  ?e a brick:HVAC_Equipment .
}}""",
        "query_with_bacnet": _equipment_points_with_bacnet("HVAC_Equipment"),
    },
    {
        "id": "meter_information",
        "label": "Meters and electrical sensors",
        "short_label": "Meters",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(?m) AS ?meters) (COUNT(?s) AS ?energy_sensors) WHERE {{
  OPTIONAL {{ ?m a brick:Building_Electrical_Meter . }}
  OPTIONAL {{ ?s a brick:Electrical_Energy_Usage_Sensor . }}
}}""",
        "query_with_bacnet": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {{
  {{ ?equipment a brick:Building_Electrical_Meter . }} UNION {{ ?equipment a brick:Electrical_Energy_Usage_Sensor . }}
  OPTIONAL {{ ?equipment rdfs:label ?equipment_label . }}
  ?point brick:isPointOf ?equipment .
  OPTIONAL {{ ?point rdfs:label ?point_label . }}
  OPTIONAL {{ ?point ofdd:bacnetDeviceId ?bacnet_device_id . }}
  OPTIONAL {{ ?point ofdd:objectIdentifier ?object_identifier . }}
}}
ORDER BY ?equipment ?point""",
    },
    {
        "id": "count-points",
        "label": "Count points (sensors, setpoints, commands)",
        "short_label": "Points",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT (COUNT(?p) AS ?count) WHERE {{
  ?p a brick:Point .
}}""",
        "query_with_bacnet": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {{
  ?point a brick:Point .
  OPTIONAL {{ ?point rdfs:label ?point_label . }}
  OPTIONAL {{ ?point ofdd:bacnetDeviceId ?bacnet_device_id . }}
  OPTIONAL {{ ?point ofdd:objectIdentifier ?object_identifier . }}
}}
ORDER BY ?point
LIMIT 500""",
    },
    {
        "id": "class_tag_summary",
        "label": "Entity types (Brick classes used)",
        "short_label": "Class summary",
        "category": "hvac",
        "query": f"""PREFIX brick: <{BRICK}>
SELECT ?type (COUNT(?e) AS ?count) WHERE {{
  ?e a ?type .
  FILTER(STRSTARTS(STR(?type), "https://brickschema.org/schema/Brick#"))
}} GROUP BY ?type
ORDER BY DESC(?count)
LIMIT 50""",
        "query_with_bacnet": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?point ?point_label ?type ?bacnet_device_id ?object_identifier WHERE {{
  ?point a ?type .
  FILTER(STRSTARTS(STR(?type), "https://brickschema.org/schema/Brick#"))
  OPTIONAL {{ ?point rdfs:label ?point_label . }}
  OPTIONAL {{ ?point ofdd:bacnetDeviceId ?bacnet_device_id . }}
  OPTIONAL {{ ?point ofdd:objectIdentifier ?object_identifier . }}
}}
ORDER BY ?type ?point
LIMIT 500""",
    },
    {
        "id": "engineering_ahu_design_cfm",
        "label": "AHUs and design CFM (engineering)",
        "short_label": "AHU design CFM",
        "category": "engineering",
        "query": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?ahu ?ahu_label ?design_cfm WHERE {{
  ?ahu a brick:Air_Handling_Unit .
  OPTIONAL {{ ?ahu rdfs:label ?ahu_label . }}
  OPTIONAL {{ ?ahu ofdd:designCFM ?design_cfm . }}
}}
ORDER BY ?ahu_label""",
    },
    {
        "id": "engineering_by_panel",
        "label": "Equipment electrically served by panel",
        "short_label": "By panel",
        "category": "engineering",
        "query": f"""PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?equipment ?equipment_label ?panel ?breaker WHERE {{
  ?equipment ofdd:feederPanel ?panel .
  OPTIONAL {{ ?equipment rdfs:label ?equipment_label . }}
  OPTIONAL {{ ?equipment ofdd:feederBreaker ?breaker . }}
}}
ORDER BY ?panel ?equipment_label""",
    },
    {
        "id": "engineering_control_vendor",
        "label": "AHUs with control vendor metadata",
        "short_label": "AHU vendor",
        "category": "engineering",
        "query": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?ahu ?ahu_label ?vendor WHERE {{
  ?ahu a brick:Air_Handling_Unit .
  OPTIONAL {{ ?ahu rdfs:label ?ahu_label . }}
  ?ahu ofdd:controlVendor ?vendor .
}}
ORDER BY ?ahu_label""",
    },
    {
        "id": "engineering_capacity_missing_bacnet_points",
        "label": "Design capacity but missing BACnet refs",
        "short_label": "Cap no BACnet",
        "category": "engineering",
        "query": f"""PREFIX brick: <{BRICK}>
PREFIX ofdd: <{OFDD}>
SELECT ?equipment ?capacity WHERE {{
  ?equipment a brick:Equipment .
  {{ ?equipment ofdd:coolingCapacityTons ?capacity . }}
  UNION
  {{ ?equipment ofdd:heatingCapacityMBH ?capacity . }}
  FILTER NOT EXISTS {{
    ?point brick:isPointOf ?equipment .
    ?point ofdd:bacnetDeviceId ?dev .
    ?point ofdd:objectIdentifier ?oid .
  }}
}}
ORDER BY ?equipment""",
    },
    {
        "id": "engineering_source_sheet",
        "label": "Engineering values sourced from PDF sheet",
        "short_label": "Source sheet",
        "category": "engineering",
        "query": f"""PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?equipment ?equipment_label ?doc ?sheet WHERE {{
  ?equipment ofdd:sourceDocumentName ?doc .
  ?equipment ofdd:sourceSheet ?sheet .
  OPTIONAL {{ ?equipment rdfs:label ?equipment_label . }}
}}
ORDER BY ?doc ?sheet ?equipment_label""",
    },
    {
        "id": "engineering_pumps_head_flow",
        "label": "Pumps with head and flow",
        "short_label": "Pump head/flow",
        "category": "engineering",
        "query": f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?pump ?pump_label ?flow ?head WHERE {{
  ?pump a brick:Water_Pump .
  OPTIONAL {{ ?pump rdfs:label ?pump_label . }}
  OPTIONAL {{ ?pump ofdd:pumpFlowGPM ?flow . }}
  OPTIONAL {{ ?pump ofdd:pumpHeadFT ?head . }}
}}
ORDER BY ?pump_label""",
    },
    {
        "id": "engineering_voltage_fla",
        "label": "Equipment with electrical voltage and FLA",
        "short_label": "Voltage/FLA",
        "category": "engineering",
        "query": f"""PREFIX rdfs: <{RDFS}>
PREFIX ofdd: <{OFDD}>
SELECT ?equipment ?equipment_label ?voltage ?fla WHERE {{
  ?equipment ofdd:electricalSystemVoltage ?voltage .
  OPTIONAL {{ ?equipment ofdd:fla ?fla . }}
  OPTIONAL {{ ?equipment rdfs:label ?equipment_label . }}
}}
ORDER BY ?equipment_label""",
    },
    {
        "id": "engineering_s223_topology",
        "label": "s223 connection points and conduits",
        "short_label": "s223 topology",
        "category": "engineering",
        "query": f"""PREFIX rdfs: <{RDFS}>
PREFIX s223: <http://data.ashrae.org/standard223#>
SELECT ?equipment ?cp ?cnx WHERE {{
  ?equipment s223:hasConnectionPoint ?cp .
  OPTIONAL {{ ?equipment s223:cnx ?cnx . }}
}}
ORDER BY ?equipment ?cp""",
    },
]

DEFAULT_SPARQL = f"""PREFIX brick: <{BRICK}>
PREFIX rdfs: <{RDFS}>
SELECT ?site ?site_label WHERE {{
  ?site a brick:Site .
  ?site rdfs:label ?site_label
}}"""


def predefined_catalog() -> dict[str, Any]:
    return {
        "default_query": DEFAULT_SPARQL,
        "queries": PREDEFINED_QUERIES,
    }


def _strip_sparql_comments(query: str) -> str:
    text = re.sub(r"#.*?$", "", query, flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def validate_readonly_sparql(query: str) -> None:
    stripped = _strip_sparql_comments(query or "").strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="SPARQL query is empty")
    tokens = re.findall(r"\b(\w+)\b", stripped, flags=re.IGNORECASE)
    form: str | None = None
    for token in tokens:
        upper = token.upper()
        if upper in ("PREFIX", "BASE"):
            continue
        if upper in _FORBIDDEN_FORMS:
            raise HTTPException(
                status_code=400,
                detail="Only read-only SPARQL (SELECT, ASK, DESCRIBE, CONSTRUCT) is allowed",
            )
        if upper in _READONLY_FORMS:
            form = upper
            break
    if form is None:
        raise HTTPException(
            status_code=400,
            detail="Only read-only SPARQL (SELECT, ASK, DESCRIBE, CONSTRUCT) is allowed",
        )


def execute_model_sparql(query: str, ttl: TtlService | None = None) -> dict[str, Any]:
    validate_readonly_sparql(query)
    svc = ttl or TtlService()
    try:
        graph = load_graph(svc)
        rows = run_sparql(graph, query)
    except TtlGraphError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    truncated = len(rows) > MAX_SPARQL_ROWS
    if truncated:
        rows = rows[:MAX_SPARQL_ROWS]
    return {
        "bindings": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }
