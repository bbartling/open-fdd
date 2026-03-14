import { Wind, Building2, Box, Flame, ThermometerSun, Layers, LayoutGrid, Gauge, List, Network, Code } from "lucide-react";

const BRICK = "https://brickschema.org/schema/Brick#";
const RDFS = "http://www.w3.org/2000/01/rdf-schema#";
const OFDD = "http://openfdd.local/ontology#";

/** Shared SPARQL for "with BACnet refs": select equipment + points + bacnet_device_id + object_identifier. */
function equipmentPointsWithBacnet(equipmentType: string): string {
  return `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
PREFIX ofdd: <${OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {
  ?equipment a brick:${equipmentType} .
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  ?point brick:isPointOf ?equipment .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?equipment ?point`;
}

/** Predefined SPARQL for one-click HVAC summary. Aligns with brick_model_summarizer AVAILABLE_COMPONENTS. */
export const PREDEFINED_QUERIES: {
  id: string;
  label: string;
  shortLabel: string;
  query: string;
  icon: typeof Wind;
  queryWithBacnet?: string;
}[] = [
  {
    id: "sites",
    label: "List sites",
    shortLabel: "Sites",
    icon: Building2,
    query: `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
SELECT ?site ?site_label WHERE {
  ?site a brick:Site .
  OPTIONAL { ?site rdfs:label ?site_label }
}`,
    queryWithBacnet: `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
PREFIX ofdd: <${OFDD}>
SELECT ?site ?site_label ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {
  ?site a brick:Site .
  OPTIONAL { ?site rdfs:label ?site_label . }
  ?equipment brick:isPartOf ?site .
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  ?point brick:isPointOf ?equipment .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?site ?equipment ?point`,
  },
  {
    id: "ahu_information",
    label: "Count Air Handling Units",
    shortLabel: "AHUs",
    icon: Wind,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(?ahu) AS ?count) WHERE {
  ?ahu a brick:Air_Handling_Unit .
}`,
    queryWithBacnet: equipmentPointsWithBacnet("Air_Handling_Unit"),
  },
  {
    id: "zone_information",
    label: "Count zones",
    shortLabel: "Zones",
    icon: LayoutGrid,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(?z) AS ?count) WHERE {
  ?z a brick:HVAC_Zone .
}`,
    queryWithBacnet: equipmentPointsWithBacnet("HVAC_Zone"),
  },
  {
    id: "building_information",
    label: "Building and HVAC counts",
    shortLabel: "Building",
    icon: Building2,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(DISTINCT ?b) AS ?buildings) (COUNT(DISTINCT ?f) AS ?floors) (COUNT(DISTINCT ?e) AS ?hvac_equipment) (COUNT(DISTINCT ?z) AS ?zones) WHERE {
  OPTIONAL { ?b a brick:Building . }
  OPTIONAL { ?f a brick:Floor . }
  OPTIONAL { ?e a brick:HVAC_Equipment . }
  OPTIONAL { ?z a brick:HVAC_Zone . }
}`,
    queryWithBacnet: `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
PREFIX ofdd: <${OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {
  ?equipment a brick:HVAC_Equipment .
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  ?point brick:isPointOf ?equipment .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?equipment ?point`,
  },
  {
    id: "count-vavs",
    label: "Count VAV boxes",
    shortLabel: "VAV boxes",
    icon: Box,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(?vav) AS ?count) WHERE {
  { ?vav a brick:Variable_Air_Volume_Box . }
  UNION
  { ?vav a brick:Variable_Air_Volume_Box_With_Reheat . }
}`,
    queryWithBacnet: `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
PREFIX ofdd: <${OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {
  { ?equipment a brick:Variable_Air_Volume_Box . }
  UNION
  { ?equipment a brick:Variable_Air_Volume_Box_With_Reheat . }
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  ?point brick:isPointOf ?equipment .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?equipment ?point`,
  },
  {
    id: "number_of_vav_boxes_per_ahu",
    label: "VAV boxes per AHU",
    shortLabel: "VAVs per AHU",
    icon: Network,
    query: `PREFIX brick: <${BRICK}>
SELECT ?ahu (COUNT(?vav) AS ?vav_count) WHERE {
  ?ahu a brick:Air_Handling_Unit .
  ?vav brick:isPartOf ?ahu .
  { ?vav a brick:Variable_Air_Volume_Box . } UNION { ?vav a brick:Variable_Air_Volume_Box_With_Reheat . }
} GROUP BY ?ahu
ORDER BY DESC(?vav_count)`,
    queryWithBacnet: `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
PREFIX ofdd: <${OFDD}>
SELECT ?ahu ?ahu_label ?vav ?vav_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {
  ?ahu a brick:Air_Handling_Unit .
  OPTIONAL { ?ahu rdfs:label ?ahu_label . }
  ?vav brick:isPartOf ?ahu .
  { ?vav a brick:Variable_Air_Volume_Box . } UNION { ?vav a brick:Variable_Air_Volume_Box_With_Reheat . }
  OPTIONAL { ?vav rdfs:label ?vav_label . }
  ?point brick:isPointOf ?vav .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?ahu ?vav ?point`,
  },
  {
    id: "count-chillers",
    label: "Count chillers",
    shortLabel: "Chillers",
    icon: ThermometerSun,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(?c) AS ?count) WHERE {
  ?c a brick:Chiller .
}`,
    queryWithBacnet: equipmentPointsWithBacnet("Chiller"),
  },
  {
    id: "count-cooling-towers",
    label: "Count cooling towers",
    shortLabel: "Cooling towers",
    icon: Layers,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(?c) AS ?count) WHERE {
  ?c a brick:Cooling_Tower .
}`,
    queryWithBacnet: equipmentPointsWithBacnet("Cooling_Tower"),
  },
  {
    id: "count-boilers",
    label: "Count boilers",
    shortLabel: "Boilers",
    icon: Flame,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(?b) AS ?count) WHERE {
  ?b a brick:Boiler .
}`,
    queryWithBacnet: equipmentPointsWithBacnet("Boiler"),
  },
  {
    id: "central_plant_information",
    label: "Central plant (heat exchangers, pumps)",
    shortLabel: "Central plant",
    icon: Layers,
    query: `PREFIX brick: <${BRICK}>
