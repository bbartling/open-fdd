---
title: SPARQL cookbook
parent: Data modeling
nav_order: 5
---

# SPARQL cookbook

Open-FDD keeps one **knowledge graph** (Brick + BACnet + platform config) in `config/data_model.ttl`. All queries in this cookbook run **via the REST API only** — use **POST /data-model/sparql** with a JSON body `{"query": "..."}`. Do not query the TTL file directly; the API is the single entry point so the same flow works for UIs, scripts, and tests.

---

## Data Model Setup vs Data Model Testing

The frontend has two tabs:

| Tab | Route | Purpose |
|-----|--------|---------|
| **Data Model Setup** | `/data-model` | Sites, equipment, import/export JSON, view TTL. Build or edit the data model (sites, equipment, points) and paste AI-tagged JSON to import. |
| **Data Model Testing** | `/data-model-testing` | **Summarize your HVAC** (one-click SPARQL buttons: Sites, AHUs, Zones, Building, VAV boxes, etc.) and **Custom SPARQL** (textarea, Run, upload .sparql file). Same queries as this cookbook. |

Use **Data Model Testing** to run SPARQL in the browser. Use **Data Model Setup** to manage sites, equipment, and import.

---

## How to run SPARQL

| Method | Use |
|--------|-----|
| **Data Model Testing (UI)** | Open **Data Model Testing** → click a predefined button (Sites, AHUs, Zones, …) or paste SPARQL in Custom SPARQL → Run SPARQL. Optional: check "Include BACnet device and point IDs" for `bacnet_device_id` / `object_identifier` in results. |
| **Swagger** | [http://localhost:8000/docs](http://localhost:8000/docs) → **POST /data-model/sparql** → body `{"query": "SELECT ..."}` → Execute. |
| **curl** | `curl -X POST http://localhost:8000/data-model/sparql -H "Content-Type: application/json" -d '{"query":"SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"}'` |
| **Upload .sparql file** | **Data Model Testing** → Custom SPARQL → "Upload .sparql file", then Run; or **POST /data-model/sparql/upload** with a `.sparql` file. |

**Response:** JSON with a `bindings` array; each element is a map of variable names to values (e.g. `{"site_label": {"value": "DemoSite"}}`). Use the `value` field for literals and the full object for URIs.

---

## Prefixes and graph contents

The graph uses these namespaces. Include them in your queries:

| Prefix | Namespace |
|--------|-----------|
| `brick:` | https://brickschema.org/schema/Brick# |
| `rdfs:` | http://www.w3.org/2000/01/rdf-schema# |
| `ref:` | https://brickschema.org/schema/Brick/ref# |
| `ofdd:` | http://openfdd.local/ontology# |
| `bacnet:` | http://data.ashrae.org/bacnet/2020# |
| `:` (default) | http://openfdd.local/site# |

**Graph contents:** Brick triples (sites, equipment, points from the DB), Brick external references (`ref:BACnetReference`, `ref:TimeseriesReference`), BACnet triples (devices and objects from discovery), and **ofdd:PlatformConfig** (platform config from GET/PUT /config). All are queryable together.

---

## Recipe 1: Platform config

Platform config is stored as RDF (same graph). Use it to verify or audit settings after PUT /config or bootstrap.

**All config triples:**

```sparql
PREFIX ofdd: <http://openfdd.local/ontology#>
SELECT ?p ?v WHERE {
  ?c a ofdd:PlatformConfig .
  ?c ?p ?v .
}
```

**Example bindings:** `ofdd:ruleIntervalHours`, `ofdd:bacnetServerUrl`, `ofdd:bacnetEnabled`, etc. Predicates are camelCase (e.g. `ruleIntervalHours`). Use this to confirm config is in the graph after seeding.

---

## Recipe 2: Sites and counts

**All sites with labels:**

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?site_label WHERE {
  ?site a brick:Site .
  ?site rdfs:label ?site_label .
}
```

**Site and aggregate counts** (equipment count, point count per site):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site_label (COUNT(DISTINCT ?equipment) AS ?equipment_count) (COUNT(?point) AS ?point_count) WHERE {
  ?site a brick:Site .
  ?site rdfs:label ?site_label .
  ?equipment brick:isPartOf ?site .
  ?point brick:isPointOf ?equipment .
}
GROUP BY ?site ?site_label
```

Use this to validate the data model after CRUD or import (see [Getting started](../getting_started)).

---

## Recipe 3: Equipment and points by site

**Equipment labels for a given site** (replace `"YourSiteLabel"` with your site name):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?eq_label WHERE {
  ?eq brick:isPartOf ?site .
  ?site rdfs:label "YourSiteLabel" .
  ?eq rdfs:label ?eq_label .
}
```

**Point labels for a site** (points under equipment under site):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?pt_label WHERE {
  ?pt brick:isPointOf ?eq .
  ?eq brick:isPartOf ?site .
  ?site rdfs:label "YourSiteLabel" .
  ?pt rdfs:label ?pt_label .
}
```

**Equipment feeds** (Brick `feeds` relationships for a site):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?eq_label ?feeds_label WHERE {
  ?eq brick:isPartOf ?site .
  ?site rdfs:label "YourSiteLabel" .
  ?eq rdfs:label ?eq_label .
  ?eq brick:feeds ?other .
  ?other rdfs:label ?feeds_label .
}
```

---

## Recipe 3b: External references (Brick v1.3)

List point-to-reference relationships:

```sparql
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT ?point ?rep ?type WHERE {
  ?point ref:hasExternalReference ?rep .
  ?rep a ?type .
}
LIMIT 200
```

BACnet references from point metadata:

```sparql
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
SELECT ?point ?oid ?device WHERE {
  ?point ref:hasExternalReference ?rep .
  ?rep a ref:BACnetReference ;
       bacnet:object-identifier ?oid ;
       bacnet:objectOf ?device .
}
```

Timeseries references:

```sparql
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT ?point ?tsid ?store WHERE {
  ?point ref:hasExternalReference ?rep .
  ?rep a ref:TimeseriesReference ;
       ref:hasTimeseriesId ?tsid ;
       ref:storedAt ?store .
}
```

## Recipe 4: BACnet devices and objects

After **POST /bacnet/point_discovery_to_graph**, the graph contains BACnet devices and their objects.

**All BACnet devices:**

```sparql
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
SELECT ?dev WHERE { ?dev a bacnet:Device }
```

**Object count per device:**

```sparql
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
SELECT ?dev (COUNT(?obj) AS ?n) WHERE {
  ?dev a bacnet:Device .
  ?dev bacnet:contains ?obj .
}
GROUP BY ?dev
```

**Object names for a device** (e.g. device instance 3456789):

```sparql
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
SELECT ?name WHERE {
  ?dev a bacnet:Device ;
       bacnet:device-instance 3456789 ;
       bacnet:contains ?obj .
  ?obj bacnet:object-name ?name .
}
```

Use these to confirm discovery results are in the graph and to cross-check with GET /data-model/export.

**BACnet device and object addresses for points with polling = true** (join Brick points to BACnet via matching label and object-name):

```sparql
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
PREFIX ofdd: <http://openfdd.local/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?device_instance ?device_address ?object_identifier ?point_label
WHERE {
  ?point ofdd:polling true ;
         rdfs:label ?point_label .
  ?bacnet_obj bacnet:object-name ?point_label ;
              bacnet:object-identifier ?object_identifier .
  ?device bacnet:contains ?bacnet_obj ;
          bacnet:device-instance ?device_instance ;
          bacnet:device-address ?device_address .
}
ORDER BY ?device_instance ?object_identifier
```

Returns one row per polling point that has a matching BACnet object: `device_instance`, `device_address`, `object_identifier` (e.g. `analog-input,1`), and `point_label`. Use this for scraper config or to list “which BACnet addresses are in the data model and polled.”

**Why "No bindings (empty result)"?** The query above joins **Brick** points to **BACnet** objects. If your graph has no BACnet triples (no discovery has been run, or you only have Brick from a TTL file), there are no `bacnet:Device`, `bacnet:contains`, or `bacnet:object-name` triples, so the join returns nothing. Use the query below when you only have Brick data.

**Polling points with a Brick type (no BACnet)** — use this when the graph has no BACnet data; it returns points that have `ofdd:polling true` and a Brick class (e.g. `Return_Air_Temperature_Sensor`):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ofdd: <http://openfdd.local/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?brick_class ?point_label ?unit
WHERE {
  ?point ofdd:polling true ;
         rdfs:label ?point_label ;
         a ?brick_type .
  FILTER(STRSTARTS(STR(?brick_type), STR(brick:)))
  BIND(REPLACE(STR(?brick_type), "https://brickschema.org/schema/Brick#", "") AS ?brick_class)
  OPTIONAL { ?point ofdd:unit ?unit . }
}
ORDER BY ?point_label
```

**Data Model Setup: Equipment table vs "View full data model (TTL)"** — The **Equipment** table on **Data Model Setup** comes from the **database** (REST API: sites, equipment, points). **Data Model Testing** (SPARQL) and **"View full data model (TTL)"** on Setup use the **in-memory graph**, which is synced from the DB (Brick) plus BACnet discovery. If you see a full TTL with equipment but "No equipment configured" in the table, the DB may be empty or out of sync: the graph can be loaded from `config/data_model.ttl` on startup, but the UI list is always from the API/DB. Use the site selector in the top bar ("All sites" vs a specific site); ensure sites and equipment exist in the DB (e.g. create via the UI or import).

---

## Recipe 5: FDD — points and rule mapping

FDD rules resolve Brick classes to DataFrame columns via the TTL. These queries help you validate that points have the right Brick types and rule inputs for your rules (e.g. [sensor_bounds](../rules/overview) or [expression rules](../expression_rule_cookbook)).

**Brick class → label → rule input** (timeseries reference and FDD input name):

```sparql
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
ORDER BY ?brick_class ?rule_input
LIMIT 50
```

- **`rdfs:label`** = `external_id` in the DB = timeseries key (column name in the FDD DataFrame).
- **`ofdd:mapsToRuleInput`** = `fdd_input` in the DB = name the rule uses when multiple points share a Brick class.

**Brick classes used in the model** (count per class):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?brick_class (COUNT(?point) AS ?count) WHERE {
  ?point a ?brick_type .
  FILTER(STRSTARTS(STR(?brick_type), STR(brick:)))
  BIND(REPLACE(STR(?brick_type), "https://brickschema.org/schema/Brick#", "") AS ?brick_class)
}
GROUP BY ?brick_class
ORDER BY DESC(?count)
```

Use this to ensure every Brick class your rules reference (e.g. `Supply_Air_Temperature_Sensor`, `Zone_Temperature_Sensor`) has at least one point in the graph.

---

## Recipe 6: FDD — time-series references for rules

Rules in `stack/rules/` (e.g. `sensor_bounds.yaml`, expression rules) declare **inputs** by Brick class only. The runner uses the Brick TTL (this graph) to resolve:

- **Brick class** → points of that type → **rdfs:label** (external_id) → column in the timeseries DataFrame.

So the **timeseries reference** for FDD is the point’s **rdfs:label** (which equals `external_id` in the DB and is the key in `timeseries_readings` when joined via `point_id`). To list “which columns will this rule see for site X?”:

**Points that map to rule inputs for a site** (equipment hierarchy + label = timeseries key):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ofdd: <http://openfdd.local/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?equipment_label ?point_class ?label ?rule_input WHERE {
  ?site a brick:Site .
  ?site rdfs:label "YourSiteLabel" .
  ?equipment brick:isPartOf ?site .
  ?equipment rdfs:label ?equipment_label .
  ?point brick:isPointOf ?equipment .
  ?point a ?brick_type .
  FILTER(STRSTARTS(STR(?brick_type), STR(brick:)))
  BIND(REPLACE(STR(?brick_type), "https://brickschema.org/schema/Brick#", "") AS ?point_class)
  ?point rdfs:label ?label .
  OPTIONAL { ?point ofdd:mapsToRuleInput ?rule_input . }
}
ORDER BY ?equipment_label ?point_class
```

Interpretation: For each row, **`label`** is the timeseries column name (external_id). The rule runner loads timeseries by (site, external_id) and builds the DataFrame; then Brick class (and optional rule_input) select which column is used for each rule input. So this query answers “what timeseries refs (columns) does the FDD pipeline have for this site?”

**Polling points only** (points that the BACnet scraper writes to; exclude non-polling):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ofdd: <http://openfdd.local/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?label ?brick_class WHERE {
  ?pt a ?brick_type .
  FILTER(STRSTARTS(STR(?brick_type), STR(brick:)))
  BIND(REPLACE(STR(?brick_type), "https://brickschema.org/schema/Brick#", "") AS ?brick_class)
  ?pt rdfs:label ?label .
  ?pt ofdd:polling true .
}
ORDER BY ?brick_class ?label
```

These queries mirror the logic in `scripts/automated_testing/sparql/` (e.g. 05_brick_rule_mapping.sparql); run them via the API for validation or for building a small “FDD readiness” report.

---

## Recipe 7: Integrity and completeness

**Graph check** — Use **GET /data-model/check** for triple counts, sites count, BACnet device count, and orphan warnings. For custom checks, use SPARQL:

**Count triples:**

```sparql
SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }
```

**Equipment hierarchy snapshot** (site → equipment type → point class → rule input):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ofdd: <http://openfdd.local/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site_label ?equipment_label ?equipment_type ?point_class ?rule_input WHERE {
  ?site a brick:Site .
  ?site rdfs:label ?site_label .
  ?equipment brick:isPartOf ?site .
  ?equipment rdfs:label ?equipment_label .
  ?equipment ofdd:equipmentType ?equipment_type .
  ?point brick:isPointOf ?equipment .
  ?point a ?brick_type .
  FILTER(STRSTARTS(STR(?brick_type), STR(brick:)))
  BIND(REPLACE(STR(?brick_type), "https://brickschema.org/schema/Brick#", "") AS ?point_class)
  OPTIONAL { ?point ofdd:mapsToRuleInput ?rule_input . }
}
ORDER BY ?site_label ?equipment_label ?point_class
LIMIT 100
```

