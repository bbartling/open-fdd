---
name: Wave S Data Model TTL Export
overview: "SPA + central TTL export/view derived from package mapping inventory. Package authoring SoT unchanged. Parent wave_soft_park_480c17e1."
todos:
  - id: ttl-builder-ts
    content: buildDataModelTurtle(inventory) from openfdd_data_model_v1; vitest golden fixtures
    status: pending
  - id: spa-buttons
    content: MappingPage Export TTL + View TTL as text; testids map-download-ttl / map-view-ttl-text
    status: pending
  - id: central-ttl-route
    content: GET package mapping TTL building_id JWT+allow_building; unit test ACL + shape
    status: pending
  - id: docs
    content: PACKAGE_AUTHORING + web Data Model docs — TTL export-only; AI zips still maps
    status: pending
isProject: false
---

# Wave S — Data Model TTL export / view

**Parent:** [wave_soft_park_480c17e1.plan.md](wave_soft_park_480c17e1.plan.md)

## Goal

Operators can download and view the site data model as **JSON** (already) and **Turtle**, without changing how agents author CSV/Haystack package zips.

## Implementation

### 1. Turtle builder (TypeScript)

- New helper next to [`frontend/web/src/api/mappingApi.ts`](frontend/web/src/api/mappingApi.ts) (e.g. `dataModelTurtle.ts`)
- Input: same shape as `buildMappingManifest` / `PackageMappingResponse`
- Output: Turtle string with prefixes `ofdd:` / `hs:` (and `xsd:` if needed)
- Emit per equipment: type, parent_ahu if any, role→column bindings as triples (stable IRI scheme: `ofdd:building/{bid}/equip/{eid}`)
- Empty/unmapped columns: omit or mark `ofdd:unmapped` — never invent cookbook roles
- Vitest: fixture inventory → golden `.ttl` substring assertions (prefixes, one AHU role triple, no phantom roles)

### 2. SPA ([`MappingPage.tsx`](frontend/web/src/pages/MappingPage.tsx))

| Control | Behavior | testId |
|---------|----------|--------|
| Export site data model | existing JSON download | `map-download-manifest` |
| View as text | existing JSON new tab | `map-view-manifest-text` |
| **Export TTL** | download `.ttl` blob | `map-download-ttl` |
| **View TTL as text** | `text/turtle` blob → `window.open` | `map-view-ttl-text` |

Caption: entire site model; TTL is a **derived export** of the same inventory as JSON.

### 3. Central API

- `GET /api/csv/import/package/mapping/ttl?building_id=` (name may match OpenAPI style of existing mapping routes)
- Auth: JWT; **fail-closed** `allow_building` (same as mapping JSON)
- Body: `text/turtle; charset=utf-8` built from the same inventory structs used by mapping JSON
- Prefer sharing one projection helper with any Rust turtle emitter; SPA may keep TS builder for offline blob UX without round-trip
- Unit/integration test: foreign building → 403; owned building → 200 + `@prefix`

**Do not** wire this into FDD run, analytics, or Oxigraph request path this wave. Edge `GET /api/model/ttl` (haystack grid) stays legacy/commissioning — product SPA uses **package mapping** projection.

### 4. Docs

- [`docs/agent/PACKAGE_AUTHORING.md`](docs/agent/PACKAGE_AUTHORING.md): one paragraph — UI TTL/JSON export does not replace zip maps
- Web/ops Data Model blurb (Mapping / Quick Start if present): Export JSON + TTL; View opens text tab
- Optional: note SPARQL/Oxigraph remains model-QA tooling on edge, not product FDD

### 5. Tests

- Vitest: turtle builder + MappingPage buttons enabled/disabled with inventory
- Central: ACL + content-type + minimal triple presence
- No synth-59 expected_faults edits

## Out of scope

- Brick ontology import
- SPARQL UI / playground
- Replacing `columns.csv` with RDF resolution
- MQTT pause UI (sibling parked plan)
