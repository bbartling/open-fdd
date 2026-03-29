# 223P / engineering tutorial (single document)

This folder supports **Data Model Engineering** and **Data Model Testing** workflows in Open-FDD: JSON import shape, Brick + ASHRAE 223P (`s223:`) topology in Turtle, a **mini graph** with AHU→VAV feeds and a BACnet/timeseries point, copy-paste **SPARQL**, and a **simultaneous heat/cool penalty** sketch.

**On-disk companions (same content as the embedded snippets below, for imports and diffs):**

| File | Role |
|------|------|
| `engineering_import_example.json` | API/import payload for `equipment.engineering` |
| `engineering_topology_example.ttl` | RDF: AHU + s223 connection points and duct |
| `engineering_graph_mini.ttl` | RDF: site, AHU→VAV `feeds`/`isFedBy`, one point with `ref:` |

---

## Table of contents

1. [Import payload: `equipment.engineering`](#1-import-payload-equipmentengineering)
2. [Topology in Turtle (AHU + s223)](#2-topology-in-turtle-ahu--s223)
3. [Mini graph: topology + capacity + BACnet point](#3-mini-graph-topology--capacity--bacnet-point)
4. [SPARQL examples (Data Model Testing)](#4-sparql-examples-data-model-testing)
5. [Sandbox: simultaneous heat / cool penalty](#5-sandbox-simultaneous-heat--cool-penalty)

---

## 1. Import payload: `equipment.engineering`

Use this shape when importing **engineering** metadata (controls, mechanical, electrical, topology, documents). Empty `points` is fine for an equipment-only engineering pass; your pipeline can merge points later.

**File:** `engineering_import_example.json`

```json
{
  "points": [],
  "equipment": [
    {
      "equipment_name": "AHU-1",
      "site_id": "11111111-1111-1111-1111-111111111111",
      "equipment_type": "Air_Handling_Unit",
      "engineering": {
        "controls": {
          "control_vendor": "Example Controls",
          "control_system_type": "BAS",
          "front_end_platform": "Open-FDD",
          "panel_name": "MDF-1",
          "ip_address": "10.10.10.42",
          "bacnet_network_number": "1001",
          "install_date": "2026-03-01",
          "as_built_date": "2026-03-15"
        },
        "mechanical": {
          "manufacturer": "Example HVAC",
          "model_number": "AHU-7X",
          "serial_number": "SN-12345",
          "design_cfm": "5000",
          "cooling_capacity_tons": "25",
          "heating_capacity_mbh": "400"
        },
        "electrical": {
          "electrical_system_voltage": "480",
          "fla": "32",
          "mca": "40",
          "mocp": "50",
          "feeder_panel": "MDP-1",
          "feeder_breaker": "3P-50A"
        },
        "topology": {
          "connection_points": [
            { "id": "ahu1-inlet", "name": "AHU-1 Inlet", "type": "inlet", "medium": "air" },
            { "id": "ahu1-outlet", "name": "AHU-1 Outlet", "type": "outlet", "medium": "air" }
          ],
          "connections": [
            { "conduit_type": "duct", "from": "ahu1-outlet", "to": "vav1-inlet", "medium": "air" }
          ],
          "mediums": ["air"]
        },
        "documents": {
          "source_document_name": "M-401.pdf",
          "source_sheet": "M-401",
          "verified_by_human": "true"
        },
        "extensions": {
          "commissioning_status": "pre-functional complete"
        }
      }
    }
  ]
}
```

---

## 2. Topology in Turtle (AHU + s223)

After you understand the **JSON** shape, compare how the same **AHU** story can appear as **RDF**: Brick class for the air handler, **223P** connection points, and a **duct** `s223:cnx`. This file is intentionally smaller than the mini graph—no site, no VAV, no points.

**File:** `engineering_topology_example.ttl`

```turtle
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ofdd: <http://openfdd.local/ontology#> .
@prefix s223: <http://data.ashrae.org/standard223#> .
@prefix : <http://openfdd.local/site#> .

:eq_ahu1 a brick:Air_Handling_Unit ;
  rdfs:label "AHU-1" ;
  ofdd:controlVendor "Example Controls" ;
  ofdd:designCFM "5000" ;
  ofdd:electricalSystemVoltage "480" ;
  s223:hasConnectionPoint :cp_ahu1_inlet ;
  s223:hasConnectionPoint :cp_ahu1_outlet ;
  s223:cnx :cnx_ahu1_duct_1 .

:cp_ahu1_inlet a s223:InletConnectionPoint ;
  rdfs:label "AHU-1 Inlet" ;
  ofdd:connectionMedium "air" .

:cp_ahu1_outlet a s223:OutletConnectionPoint ;
  rdfs:label "AHU-1 Outlet" ;
  ofdd:connectionMedium "air" .

:cnx_ahu1_duct_1 a s223:Duct ;
  ofdd:connectsFromRef "ahu1-outlet" ;
  ofdd:connectsToRef "vav1-inlet" ;
  ofdd:connectionMedium "air" .
```

---

## 3. Mini graph: topology + capacity + BACnet point

This **end-to-end** sample ties together:

- `brick:Site` and equipment **part-of** site  
- **AHU → VAV** with `brick:feeds` / `brick:isFedBy`  
- **Engineering literals** on the AHU (`ofdd:designCFM`, `ofdd:coolingCapacityTons`, …)  
- **223P** outlets/inlets and a `s223:Duct`  
- One **point** (`brick:Cooling_Valve_Command`) with `ofdd:mapsToRuleInput`, `ref:BACnetReference`, and `ref:TimeseriesReference`

Use it in **Data Model Testing** after import, or load into an offline RDF tool and run the SPARQL below.

**File:** `engineering_graph_mini.ttl`

```turtle
# Minimal illustration: Brick equipment + feeds/fedBy + Brick ref (BACnet + timeseries)
# on points + engineering (ofdd + s223). Not a full site export—copy patterns into imports or compare to View TTL.

@prefix : <http://openfdd.local/site#> .
@prefix bacnet: <http://data.ashrae.org/bacnet/2020#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ofdd: <http://openfdd.local/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ref: <https://brickschema.org/schema/Brick/ref#> .
@prefix s223: <http://data.ashrae.org/standard223#> .

:site_demo a brick:Site ;
  rdfs:label "Engineering demo site" .

:eq_ahu_demo a brick:Air_Handling_Unit ;
  rdfs:label "AHU-1" ;
  brick:isPartOf :site_demo ;
  brick:feeds :eq_vav_demo ;
  ofdd:controlVendor "Example Controls" ;
  ofdd:designCFM "5000" ;
  ofdd:coolingCapacityTons "25" ;
  ofdd:heatingCapacityMBH "400" ;
  s223:hasConnectionPoint :cp_ahu_out ;
  s223:cnx :duct_ahu_to_vav .

:eq_vav_demo a brick:Variable_Air_Volume_Box ;
  rdfs:label "VAV-1" ;
  brick:isPartOf :site_demo ;
  brick:isFedBy :eq_ahu_demo ;
  s223:hasConnectionPoint :cp_vav_in .

:cp_ahu_out a s223:OutletConnectionPoint ;
  rdfs:label "AHU supply outlet" ;
  ofdd:connectionMedium "air" .

:cp_vav_in a s223:InletConnectionPoint ;
  rdfs:label "VAV inlet" ;
  ofdd:connectionMedium "air" .

:duct_ahu_to_vav a s223:Duct ;
  ofdd:connectsFromRef "ahu-outlet" ;
  ofdd:connectsToRef "vav-inlet" ;
  ofdd:connectionMedium "air" .

# Point: Brick class + rule input + external refs (same idea as live data_model.ttl)
:pt_clg_valve a brick:Cooling_Valve_Command ;
  rdfs:label "CLG-O" ;
  ofdd:mapsToRuleInput "clg_cmd" ;
  ofdd:polling true ;
  ofdd:unit "%" ;
  brick:isPointOf :eq_ahu_demo ;
  ref:hasExternalReference
    [ a ref:BACnetReference ;
      bacnet:object-identifier "analog-output,3" ;
      bacnet:object-name "CLG-O" ;
      bacnet:objectOf <bacnet://3456789> ;
      brick:BACnetURI "bacnet://3456789/analog-output,3/present-value" ] ,
    [ a ref:TimeseriesReference ;
      ref:hasTimeseriesId "CLG-O" ;
      ref:storedAt "postgresql://db:5432/openfdd/timeseries_readings" ] .
```

---

## 4. SPARQL examples (Data Model Testing)

Run these in **Data Model Testing** after engineering metadata is imported, or against `engineering_graph_mini.ttl` in an offline triple store.

### AHU → VAV topology (Brick `feeds`)

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?upstream ?upstream_label ?downstream ?downstream_label WHERE {
  ?upstream brick:feeds ?downstream .
  OPTIONAL { ?upstream rdfs:label ?upstream_label . }
  OPTIONAL { ?downstream rdfs:label ?downstream_label . }
}
ORDER BY ?upstream_label ?downstream_label
```

### AHUs with design CFM and cooling tons (optimization / penalty context)

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?ahu ?ahu_label ?design_cfm ?tons WHERE {
  ?ahu a brick:Air_Handling_Unit .
  OPTIONAL { ?ahu rdfs:label ?ahu_label . }
  OPTIONAL { ?ahu ofdd:designCFM ?design_cfm . }
  OPTIONAL { ?ahu ofdd:coolingCapacityTons ?tons . }
}
ORDER BY ?ahu_label
```

### Points on an AHU with BACnet + timeseries refs (Brick `ref:`)

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
SELECT ?point ?label ?rule_in ?oid WHERE {
  ?ahu a brick:Air_Handling_Unit .
  ?point brick:isPointOf ?ahu .
  OPTIONAL { ?point rdfs:label ?label . }
  OPTIONAL { ?point ofdd:mapsToRuleInput ?rule_in . }
  ?point ref:hasExternalReference ?rep .
  ?rep a ref:BACnetReference .
  OPTIONAL { ?rep bacnet:object-identifier ?oid . }
}
ORDER BY ?label
```

### Equipment served by electrical panel

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?equipment ?equipment_label ?panel ?breaker WHERE {
  ?equipment ofdd:feederPanel ?panel .
  OPTIONAL { ?equipment rdfs:label ?equipment_label . }
  OPTIONAL { ?equipment ofdd:feederBreaker ?breaker . }
}
ORDER BY ?panel ?equipment_label
```

### s223 connection points and conduits

```sparql
PREFIX s223: <http://data.ashrae.org/standard223#>
SELECT ?equipment ?cp ?cnx WHERE {
  ?equipment s223:hasConnectionPoint ?cp .
  OPTIONAL { ?equipment s223:cnx ?cnx . }
}
ORDER BY ?equipment ?cp
```

### BACnet devices present in the graph

```sparql
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?dev ?label ?inst WHERE {
  ?dev a bacnet:Device .
  OPTIONAL { ?dev rdfs:label ?label . }
  OPTIONAL { ?dev bacnet:device-instance ?inst . }
}
ORDER BY ?inst
```

---

## 5. Sandbox: simultaneous heat / cool penalty

**Intent:** Show how **engineering capacity on the graph** (from Data Model Engineering → `ofdd:coolingCapacityTons`, `ofdd:heatingCapacityMBH`) plus **time-series** (valve %, SAT, etc.) can feed a **back-of-envelope** penalty when a fault (e.g. leaking cooling valve) fights heating.

This is **not** calibrated M&V—only a **teaching** stub for integrators and future optimization layers.

### Assumptions (tune per site)

- \(Q_c\) = design cooling capacity (**tons**) from the graph (`ofdd:coolingCapacityTons`).
- Valve is leaking cold water / coil active at fraction \(f\) (0–1), estimated from trends (e.g. `clg_cmd` near 0 but SAT or coil ΔT says otherwise)—**your FDD rule supplies \(f\)**.
- Simultaneous reheat / heating is on at roughly the same time over \(h\) hours.
- **Crude electric proxy:** treat unwanted cooling as chiller / compressor load at ~**3.517 kW per ton** (order-of-magnitude; replace with COP/PLR model later).

### Formula (kWh, order-of-magnitude)

\[
E_{\text{extra}} \approx Q_c \times 3.517 \times f \times h
\]

- \(Q_c\) in **tons**, \(h\) in **hours**, result in **kWh** (scale of magnitude for “how big is this fault?”).

**Example:** \(Q_c = 25\) tons, \(f = 0.15\) leak, \(h = 8\) h run → \(25 \times 3.517 \times 0.15 \times 8 \approx 106\) kWh per event window.

### What Open-FDD provides

| Piece | Where |
|-------|--------|
| Design tons / MBH | Equipment **engineering** → RDF `ofdd:coolingCapacityTons`, `ofdd:heatingCapacityMBH` |
| Topology (AHU → VAV) | `brick:feeds` / `brick:isFedBy` + optional `s223:*` |
| BACnet + DB series | `ref:BACnetReference` + `ref:TimeseriesReference` on points; scrape → `timeseries_readings` |
| Fault flag / severity | YAML FDD rules → \(f\) or duration \(h\) from fault analytics |

### Next steps (product / integration)

- Pull \(Q_c\) with SPARQL ([§4](#4-sparql-examples-data-model-testing)—“AHUs with design CFM and cooling tons”).
- Pull average `clg_cmd` / SAT for the fault window from SQL or API download CSV.
- Replace 3.517 with **site COP** or **utility $/kWh** for cost.

---

## Suggested tutorial path

1. Read **§1** (JSON import shape).  
2. Open **§2** TTL—see **223P** connection points and duct without VAV/points.  
3. Open **§3** TTL—see **feeds**, **capacity**, and **one BACnet/timeseries point**.  
4. Paste **§4** queries into **Data Model Testing** (or your RDF desktop tool).  
5. Read **§5** to connect graph capacity to a rough **energy penalty** story.

---

*Previously split across `sparql_engineering_examples.md` and `energy_penalty_sandbox.md`; those are merged here.*
