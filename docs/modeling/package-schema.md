---
title: Package schema (ingest contract)
parent: Haystack Modeling
nav_order: 3
---

# Package schema — what agents must know

Open-FDD package lane: `openfdd_package_v1` ZIP → `POST /api/csv/import/package`.

This page documents **shipped** ingest shapes versus **SCAFFOLD** commissioning
evidence. Do not treat unshipped MCP mapping tools as the live importer.

## Compact ingest map (normative today)

Sibling JSON next to each equipment CSV (or root equipment maps). Example:

```json
{
  "equipType": "heatPump",
  "equip": "HP_1",
  "points": {
    "discharge-air-temp": "da_t",
    "zone-air-temp": "zn_t",
    "fan-status": "sf_s"
  }
}
```

Rules:

- `points` keys = Haystack point names → values = **exact CSV column headers**.
- Haystack names translate to SQL roles via `haystack_point_to_role`
  (`discharge-air-temp` → `sat`). See `ROLE_MAPPING_PARITY.md`.
- Prefer stamp `equipType` (`ahu` `vav` `chwPlant` `boiler` `heatPump` `weather`).
- Weather: `{building}/weather/` with `web-outside-air-temp` → SQL `web_oa_t`.
- String `"equip": "HP_1"` is device metadata, not a nested package map.

Full authoring checklist: [PACKAGE_AUTHORING.md](../agent/PACKAGE_AUTHORING.md).

## Semantic metadata sidecar (C2 — optional)

Optional building-root file consumed by package import (Haystack RDF C2 / #1000):

| Package path | Schema |
| --- | --- |
| `semantic_meta.json` (preferred) | `openfdd_semantic_meta_v1` |
| `openfdd_semantic_meta_v1.json` / `point_metadata.json` | same |

Persists to `workspace/data/csv_buildings/<building_id>/semantic_meta.json` plus
`semantic_meta.revision.json` (atomic revision / content hash). Fields prefer
**Project Haystack tags** (`haystack_tags`), units, refs, and provenance.
Engineering quantities are Open-FDD-only when Haystack has no def. Old ZIPs
without the sidecar keep prior FDD/analytics meaning — metadata is **never
fabricated**. Invalid sidecar is rejected with a warning; a concurrent revision
mismatch returns an explicit conflict (HR-07).

C3 projects this native store to Haystack RDF (`ph` / `phIct`). Do not treat the
SPA’s invented `openfdd_data_model_v2` TTL as the site model until that lands.

Fixture: `scripts/fixtures/haystack_rdf/synthetic_point_metadata_v1.json`.

## Rich mapping evidence (SCAFFOLD — not the importer)

The MCP role pack `docs/mcp-agents/roles/package-mapping.md` describes richer
entries (`column`, `role`, `unit`, `equip_ref`, `confidence`, `evidence`,
PROVISIONAL/PROVEN) and tools (`package_preflight`, `mapping_suggest`, …).

**Status:** SCAFFOLD. Those tools are **not** in the `mcp/` crate as a shipped
path for this cycle. Until they land:

- Use compact sibling maps for ingest.
- Keep optional evidence/readiness notes in the **site preprocess repo**, not as
  invented product behavior.
- Use existing MCP/API: `openfdd_csv_import_*`, `openfdd_csv_package_append`,
  `openfdd_ingest_contract`.
- Optional C2 `semantic_meta.json` for tags/units/refs (above).

## Importable ≠ ready

| Outcome | Meaning |
|---------|---------|
| ZIP parses / import `ok` | Members readable; some roles may still be blank |
| Charts / matrices empty | Missing mapped roles or rule evidence |
| Rule `not runnable` | Required SQL roles absent for that equipment |
| Fabricated columns | Forbidden — request BAS re-export instead |

## Known weather gap (honest)

Preferred: sibling weather sidecar with `equipType: weather` and explicit
`points` → `web_oa_t`.

Agents may see a root-level `weather.column_roles` shape in some archives.
Do **not** assume the importer normalizes every root weather shape — verify
post-import that `web_oa_t` is mapped. Distinguish BAS `oa_t` from web
`web_oa_t`.
