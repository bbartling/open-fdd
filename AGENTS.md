# Agent Guidelines — Open-FDD

Guidance for AI assistants helping **mechanical engineers and building operators** use **Open-FDD**: an open-source edge analytics platform for smart building IoT. The primary task is **Brick tagging of the data model** so that BACnet discovery becomes a curated, rule-ready dataset for fault detection and diagnostics (FDD).

---

## What Open-FDD Is

Open-FDD ingests BACnet (and Open-Meteo) telemetry, stores it in TimescaleDB, and runs **Brick-model-driven** FDD rules defined in YAML. It exposes REST APIs and Grafana dashboards and is deployable behind the firewall. Rules refer only to Brick classes; the platform resolves them to time-series columns via the Brick TTL (sites, equipment, points). **Tagging** is the step where raw BACnet objects get a site, equipment, Brick type, rule_input, and optional feeds/fed-by relationships so that the FDD engine and dashboards have a correct, consistent model.

**Stack:** API (FastAPI), Grafana, TimescaleDB, BACnet scraper, weather scraper, FDD loop, diy-bacnet-server. Data model: **GET /data-model/export** (single route; optional `?bacnet_only=true`, `?site_id=...`) → LLM or human tags → **PUT /data-model/import**.

---

## Primary Task: Data Model Tagging for the Job

The mechanical engineer is running a **job** (a building or site) and needs the data model tagged so that:

1. **Points** are assigned to the right site and equipment, have correct Brick types and `rule_input` names, and (for points that must be logged long-term) have **`polling: true`** so the BACnet scraper writes them to TimescaleDB.
2. **Equipment relationships** (Brick `feeds` / `isFedBy`) are set from the engineer’s input so that `feeds_equipment_id` and `fed_by_equipment_id` are correct in the backend.
3. **Only points required for the job and for FDD rules** are marked for logging; the LLM should **tell the human which points will be logged** (polling true) so they can confirm the rules in **`analyst/rules/`** (and `open_fdd/rules/`) have the inputs they need.

### Export → Tag → Import Flow

1. **Export** — `GET /data-model/export` (or `?bacnet_only=true` for discovery-only). Returns a JSON array of points: BACnet discovery plus existing DB points. Unimported rows have `point_id: null`, `polling: false`, and null `site_id`/`equipment_id`/`brick_type`/`rule_input`.
2. **Tag with LLM** — Send the export JSON (and any site/equipment context from the engineer) to an LLM. The engineer provides **feeds / isFedBy** (which equipment feeds or is fed by which); the LLM incorporates these as `feeds_equipment_id` and `fed_by_equipment_id` in the **equipment** array for import.
3. **Polling for logging** — The LLM must set **`polling: true`** for every point that is **required to log data long-term** for this job (e.g. sensors and setpoints that FDD rules in `analyst/rules/` use). Set **`polling: false`** for points not needed for logging or rules. The LLM should **explicitly tell the human which points will be logged** (polling true) so they can verify that the rules they care about (bounds, flatline, expression, hunting, oa_fraction, erv_efficiency) have the required inputs.
4. **Import** — The mechanical engineer sends the completed JSON to **PUT /data-model/import** (body: `points` and optional `equipment`). The backend creates/updates points and equipment relationships, then rebuilds the RDF and TTL for scraping and FDD.

---

## Prompt to the LLM (for Brick Tagging)

Use this (or adapt it) when sending the export JSON to an external LLM:

