# SCOPE — open-fdd, rebuilt on a Brick-conformant SurrealDB substrate

Status: **draft / design**. This is the scope for the next-generation open-fdd: an
open-source **supervisory fault detection & diagnosis (FDD)** platform for buildings,
rebuilt so that the equipment model **is a conformant [Brick](https://brickschema.org)
model**, telemetry is a first-class time-series plane, faults are deterministic,
auditable, offline-capable rules, and a future **agent mode** ([Rig](https://docs.rig.rs)
over SurrealDB vectors) reasons over the same store. The same binary runs on one
building/station at the edge and across a portfolio in the cloud.

The domain (equipment, points, telemetry, faults, RCx) is the product. The substrate
ideas (single SurrealDB store; an inject plane; a Rhai-decision + DataFusion-compute
rule engine; an access gate with audit/undo; edge→cloud sync; an agent over vectors)
are borrowed, but this doc stands on its own — it is **not** a generic-platform doc
with FDD bolted on.

## The one hard requirement: MUST match Brick

The equipment/point/location model is **not "tags that resemble Brick."** It is a
**Brick-conformant model**:

1. Every modelled entity is an instance of a **real Brick class** (e.g.
   `brick:Air_Handling_Unit`, `brick:Supply_Air_Temperature_Sensor`).
2. Every relationship is a **real Brick object property** (`brick:hasPoint`,
   `brick:feeds`, `brick:hasPart`, `brick:hasLocation`, …) with Brick's inverse
   semantics preserved.
3. Units are **QUDT** via `brick:hasUnit` (e.g. `unit:DEG_F`).
4. A Point binds to its telemetry the **Brick-native way**: `ref:hasExternalReference
   → ref:TimeseriesReference` carrying `ref:hasTimeseriesId` and `ref:storedAt`
   ([Ref Schema](https://ref-schema.brickschema.org/),
   [Brick timeseries storage](https://docs.brickschema.org/metadata/timeseries-storage.html)).
5. The model **round-trips to Brick Turtle (`.ttl`)** and **validates against Brick's
   SHACL shapes** — a real Brick model imports and re-exports with no semantic loss,
   and an invalid model is rejected at the gate.

Conformance is a contract, not a nicety: it is what lets open-fdd interoperate with
existing Brick models, SPARQL tooling, and other Brick-aware systems, and it is what
makes "bind a rule to every `brick:Supply_Air_Temperature_Sensor` that feeds this
AHU" a portable query instead of a bespoke one. **Where this doc and the Brick
ontology disagree, Brick wins.**

## Principles

1. **Brick-conformant or it doesn't ship.** The graph is a faithful Brick model
   (classes, relationships, units, timeseries refs), TTL-round-trippable and
   SHACL-validated. See *The Brick model* below.
2. **One binary, edge to cloud.** Same build on a building controller, a Windows box,
   or the cloud. Difference is configuration (single station vs. portfolio).
3. **Faults fire offline.** The rule/fault runtime is embedded and needs no cloud.
4. **SurrealDB is the single store.** Graph (the Brick model), time-series
   (telemetry), vector (RAG/agent memory), document (config), auth, live queries, and
   change feeds in one engine.
5. **Telemetry is data-plane, append-only.** Millions of samples never enter the
   audit/undo/command path; they append and age out.
6. **Commands cross the gate; reads are SurrealDB-native.** Every mutation is
   audited/undoable with a correlation id; reads run on a scoped SurrealDB session
   enforced by row-level permissions. **The agent is a scoped principal too** — its
   writes cross the same gate.
7. **Python is the oracle, not the runtime.** Existing open-fdd Python rules are the
   golden reference; each Rust/Rhai/SQL rule is validated against them with fixtures.
   Python never runs on the edge hot path.

## Architecture

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                 FRONTEND                                        ║
║   Dashboards · RULE LAB (author faults) · RCx reports · AGENT chat (Rig)         ║
║   React · Vite · TanStack · Tailwind · shadcn/ui · Module Federation             ║
╚════════════════════════════════════╤═════════════════════════════════════════╝
            WebSocket (live faults/telemetry) │ + JSON-RPC (control)
                                       ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                          ACCESS GATE · one identity                              ║
║  COMMANDS (author rule · model Brick entity · write config) ─► authN · grants    ║
║                        · SHACL/Brick validation · audit/undo · correlation-id    ║
║  READS (charts · live faults · Brick queries · agent retrieval) ─► scoped session ║
╚════════════════════════════════════╤═════════════════════════════════════════╝
                                      ▼
┌─────────────── FDD ENGINE ──────────────┐   ┌──── AGENT MODE (future) ───────┐
│ bind rule to points via a BRICK QUERY    │   │  RIG agent (rig-core)          │
│ (class + relationship), not point ids    │   │  reason · plan · tool-call     │
│                                          │   │  retrieval = SurrealDB VECTOR  │
│ DATAFUSION+Arrow  RHAI       CONFIRMATION │   │  tools = Brick query ·         │
│ window rollups ─► decision ─► min_elapsed │   │   telemetry historian ·        │
│ (avg/min/max)  │  (G36)    │  min_true_rows│   │   fault history · RCx/docs     │
│ SQL rules ─────┘  invoke() │  ─► FAULT     │   │  writes ─► ACCESS GATE         │
│                            │   +trace(why) │   └────────────┬──────────────────┘
└──────────────────┬───────────────────────┘                │
                   ▼                                         ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                              SURREALDB CORE                                      ║
║  GRAPH = the BRICK MODEL: entity(class) ─[hasPoint|feeds|hasPart|hasLocation]─►  ║
║          + brick_class hierarchy (subClassOf) for subclass inference             ║
║  TIME-SERIES = telemetry keyed by ref:hasTimeseriesId                             ║
║  VECTOR = embeddings (docs · faults · Brick context) — RAG + agent memory         ║
║  DOCUMENT = rule defs · RCx · dashboards   auth · live queries · CHANGEFEED        ║
╚════════════════════════════════════════════════════════════════════════════════╝

  ── INJECT PLANE (field → edge store · the pre-sync gate) ────────────────────────
     BACnet / Niagara station ─┐
     (discover · read · poll)  │  bridge ─► preprocess (decimate→filter→enrich)
     MQTT devices ─────────────┴──────────► append `telemetry`
     map: sample → { series = ref:hasTimeseriesId of the Brick Point, at, value }
     discovery proposes Brick entities + points (operator confirms class) → graph

  ── SYNC PLANE (station → portfolio) ─────────────────────────────────────────────
     EDGE SurrealDB ══[ CHANGEFEED → SurrealDB native sync / shipper ]══► CLOUD
       telemetry/faults: append-only, partitioned by station → no conflict
       Brick model + rules: ownership + last-write-wins + audit tiebreak

        EDGE = one building/station                 CLOUD = portfolio / fleet
     (faults fire offline, local dashboard)    (cross-site RCx, fleet rollups, agent)
```

## Key technologies — use case, what it replaces, and the Python migration path

How each technology is used, what played that role in today's (Python) open-fdd, and
what existing Python is reused as an oracle and migrated over time. The migration
discipline is constant: **Python stays the reference; each component is validated
against Python fixtures before it replaces it.**

| Technology | Use case in this design | What it was in open-fdd (Python) | Reused / migration path |
| --- | --- | --- | --- |
| **SurrealDB** | Single store: Brick graph + telemetry time-series + vectors + config + auth + change feeds | No single store — pandas/Arrow in memory + files; separate dashboards/historian | New foundation. Python loaders/ETL become importers; historian boundary keeps reads Arrow-shaped |
| **Brick + Ref Schema (RDF/SHACL/QUDT)** | Conformant equipment model; rules bind to Brick queries | BRICK/RDF + SPARQL work (roadmap milestone 6), looser tag/metadata use | Reuse existing Brick models / TTL via lossless import; SPARQL parity becomes a CI check |
| **DataFusion + Arrow** | Vectorised window rollups; SQL fault rules; the compute engine | PyArrow compute + optional DataFusion SQL rules | DataFusion SQL rules port almost directly; PyArrow rule logic re-expressed and parity-tested |
| **Rhai** | Embedded, sandboxed fault *decision* + rule composition (offline) | Python rule functions (`def high_sat(table,cfg)…`) | Python is the oracle; G36 decision logic re-authored in Rhai, validated vs Python fixtures |
| **Fault confirmation (`min_elapsed_minutes`/`min_true_rows`)** | Debounce/hysteresis before a fault is recorded | Same config mechanics, in Python | Mechanics carried over 1:1; validated against Python outputs |
| **Inject pipeline (decimate→filter→enrich)** | Field→edge acquisition + pre-sync gate | `openfdd-commission` (BACnet discovery/poll), MQTT, edge bridge | BACnet/Niagara drivers reused as inject sources pointed at the append endpoint |
| **SurrealDB CHANGEFEED + shipper / native sync** | Edge→cloud replication, partition-by-station | Deferred in open-fdd (#334) | New capability; no Python equivalent to migrate |
| **Access gate (audit/undo/correlation-id)** | One mutation chokepoint; SHACL validation; "why did this fire" trace | Ad-hoc; no unified audit/undo/trace | New; trace consumes the same correlation id ingest/gate mint |
| **Rig (`rig-core`) + SurrealDB vectors** | Future agent mode: Brick-grounded RAG + tool-calling over the store | `openfdd-mcp-rag` (MCP + doc search) | MCP-RAG capability generalised into the Rig agent; embeddings move into SurrealDB |
| **React/Vite/TanStack/shadcn + Module Federation** | Dashboards, Rule Lab, RCx, agent chat | Existing browser Rule Lab + dashboard (TS) | Rule Lab front-end reused; points at the gated rule API |
| **Python (pandas/pyarrow + ML)** | **Oracle + out-of-process ML extension** — never on the edge hot path | The whole runtime | Stays as golden-fixture reference and a scoped ML extension; not embedded in the edge binary |

## The Brick model — the heart of the system

Brick is RDF/OWL with a Turtle serialization, a deep **class hierarchy**, **inverse
relationships**, **QUDT units**, and **SHACL** validation. SurrealDB is a property/
graph store, not an RDF triple store with a reasoner. "MUST match Brick" therefore
means we **carry Brick's semantics explicitly** rather than assume an RDF engine
provides them. Four mappings make the model conformant.

### 1. Entities are Brick-class instances — SCHEMAFULL, typed class reference

The core Brick tables are **`SCHEMAFULL`**, not schemaless: a building model is a
constrained ontology, and the store should refuse anything that isn't conformant
rather than accept free-form documents. `class` is a **typed record link** to a
`brick_class` row (not a bare string), so an entity literally cannot carry a class
that isn't in the loaded ontology.

```surql
DEFINE TABLE entity SCHEMAFULL;                          -- a Brick instance (equipment/point/location/…)
DEFINE FIELD class   ON entity TYPE record<brick_class>; -- typed link → the ontology, not a loose CURIE
DEFINE FIELD label   ON entity TYPE string;
DEFINE FIELD station ON entity TYPE string;              -- edge partition (one building/station)
DEFINE FIELD unit    ON entity TYPE option<record<qudt_unit>>;  -- QUDT term for Points (brick:hasUnit)
DEFINE INDEX entity_station_class ON entity FIELDS station, class;
```

`class` resolves to a real ontology row by construction, and `unit` to a QUDT term.
The instance is a SurrealDB record, but its identity is Brick: it has a class IRI and
participates in Brick relationships.

#### A lossless RDF sidecar — so TTL round-trip never drops detail

The operational tables above hold the **projected, queryable subset** open-fdd
actually runs on (class, station, unit, relationships, timeseries refs). They are
deliberately *not* a complete RDF representation — a SCHEMAFULL projection cannot
carry blank nodes, datatype literals, language tags, repeated/annotated refs, or
non-core Brick annotations. To keep the *"MUST round-trip to Brick TTL"* contract
**lossless**, every import also lands the raw model in a sidecar:

```surql
DEFINE TABLE brick_assertion SCHEMAFULL;            -- one row per imported RDF triple (lossless)
DEFINE FIELD subject   ON brick_assertion TYPE string;   -- IRI or _:blank
DEFINE FIELD predicate ON brick_assertion TYPE string;
DEFINE FIELD object    ON brick_assertion TYPE string;   -- IRI / literal (with datatype + lang preserved)
DEFINE FIELD graph     ON brick_assertion TYPE string;   -- source model / named graph
DEFINE INDEX brick_assertion_spo ON brick_assertion FIELDS subject, predicate, object;
```

Flow: **import** writes `brick_assertion` (lossless) **and** projects the operational
subset into `entity` / relations / timeseries refs; **export** regenerates TTL from
`brick_assertion`, reconciled with any operational edits made since import. This is
the split that lets the graph tables stay lean and typed while the round-trip stays
faithful — the projection is for *running*, the sidecar is for *fidelity*.

### 2. The Brick class hierarchy is loaded, so subclass inference works

The single thing a property graph does **not** give you for free is RDFS subclass
reasoning — "give me all `brick:Temperature_Sensor`" must also match
`brick:Supply_Air_Temperature_Sensor` (a subclass). We make this native by loading
the Brick ontology's class graph:

```surql
DEFINE TABLE brick_class SCHEMALESS;            -- one row per Brick class
DEFINE FIELD curie ON brick_class TYPE string;  -- "brick:Temperature_Sensor"
-- subClassOf as graph edges, straight from the Brick ontology:
--   brick_class:Supply_Air_Temperature_Sensor ->subClassOf-> brick_class:Air_Temperature_Sensor -> …
RELATE brick_class:$child->subClassOf->brick_class:$parent;
```

A query for "all Temperature_Sensors under AHU-1" walks the class closure and the
Brick relationship in one SurrealQL graph traversal — the property-graph equivalent
of a SPARQL query over an inferred model. For speed, the transitive subclass closure
is materialised (a `subclass_of_closure` table refreshed when the ontology version
changes), so rule binding is an index lookup, not a recursive walk per evaluation.

### 3. Relationships are Brick object properties, inverses preserved

Each Brick object property is a **typed, enforced `RELATION` table** — not an
untyped edge — with `in`/`out` constrained to `entity` and `ENFORCED` so a dangling
or mistyped edge is rejected at write. The relation table definitions are
**generated from the Brick ontology** (one per supported object property), not
hand-listed, so the closed set tracks the pinned Brick version automatically:

```surql
-- generated per Brick object property (hasPoint, feeds, hasPart, hasLocation, …):
DEFINE TABLE hasPoint TYPE RELATION IN entity OUT entity ENFORCED;
DEFINE TABLE feeds    TYPE RELATION IN entity OUT entity ENFORCED;
-- domain/range narrowing (e.g. hasPoint OUT must be a brick:Point subclass) is
-- checked at the gate against the ontology + SHACL; see Conformance below.

RELATE entity:ahu1->hasPoint->entity:sat_sensor;   -- brick:hasPoint
RELATE entity:ahu1->feeds->entity:vav_3;            -- brick:feeds
```

Brick relationships are inverse-paired (`hasPoint`/`isPointOf`, `feeds`/`isFedBy`,
`hasPart`/`isPartOf`, `hasLocation`/`isLocationOf`). We store the **canonical
direction once** as the enforced relation and traverse the inverse with SurrealDB's
reverse edge syntax (`entity:sat_sensor<-hasPoint<-entity`), so there is no
double-write to keep consistent. On **TTL export** the inverse triples are emitted as
Brick expects; on **import** an inverse triple is normalised back to its canonical
edge. The closed set of supported relations is the Brick version we target (pinned —
see open questions).

### 4. A Point binds to telemetry the Brick-native way

This is the conformant seam between the **graph** and the **time-series plane**. Brick
already standardises it: a Point carries `ref:hasExternalReference` to a
`ref:TimeseriesReference` whose `ref:hasTimeseriesId` is the key of the data in some
store ([timeseries storage](https://docs.brickschema.org/metadata/timeseries-storage.html)).

```turtle
:sat_sensor a brick:Supply_Air_Temperature_Sensor ;
    brick:hasUnit unit:DEG_F ;
    ref:hasTimeseriesReference [ a ref:TimeseriesReference ;   # specific sub-property
        ref:hasTimeseriesId "ahu1.sat" ;
        ref:storedAt :openfdd_surreal ] .
```

The reference is a **first-class record**, not an embedded blob — so it can be
queried, indexed, and shared (a BACnet object reference and a timeseries reference can
coexist on the same point), and import/export preserves the exact property used:

```surql
DEFINE TABLE ts_ref SCHEMAFULL;                         -- a ref:TimeseriesReference instance
DEFINE FIELD timeseries_id ON ts_ref TYPE string;       -- ref:hasTimeseriesId — the telemetry series key
DEFINE FIELD stored_at     ON ts_ref TYPE option<string>;-- ref:storedAt (database/source)
DEFINE INDEX ts_ref_tsid   ON ts_ref FIELDS timeseries_id UNIQUE;
-- point → ref as an enforced relation; the property used is preserved for round-trip:
DEFINE TABLE hasExternalReference TYPE RELATION IN entity OUT ts_ref ENFORCED;
DEFINE FIELD property ON hasExternalReference TYPE string; -- "ref:hasTimeseriesReference" | "ref:hasExternalReference"
```

Brick exposes a **generic** `ref:hasExternalReference` and a **specific**
`ref:hasTimeseriesReference` (a sub-property of it) ([Ref Schema](https://ref-schema.brickschema.org/)).
We store which property the source used (`property`) so export emits the same one —
generic stays generic, specific stays specific — and a BACnet/IFC external reference
uses the same table with a different target type.

The `ts_ref.timeseries_id` **is** the `series` key of the telemetry plane. So the
Brick model says *what a point means* and *where its data lives*, and the telemetry
table holds the samples under that same id — no parallel point registry, no drift.

### Conformance: validation + round-trip (the contract)

- **SHACL validation at the gate.** Modelling/editing a Brick entity is a command;
  the gate validates the write against Brick's SHACL shapes (class exists; the
  relationship's domain/range are legal for the two entities' classes; required
  properties present; unit is a QUDT term). Invalid models are **rejected**, not
  stored. Full SHACL runs in CI/import; a fast native subset runs on the hot
  per-write path (open question 4).
- **Turtle round-trip.** `import` parses a Brick `.ttl` into `entity` rows +
  relationship edges + timeseries refs; `export` regenerates `.ttl` (canonical +
  inverse triples, units, refs). A conformance test asserts `export(import(ttl)) ≡
  ttl` semantically for the Brick reference models — this is the objective "matches
  Brick" gate in CI.
- **SPARQL-style queries.** Rule binding and dashboards query the graph by class +
  relationship + subclass closure. We do **not** run a SPARQL engine inside SurrealDB;
  we compile the small set of query shapes we need to SurrealQL graph traversals.
  (A full SPARQL endpoint over an exported model is an optional cloud add-on.)

## Telemetry plane — first-class time-series, keyed by the Brick timeseries id

A reading is not a document. Telemetry is a dedicated append-only plane, keyed by the
Point's `ref:hasTimeseriesId`:

```surql
DEFINE TABLE telemetry SCHEMALESS;              -- data plane, append-only
DEFINE FIELD series  ON telemetry TYPE string;  -- == ref:hasTimeseriesId of the Brick Point
DEFINE FIELD at      ON telemetry TYPE datetime;-- MEASUREMENT instant (not write time)
DEFINE FIELD value   ON telemetry TYPE number;
DEFINE FIELD station ON telemetry TYPE string;  -- edge partition
DEFINE INDEX telemetry_station_series_at ON telemetry FIELDS station, series, at;
-- scoped read perms; create/update/delete NONE on scoped sessions (appends on owner handle)
```

- **Bucket on `at`** (measurement time), never write time — the trend-collapse bug
  that bites any "bucket on row-created" design.
- **Deterministic id from `(series, at)`** so re-poll, backfill, and sync-replay are
  idempotent no-ops.
- **Rollups behind a historian boundary** are the first scale lever (pre-aggregated
  `telemetry_rollup` per grain); an external TSDB is an optional datasource behind the
  same boundary, never required.
- **Unit/quantity live on the Brick Point** (`brick:hasUnit`), not on every sample —
  rows stay `{series, at, value}` lean.

### The historian boundary — SurrealDB rows → Arrow/DataFusion batches

open-fdd is **Arrow-native**, but the store is SurrealDB. The seam that bridges them
is the **historian boundary**, defined early because it's where a lot of performance
and correctness lives. It is a single read interface — *"give me series S (or a
Brick-resolved set), window [t0,t1], grain G"* — that returns **Arrow `RecordBatch`es**
ready for DataFusion, and decides behind the caller's back how to produce them:

- **Paged range-scan → Arrow.** For raw/live-tail reads it issues a filtered SurrealQL
  range scan (`WHERE station=$s AND series=$x AND at BETWEEN $t0 AND $t1 ORDER BY at`)
  over the `telemetry_station_series_at` index, **paged**, and assembles columnar Arrow
  batches (not row-by-row into the engine).
- **Rollup table for coarse grains.** Above a threshold it reads `telemetry_rollup`
  instead of raw rows; epoch-aligned to the engine's grain so a chart bucket and a rule
  bucket line up exactly.
- **Optional derived Arrow/Parquet cache.** Hot windows (a rule's recent evaluation
  window, a dashboard's visible range) can be materialised to a **local Arrow/Parquet
  cache** so repeat reads skip SurrealDB entirely — and this is the same seam an
  external TSDB (TimescaleDB as a DataFusion `TableProvider`) plugs into if SurrealDB's
  time-series read path stops keeping up. No rule or chart changes when the source
  swaps.

Defining this boundary now (not after volume bites) keeps the rest of the system
talking **Arrow**, not SurrealQL, so the swap surface is one interface.

## FDD engine — rules bind to Brick, decide in Rhai, confirm, record a fault

The decisive design choice: **a rule does not name point ids — it names a Brick
query.** A G36 rule says "for each `brick:Air_Handling_Unit`, take its
`brick:Supply_Air_Temperature_Sensor` and `brick:Mixed_Air_Temperature_Sensor` via
`brick:hasPoint`…". The engine resolves that query (with subclass closure) to concrete
points and their `hasTimeseriesId`s, then runs the math. This is what makes a rule
**portable across buildings** — the whole point of modelling in Brick.

Three stages, mirroring open-fdd's existing mechanics:

1. **DataFusion + Arrow** computes window rollups over the bound series (avg/min/max
   over N minutes). Heavy vectorised math lives here. Pure-threshold faults may be
   expressed directly as **DataFusion SQL rules** (ported from today's open-fdd).
2. **Rhai** makes the deterministic decision (G36 logic, economizer/SAT/valve-hunting
   faults), composes sub-rules via `invoke()`, and is sandboxed (bounded ops, no I/O,
   fail-closed).
3. **Fault confirmation** applies open-fdd's `min_elapsed_minutes` / `min_true_rows`
   plus debounce/hysteresis, then records a **fault** as an audited insight with a
   **per-fault trace** ("which points, which window values, why it fired").

**Rules do not fire per sample.** At telemetry volume, running rule evaluation on
every appended row would melt the engine. Instead ingest **marks dirty series/windows**
as samples land (a cheap `(series, bucket)` dirty-set), and a **scheduler batches**
DataFusion runs over those dirty windows on a tick — so evaluation cost scales with
*changed windows*, not sample count, and DataFusion sees real Arrow batches (via the
historian boundary) rather than one-row calls. A rule may also be run on demand
(dry-run, manual re-check). The after-write hook path is reserved for **low-volume
config** changes (e.g. a rule edit triggers a re-evaluation), never for telemetry.

Faults are recorded back to SurrealDB and published on live queries (the dashboard's
realtime feed); a **dry-run** path
runs a draft rule against real history with no side effects (the Rule Lab preview).

## Faults, RCx, and traces

- A **fault** is an insight record linked to the Brick entity it concerns (so "all
  faults for AHU-1" / "all economizer faults across the portfolio" are graph queries).
- **RCx reports** are documents assembled from fault history + Brick context, the
  cloud-side retro-commissioning surface.
- **Traces** answer "why did this fire": the Rhai evaluation emits a span tree
  (sub-rules, window values, decision), correlated by id from the same gate/ingest
  correlation id that stamps audit and faults.

## Inject plane — field to edge store, and Brick discovery

Acquisition (BACnet/Niagara discovery + polling, MQTT) lands samples on the edge
`telemetry` table after a preprocess pipeline (decimate→filter→enrich). The mapping
turns a sample into `{ series = the point's hasTimeseriesId, at, value }`. **Discovery
also proposes Brick entities**: a BACnet discovery run suggests candidate equipment
and points with candidate Brick classes; an operator confirms/edits the class (the
one human step Brick conformance requires), and the confirmed entities + timeseries
refs land in the graph. The capability decision is taken once (at subscribe / per
batch), not per sample; appends bypass the command gate but stay on the station
partition.

## Sync plane — station to portfolio

Edge→cloud movement replicates the **store**, not the field. Telemetry and faults are
append-only and **partitioned by station**, so two edges never write the same row and
reconciliation is ordering+dedup, not merge. The Brick model and rule definitions are
the real conflict surface, handled by ownership + last-write-wins + audit tiebreak.
Capture uses SurrealDB **CHANGEFEED**; transport is a shipper. (Native SurrealDB
edge-sync, if/when confirmed GA for the self-hosted engine, can replace the shipper —
but the partition-by-station conflict model stays either way, because sync moves bytes
and does not resolve domain conflicts.)

## Access gate, audit, undo

Every command (author a rule, model/edit a Brick entity, write config, **apply an
agent proposal**) crosses the gate: authenticate → capability grant → **Brick/SHACL
validation** → capture before/after for audit + undo → mint correlation id → apply.
Reads (charts, live faults, Brick queries, agent retrieval) run on a scoped SurrealDB
session under row-level permissions. Telemetry appends are data-plane and never
produce audit/undo per sample.

## Agent mode (future) — Rig over SurrealDB vectors

A forward-looking mode: an LLM agent an operator (or the Rule Lab) can ask in natural
language — *"why is AHU-3 faulting this week?"*, *"draft a stuck-damper rule for the
rooftop units"*, *"summarise RCx findings for site 7"* — that reasons over **the same
SurrealDB store** the rest of the system uses. Built on **[Rig](https://docs.rig.rs)**
(`rig-core`), a Rust LLM-agent framework with a **SurrealDB vector-store integration**
(`rig-surrealdb`), so embeddings live **beside** the Brick model, telemetry, and
faults — no second vector database (principle 4).

```
  ── AGENT MODE (future) · Rig over SurrealDB ─────────────────────────────────────
     Operator / Rule Lab ──ask──►  RIG AGENT  (rig-core · Claude/LLM)
                                      │  reason → plan → call tools → ground → answer
                                      │
        ┌─────────────┬──────────────┼──────────────┬───────────────┐
        ▼             ▼              ▼              ▼               ▼
   VECTOR SEARCH  BRICK QUERY   TELEMETRY      FAULT HISTORY    RCx / DOCS
   (SurrealDB     (graph: class  (window        (insights by     (RAG over
    embeddings:    + relationship rollups via    Brick entity)    G36 guide,
    docs·faults·   + subclass     DataFusion)                     manuals)
    Brick context) closure)
        └─────────────┴──────────────┬──────────────┴───────────────┘
                                     ▼
                    grounded answer  +  proposed action
              (draft a rule · explain a fault · suggest an RCx measure)
                                     │
                 any WRITE ─────────►│  ACCESS GATE  (capability · SHACL ·
                                     ▼   audit · undo · correlation-id)
                          the agent is a SCOPED PRINCIPAL, like a user
```

Design points, each load-bearing:

- **Embeddings live in SurrealDB beside the data.** Vector search is SurrealDB-native,
  so retrieval can be **Brick-filtered** (only this site's AHUs; only economizer
  faults) by joining a vector hit back to its Brick entity — RAG that knows the
  building's structure, not just text similarity.
- **The agent's tools are the system's existing read surfaces.** Brick graph query,
  the telemetry historian, fault history, RCx/doc RAG — the agent calls the same
  capabilities the FDD engine and dashboards use. No privileged backdoor.
- **Reads are free; writes cross the gate.** The agent answers and *proposes* (a rule
  draft, a model edit, an RCx note); applying any of it is a gated, audited, undoable
  command — the agent holds capability grants like any principal, and a proposed rule
  still runs **dry-run against real history** before a human commits it.
- **Edge or cloud.** Lightweight retrieval/grounding can run at the edge; heavier
  multi-step reasoning is a cloud add-on. Either way it reads the same synced store.

This is where today's MCP-RAG capability lands, generalised from doc search to a
Brick-grounded agent. It is explicitly **future** — the deterministic FDD engine is the
product; the agent is an assist layer over it, never the thing that silently changes
config.

## Edge and cloud profiles

- **Edge** — one station, single SurrealDB namespace, faults fire offline, local
  dashboard, lightweight agent retrieval, sync up when connected.
- **Cloud** — portfolio (namespace-per-tenant or per-site), fleet RCx, cross-site
  rollups, full agent reasoning, optional SPARQL endpoint.

## Build order (smallest load-bearing first)

1. **Brick model core** — SCHEMAFULL `entity` (typed `class`) + `brick_class`
   hierarchy + ontology-generated **enforced relation** tables + first-class `ts_ref` +
   the lossless `brick_assertion` sidecar; TTL import/export; SHACL validation in CI.
   The conformance gate. *Nothing else is correct until this is.*
2. **Telemetry plane** — `telemetry` table keyed by `hasTimeseriesId`, bucket on
   `at`, deterministic id, scoped perms.
3. **Inject** — BACnet/Niagara/MQTT acquisition → preprocess → telemetry; discovery
   proposes Brick entities for operator confirmation.
4. **FDD engine** — DataFusion window + Rhai decision + fault confirmation; rules bind
   via Brick queries; dry-run; record faults + traces. Validate each rule against the
   Python oracle with fixtures.
5. **Frontend** — dashboards, Rule Lab, RCx.
6. **Sync + cloud** — CHANGEFEED shipper, portfolio profile, fleet RCx.
7. **Scale levers** — telemetry rollups behind the historian boundary; optional
   external TSDB / SPARQL endpoint.
8. **Agent mode (Rig)** — embeddings in SurrealDB; Rig agent with Brick-query /
   historian / fault-history / RAG tools; gated writes for proposals. Built last, over
   a store that already works.

## Open questions

1. **Brick version pin.** Which Brick release (1.3 / 1.4) defines our closed set of
   classes, relationships, and the `ref:` schema — and the ontology-refresh process
   when it bumps (re-materialise the subclass closure).
2. **SHACL on the hot path.** Full pyshacl-grade validation in CI/import vs. a native
   fast subset at the gate per write — which checks are mandatory inline vs.
   deferred.
3. **Subclass-closure materialisation.** Refresh trigger and storage for
   `subclass_of_closure`; cost at full Brick class cardinality.
4. **Inverse relationships.** Confirm "store canonical + traverse reverse" is
   sufficient everywhere, or whether any Brick query shape forces materialising both
   directions.
5. **TimeseriesReference identity.** `ref:hasTimeseriesId` = the human key
   (`ahu1.sat`) vs. an opaque id; how it relates to telemetry `series` cardinality and
   indexing.
6. **Discovery → Brick classification.** How much can be auto-proposed (BACnet object
   names → candidate Brick classes) vs. mandatory operator confirmation; where the
   ML/heuristic lives. (An early agent-mode assist candidate.)
7. **SurrealDB time-series at portfolio cardinality** — where rollups stop sufficing
   and an external historian is warranted.
8. **Native edge-sync vs. CHANGEFEED shipper** — verify the self-hosted SurrealDB sync
   mechanism, bidirectionality, and conflict semantics before retiring the shipper.
9. **SPARQL surface** — do we need a real SPARQL endpoint (cloud add-on over exported
   models) or are compiled SurrealQL query shapes enough for rules + dashboards.
10. **Agent embedding model & SurrealDB vector maturity** — which embedding model, edge
    vs. cloud embedding, and whether SurrealDB's vector index meets retrieval latency at
    portfolio scale (else an external vector store behind a retrieval seam).
11. **Agent write authority** — which proposals an agent may *apply* under a grant vs.
    always human-in-the-loop (rule authoring, Brick edits, RCx notes).

## Alternative substrate considered — TimescaleDB/Postgres + a graph add-on

The whole design above bets on **one engine** (SurrealDB) covering graph, time-series,
vector, document, and auth. The obvious alternative is the **mature, battle-tested**
combination most teams reach for: **PostgreSQL + TimescaleDB** for telemetry, plus a
**graph add-on** for the Brick model (Apache AGE as a Postgres extension, or a separate
graph DB), with **pgvector** for embeddings. This is recorded as a considered option,
not the chosen one.

What it buys:

- **Telemetry at scale, proven.** TimescaleDB hypertables, continuous aggregates, and
  compression are purpose-built for exactly the high-cardinality time-series load that
  is SurrealDB's least-proven axis here — it directly retires open question 7.
- **Operational maturity.** Backups, replication, HA, monitoring, and hiring are all
  solved for Postgres in a way they are not yet for SurrealDB.
- **`pgvector`** is a well-understood vector index for the agent's RAG retrieval.
- **Brick on a real graph.** Apache AGE (openCypher in Postgres) or a dedicated graph
  store can hold the Brick model; the typed-relation/closure design above maps onto it.

What it costs — and why it is the alternative, not the plan:

- **Edge→cloud sync does not come for free, and largely does not work the way this
  design needs.** The entire sync plane here relies on **one engine running embedded at
  the edge and in the cloud** with change-feed-driven, partition-by-station
  replication. Postgres/TimescaleDB is **not an embedded, offline-first edge engine**:
  you'd run a real server per building, and edge→cloud movement becomes
  logical-replication / Debezium-style CDC plumbing that is far heavier to operate at
  fleet scale, doesn't run truly offline-first the same way, and has its own conflict
  story to build. **Assume the edge-sync model in this doc does not carry over** —
  it would need a different, more operationally expensive sync design.
- **Three engines, three operational surfaces.** Postgres + Timescale + AGE/graph +
  pgvector is several moving parts to deploy, version, and secure on a building
  controller — against SurrealDB's single binary. The "one binary, edge to cloud"
  principle is lost.
- **Two query languages and a join seam.** Brick (Cypher/AGE) and telemetry (SQL/
  Timescale) live in different engines; the "resolve a Brick query → its series →
  window math" path that is one traversal here becomes a cross-engine join.

Net: this alternative is the **stronger choice if telemetry scale or Postgres operational
maturity is the dominant risk and the fleet is mostly cloud-side** — but it sacrifices
the embedded single-binary edge story and, critically, the cheap edge→cloud sync that
is a core goal of this design. It stays on the table as a fallback if SurrealDB's
time-series or sync axes fail to hold at real cardinality (open questions 7 and 8).

## References

- Brick Schema — <https://brickschema.org>
- Ref Schema (external references / timeseries) — <https://ref-schema.brickschema.org/>
- Brick timeseries storage model —
  <https://docs.brickschema.org/metadata/timeseries-storage.html>
- Rig (Rust LLM-agent framework) — <https://docs.rig.rs>
- open-fdd Python→Rust cutover (issue #334) —
  <https://github.com/bbartling/open-fdd/issues/334>
