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
