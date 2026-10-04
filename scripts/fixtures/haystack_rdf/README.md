# Haystack RDF C1/C3 — synthetic fixtures (#998 / #1001)

Public, machine-portable fixtures for Haystack RDF wave **C1** (baseline profile)
and **C3** (strict projection). They are **not** derived from product exporters
and must not be copied from maintainer Downloads or live BAS exports.

| File | Role |
| --- | --- |
| `synthetic_mapping_inventory.json` | `PackageMappingResponse`-shaped inventory (AHU + VAV, ambiguity, missing parent, intentional exclusion) |
| `synthetic_point_metadata_v1.json` | C2/C3 `openfdd_semantic_meta_v1` sidecar — unknown unit, unknown tag, false marker, ambiguity/exclusion columns |
| `expected_c1_answers.json` | Independent expected answers for HR-03/04/05 and strict vs native export checks |

Building id: `OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1` (synthetic only).

Strict projection code: `edge/src/csv_ingest/haystack_projection.rs` (`ofdd_haystack_projection_v1`).