- **Task:** You are helping tag BACnet discovery data for the Open-FDD building analytics platform. The input is a JSON array of points (BACnet device instance, object identifier, object name, and optionally existing point_id, site_id, equipment_id). Your job is to complete tagging so the mechanical engineer can import it into Open-FDD for this building/site.
- **Brick tagging:** For each point, set or suggest: `site_id` (UUID of the building/site), `external_id` (time-series key, e.g. from object name), `brick_type` (BRICK class, e.g. Supply_Air_Temperature_Sensor, Zone_Air_Temperature_Sensor), `rule_input` (name FDD rules use), and optionally `equipment_id`, `unit`.
- **Feeds relationships:** The mechanical engineer will provide which equipment **feeds** or **is fed by** which other equipment (Brick `feeds` / `isFedBy`). You will incorporate their `feeds_equipment_id` and `fed_by_equipment_id` (equipment UUIDs) into the import payload. The import body has a separate **`equipment`** array: each item has `equipment_id` and optionally `feeds_equipment_id` and `fed_by_equipment_id`. Use this so the backend can persist those relationships in the data model and TTL.
- **Polling (logging):** Set **`polling: true`** for every point that must be **logged long-term** for this job — i.e. points that the FDD rules in `analyst/rules/` (and the job) depend on (e.g. temperatures, setpoints, flow, status). Set **`polling: false`** for points not needed for logging or rules. In your response, **tell the human which points will be logged** (polling true) so they can confirm the rules they are trying to accomplish have the required data.
- **Rules context:** Open-FDD rules are in **`analyst/rules/`** (and `open_fdd/rules/`). They are Brick-model driven: each rule declares Brick class inputs (e.g. Supply_Air_Temperature_Sensor, Outside_Air_Temperature_Sensor). Rule types include bounds, flatline, expression, hunting, oa_fraction, erv_efficiency. Tagging should align point `brick_type` and `rule_input` so these rules can resolve their inputs from the Brick TTL.
- **Iteration:** Work with the mechanical engineer until they are satisfied with the tagging, relationships, and which points are set for logging.
- **Output:** Return the completed JSON: the **points** array (with polling set per above) and, if applicable, the **equipment** array with `equipment_id`, `feeds_equipment_id`, and `fed_by_equipment_id`. The engineer will send this to **PUT /data-model/import** so the backend creates/updates points and equipment relationships and refreshes the in-memory data model and TTL for BACnet scraping and FDD.

---

## Where to Look (ordered)