SELECT ?type (COUNT(?e) AS ?count) WHERE {
  ?e a ?type .
  FILTER(?type IN (
    brick:Heat_Exchanger,
    brick:Water_Pump,
    brick:Chilled_Water_System,
    brick:Condenser_Water_System,
    brick:Hot_Water_System
  ))
} GROUP BY ?type
ORDER BY DESC(?count)`,
    queryWithBacnet: `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
PREFIX ofdd: <${OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {
  ?equipment a ?type .
  FILTER(?type IN (brick:Heat_Exchanger, brick:Water_Pump, brick:Chilled_Water_System, brick:Condenser_Water_System, brick:Hot_Water_System))
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  ?point brick:isPointOf ?equipment .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?equipment ?point`,
  },
  {
    id: "count-hvac-equipment",
    label: "Count HVAC equipment (all types)",
    shortLabel: "HVAC equipment",
    icon: Wind,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(?e) AS ?count) WHERE {
  ?e a brick:HVAC_Equipment .
}`,
    queryWithBacnet: equipmentPointsWithBacnet("HVAC_Equipment"),
  },
  {
    id: "meter_information",
    label: "Meters and electrical sensors",
    shortLabel: "Meters",
    icon: Gauge,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(?m) AS ?meters) (COUNT(?s) AS ?energy_sensors) WHERE {
  OPTIONAL { ?m a brick:Building_Electrical_Meter . }
  OPTIONAL { ?s a brick:Electrical_Energy_Usage_Sensor . }
}`,
    queryWithBacnet: `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
PREFIX ofdd: <${OFDD}>
SELECT ?equipment ?equipment_label ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {
  { ?equipment a brick:Building_Electrical_Meter . } UNION { ?equipment a brick:Electrical_Energy_Usage_Sensor . }
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  ?point brick:isPointOf ?equipment .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?equipment ?point`,
  },
  {
    id: "count-points",
    label: "Count points (sensors, setpoints, commands)",
    shortLabel: "Points",
    icon: Code,
    query: `PREFIX brick: <${BRICK}>
SELECT (COUNT(?p) AS ?count) WHERE {
  ?p a brick:Point .
}`,
    queryWithBacnet: `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
PREFIX ofdd: <${OFDD}>
SELECT ?point ?point_label ?bacnet_device_id ?object_identifier WHERE {
  ?point a brick:Point .
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?point
LIMIT 500`,
  },
  {
    id: "class_tag_summary",
    label: "Entity types (Brick classes used)",
    shortLabel: "Class summary",
    icon: List,
    query: `PREFIX brick: <${BRICK}>
SELECT ?type (COUNT(?e) AS ?count) WHERE {
  ?e a ?type .
  FILTER(STRSTARTS(STR(?type), "https://brickschema.org/schema/Brick#"))
} GROUP BY ?type
ORDER BY DESC(?count)
LIMIT 50`,
    queryWithBacnet: `PREFIX brick: <${BRICK}>
PREFIX rdfs: <${RDFS}>
PREFIX ofdd: <${OFDD}>
SELECT ?point ?point_label ?type ?bacnet_device_id ?object_identifier WHERE {
  ?point a ?type .
  FILTER(STRSTARTS(STR(?type), "https://brickschema.org/schema/Brick#"))
  OPTIONAL { ?point rdfs:label ?point_label . }
  OPTIONAL { ?point ofdd:bacnetDeviceId ?bacnet_device_id . }
  OPTIONAL { ?point ofdd:objectIdentifier ?object_identifier . }
}
ORDER BY ?type ?point
LIMIT 500`,
  },
];

export const DEFAULT_SPARQL = `PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?site_label WHERE {
  ?site a brick:Site .
  ?site rdfs:label ?site_label
}`;
