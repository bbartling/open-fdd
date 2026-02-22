---
title: SPARQL cookbook
parent: Data modeling
nav_order: 5
---

# SPARQL cookbook

Open-FDD keeps one **knowledge graph** (Brick + BACnet + platform config) in `config/data_model.ttl`. All queries in this cookbook run **via the REST API only** — use **POST /data-model/sparql** with a JSON body `{"query": "..."}`. Do not query the TTL file directly; the API is the single entry point so the same flow works for UIs, scripts, and tests.

---

## How to run SPARQL

| Method | Use |
|--------|-----|
| **Swagger** | [http://localhost:8000/docs](http://localhost:8000/docs) → **POST /data-model/sparql** → body `{"query": "SELECT ..."}` → Execute. |
| **curl** | `curl -X POST http://localhost:8000/data-model/sparql -H "Content-Type: application/json" -d '{"query":"SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"}'` |
| **Upload .sparql file** | **POST /data-model/sparql/upload** with a `.sparql` file (e.g. from `analyst/sparql/`). |

**Response:** JSON with a `bindings` array; each element is a map of variable names to values (e.g. `{"site_label": {"value": "DemoSite"}}`). Use the `value` field for literals and the full object for URIs.

---

## Prefixes and graph contents

The graph uses these namespaces. Include them in your queries:

| Prefix | Namespace |
|--------|-----------|
| `brick:` | https://brickschema.org/schema/Brick# |
| `rdfs:` | http://www.w3.org/2000/01/rdf-schema# |
| `ofdd:` | http://openfdd.local/ontology# |
| `bacnet:` | http://data.ashrae.org/bacnet/2020# |
| `:` (default) | http://openfdd.local/site# |

**Graph contents:** Brick triples (sites, equipment, points from the DB), BACnet triples (devices and objects from discovery), and **ofdd:PlatformConfig** (platform config from GET/PUT /config). All are queryable together.

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

**Example bindings:** `ofdd:ruleIntervalHours`, `ofdd:bacnetServerUrl`, `ofdd:bacnetEnabled`, etc. Predicates are camelCase (e.g. `ruleIntervalHours`). Use this to confirm config is in the graph after seeding or after running `tools/graph_and_crud_test.py` (steps 1c–1e).

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

Use this to validate the data model after CRUD or import (e.g. in e2e tests or from `tools/graph_and_crud_test.py`; see [Getting started](../getting_started)).

---

## Recipe 3: Equipment and points by site

**Equipment labels for a given site** (bind site label in the query or filter in application code):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?eq_label WHERE {
  ?eq brick:isPartOf ?site .
  ?site rdfs:label "DemoSite" .
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
  ?site rdfs:label "DemoSite" .
  ?pt rdfs:label ?pt_label .
}
```

**Equipment feeds** (Brick `feeds` relationships for a site):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?eq_label ?feeds_label WHERE {
  ?eq brick:isPartOf ?site .
  ?site rdfs:label "DemoSite" .
  ?eq rdfs:label ?eq_label .
  ?eq brick:feeds ?other .
  ?other rdfs:label ?feeds_label .
}
```

---

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

Rules in `analyst/rules/` (e.g. `sensor_bounds.yaml`, expression rules) declare **inputs** by Brick class only. The runner uses the Brick TTL (this graph) to resolve:

- **Brick class** → points of that type → **rdfs:label** (external_id) → column in the timeseries DataFrame.

So the **timeseries reference** for FDD is the point’s **rdfs:label** (which equals `external_id` in the DB and is the key in `timeseries_readings` when joined via `point_id`). To list “which columns will this rule see for site X?”:

**Points that map to rule inputs for a site** (equipment hierarchy + label = timeseries key):

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ofdd: <http://openfdd.local/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?equipment_label ?point_class ?label ?rule_input WHERE {
  ?site a brick:Site .
  ?site rdfs:label "DemoSite" .
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

These queries mirror the logic in `analyst/sparql/01_points_rule_mapping.sparql` and `analyst/sparql/04_brick_classes_used.sparql`; run them via the API for validation or for building a small “FDD readiness” report.

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

## E2E test coverage (graph_and_crud_test.py)

The script **`tools/graph_and_crud_test.py`** runs against a live API and exercises CRUD plus SPARQL **only via POST /data-model/sparql**. It does not read the TTL file. Coverage that matches this cookbook:

| Step | What it does |
|------|----------------|
| **0** | POST /data-model/sparql (sites query) — confirms SPARQL is CRUD-only. |
| **1c–1e** | PUT /config, GET /config, then SPARQL for ofdd:PlatformConfig (Recipe 1). |
| **1a–1a5** | BACnet: server_hello, whois_range, point_discovery_to_graph; SPARQL for bacnet:Device and object names (Recipe 4). |
| **2–3** | Sites CRUD; GET /data-model/ttl. |
| **Later** | Equipment, points, import, export; SPARQL for site labels, equipment labels, point labels, equipment feeds (Recipes 2–3). |
| **SPARQL** | _sparql_site_labels(), _sparql_point_labels_for_site(), _sparql_equipment_labels_for_site(), _sparql_equipment_feeds_for_site() — all via POST /data-model/sparql. |

Run the e2e test after bootstrap or after changes to confirm config, data model, and BACnet discovery are queryable through the API. See [Technical reference — Unit tests](../appendix/technical_reference#unit-tests) and [Getting started](../getting_started).

---

## Saved queries (analyst/sparql/)

The repo includes sample `.sparql` files in **analyst/sparql/** (e.g. `01_points_rule_mapping.sparql`, `05_site_and_counts.sparql`). Run them via **POST /data-model/sparql/upload** with the file, or paste their contents into **POST /data-model/sparql** in Swagger. They match the FDD-oriented queries in Recipes 5–6 and are useful for validating the model before running the FDD loop or for debugging missing rule inputs.

---

## Related docs

| Topic | Page |
|-------|------|
| Data model flow | [Overview](overview) |
| AI-assisted tagging | [AI-assisted tagging](ai_assisted_tagging) |
| Rule inputs and Brick | [Expression rule cookbook](../expression_rule_cookbook) · [Fault rules overview](../rules/overview) |
| Grafana (SQL, not SPARQL) | [Grafana SQL cookbook](../howto/grafana_cookbook) |
| Dev reference | [Technical reference](../appendix/technical_reference) |