1. **docs/** — Overview, BACnet (discovery → point_discovery_to_graph → export), data modeling (sites, equipment, points), **AI-assisted tagging** ([docs/modeling/ai_assisted_tagging.md](docs/modeling/ai_assisted_tagging.md)), rules, API reference.
2. **docs/api/platform.md** — REST API (sites, points, equipment, data-model export/import, TTL, SPARQL).
3. **docs/rules/overview.md** — Rule types, Brick-only inputs, `analyst/rules/`, hot reload.
4. **docs/expression_rule_cookbook.md** — Expression rule recipes (Brick inputs).
5. **analyst/rules/** — Project rule YAML (sensor_bounds, sensor_flatline, etc.); FDD loop loads from here.
6. **open_fdd/rules/** — Built-in rule examples.
7. **docs/appendix/technical_reference.md** — Data model API, export/import workflow, LLM tagging, unit tests, BACnet scrape, bootstrap.
8. **open_fdd/** — Source; docstrings are ground truth.

---

## Capabilities

- **Platform:** REST CRUD for sites, equipment, points; **GET /data-model/export** (unified; optional bacnet_only, site_id), **PUT /data-model/import** (points + optional equipment feeds/fed_by); TTL, SPARQL.
- **Tagging workflow:** Export JSON → LLM or human adds site_id, brick_type, rule_input, equipment_id, unit, polling, and equipment relationships → import.
- **Engine:** Load YAML rules from `analyst/rules/`, run RuleRunner against DataFrames. Resolution is **100% Brick-model driven** (no `column` in YAML); column_map from Brick TTL via SPARQL.
- **Rules:** bounds, flatline, expression, hunting, oa_fraction, erv_efficiency (see docs/rules and analyst/rules).
- **Reports:** summarize_fault, print_summary, get_fault_events, all_fault_events (when dependencies available).

---

## Non-capabilities (strict)

- **Do not invent columns.** Only use columns that exist in the input DataFrame or that rules add.
- **Do not hallucinate rule names.** Rule names and flags come from YAML. Check `open_fdd/rules/` or `analyst/rules/`.
- **Do not claim a function exists** unless it appears in `open_fdd/**` or the docs.
- **Do not assume optional dependencies** (rdflib, python-docx, matplotlib) are installed unless stated.

---

## Data Contracts

### Export (GET /data-model/export)

- Returns a list of objects with: `point_id` (null if unimported), `bacnet_device_id`, `object_identifier`, `object_name`, `site_id`, `site_name`, `equipment_id`, `equipment_name`, `external_id`, `brick_type`, `rule_input`, `unit`, **`polling`** (default false for unimported). Optional query: `bacnet_only=true`, `site_id=...`.

### Import (PUT /data-model/import) — exact schema

The API accepts **only** two top-level keys. **Do not** send `sites`, `equipments`, or `relationships`.

- **`points`** (array, required): Each row is a point to create or update. To **create**, omit `point_id` and set `site_id`, `external_id`, `bacnet_device_id`, `object_identifier` (and optionally `object_name`, `equipment_id`, `brick_type`, `rule_input`, `unit`, `polling`). To **update**, set `point_id` and any fields to change. **`site_id` and `equipment_id` must be real UUIDs** from GET /sites and GET /equipment — the backend does not create sites or equipment on import.
- **`equipment`** (array, optional): Updates **existing** equipment with Brick feeds/isFedBy. Each item: `{ "equipment_id": "<uuid>", "feeds_equipment_id": "<uuid> | null", "fed_by_equipment_id": "<uuid> | null" }`. Example: AHU feeds VAV → `{ "equipment_id": "<ahu-uuid>", "feeds_equipment_id": "<vav-uuid>" }`; VAV fed by AHU → `{ "equipment_id": "<vav-uuid>", "fed_by_equipment_id": "<ahu-uuid>" }`.

**Workflow for LLM output:** (1) Create site and equipment via POST /sites and POST /equipment. (2) GET /sites and GET /equipment to obtain UUIDs. (3) Replace any placeholder site/equipment IDs in the LLM’s JSON with these UUIDs. (4) Send only `points` and `equipment` to PUT /data-model/import (no `sites`, `equipments`, or `relationships`).

**diy-bacnet ready (points to poll):** The list of BACnet points to poll (e.g. for the BACnet scraper or diy-bacnet app) is **GET /data-model/export** with rows where **`polling === true`**; each row has `bacnet_device_id` and `object_identifier`. SPARQL runs over the Brick+BACnet graph and can return all BACnet devices and point addresses, but **polling** is stored in the DB only, so to get “devices + addresses where polling is true” use the export response filtered by `polling: true`.

### Engine

- Input DataFrame: columns from Brick/column_map, optional `timestamp`; numeric dtypes for sensor/command columns.
- Output: fault flag columns `*_flag` (boolean, True = fault), one per rule.

---

## Glossary

| Term | Meaning |
|------|---------|
| **flag** | Output column name; boolean, True = fault |
| **episode** | Contiguous timestamps where a flag is True |
| **rule_input** | Key FDD rules use; variable in expression; often BRICK class; set per-point in tagging |
| **column_map** | Built from Brick TTL (SPARQL); maps Brick class to DataFrame column. Rules declare only Brick classes. |
| **external_id** | Time-series key (e.g. BACnet object name); set in tagging |
| **polling** | If true, BACnet scraper logs this point to TimescaleDB. Set true only for points needed for the job and for rules. |
| **feeds_equipment_id** / **fed_by_equipment_id** | Brick relationships: this equipment feeds / is fed by that equipment (UUIDs). Set via import `equipment` array. |

---

## Public API

- **Engine:** RuleRunner, load_rule, load_rules_from_dir, bounds_map_from_rule
- **Reports:** summarize_fault, summarize_all_faults, print_summary, get_fault_events, all_fault_events
- **Brick:** resolve_from_ttl, get_equipment_types_from_ttl (when rdflib available)
- **Data model:** GET /data-model/export, PUT /data-model/import, GET /data-model/ttl, POST /data-model/sparql