---

## Predefined buttons (Data Model Testing)

The **Data Model Testing** tab has one-click buttons under **Summarize your HVAC** that run the same SPARQL as this cookbook.

| Button | Recipe |
|--------|--------|
| Sites | Recipe 2 (sites with labels) |
| AHUs, Zones, Building, VAV boxes, VAVs per AHU | Count or list by Brick type |
| Chillers, Cooling towers, Boilers, Central plant | Count or list equipment types |
| HVAC equipment, Meters, Points, Class summary | Counts and Brick class summary |

Checking **Include BACnet device and point IDs** on Data Model Testing runs a variant of each query that adds `bacnet_device_id` and `object_identifier` (for telemetry and algorithms).

---

## Saved queries

The recipes in this cookbook can be saved as `.sparql` files and run via **POST /data-model/sparql**, **POST /data-model/sparql/upload**, or **Data Model Testing** (Custom SPARQL → upload or paste). Recipe 4 covers BACnet devices, polling points with Brick type, and polling points with optional BACnet join.

**scripts/automated_testing/sparql/** — `.sparql` files for FDD-oriented validation (e.g. brick rule mapping, site counts). Run via **POST /data-model/sparql/upload** or **Data Model Testing** (Custom SPARQL).

---

## Related docs

| Topic | Page |
|-------|------|
| Data model flow | [Overview](overview) |
| AI-assisted tagging | [AI-assisted tagging](ai_assisted_tagging) |
| Rule inputs and Brick | [Expression rule cookbook](../expression_rule_cookbook) · [Fault rules overview](../rules/overview) |
| Grafana (SQL, not SPARQL) | [Grafana SQL cookbook](../howto/grafana_cookbook) |
| Dev reference | [Technical reference](../appendix/technical_reference) |
