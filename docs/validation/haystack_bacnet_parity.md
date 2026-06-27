# BACnet vs Haystack parity validation

Compare BACnet direct readings with Niagara nHaystack for the same logical points on a **field bench** (not CI).

## Goal

Prove that readings for the same logical sensor points match when obtained via:

1. **BACnet direct** — Open-FDD BACnet driver
2. **Haystack via Niagara nHaystack** — Open-FDD Haystack driver

## Prerequisites

- BACnet device integrated in Niagara (e.g. device instance 5007)
- nHaystack exposing the same points
- Local parity profile mapping roles → BACnet objects + Haystack ids  
  Example: `workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml.example`

## Procedure

```bash
# Copy and edit haystack_id placeholders first:
cp workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml.example \
   workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml

OPENFDD_HAYSTACK_PARITY_PROFILE=workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml \
  ./scripts/openfdd_haystack_bacnet_parity.sh
```

1. Connect to BACnet direct using `bacnet_source_id`.
2. Connect to Niagara nHaystack using `haystack_source_id`.
3. Read mapped points through both paths.
4. Normalize units (°F, %RH, etc.).
5. Compare values within tolerance.
6. Record pass/fail into validation artifacts under `workspace/logs/`.
7. Optionally write both samples to Feather/historian with distinct `source_id`.
8. Confirm model maps both sources to the same equipment/point role.

## Tolerances (configurable)

| Quantity | Default |
|----------|---------|
| Temperature | 1.0 °F |
| Humidity | 5 %RH |
| Timestamp skew | 120 seconds |

Environment hooks (future):

```bash
export OPENFDD_SMOKE_HAYSTACK_PARITY=1
export OPENFDD_HAYSTACK_PARITY_PROFILE=workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml
```

## Comparison output fields

| Field | Description |
|-------|-------------|
| `equipment_id` | Haystack equipment id |
| `role` | Logical role (oa_t, oa_h, …) |
| `bacnet_object` | BACnet object identifier |
| `haystack_id` | nHaystack point id |
| `bacnet_value` | Direct BACnet reading |
| `haystack_value` | Haystack/Niagara reading |
| `absolute_delta` | \|bacnet − haystack\| |
| `tolerance` | Applied threshold |
| `pass` | Boolean |
| `bacnet_timestamp` | Sample time (BACnet path) |
| `haystack_timestamp` | Sample time (Haystack path) |
| `timestamp_delta_seconds` | \|Δt\| |

The comparator function lives in `edge/src/drivers/haystack/parity.rs` and is covered by unit tests with mocked values only.

## Intentionally not run yet

- Full 5007 long smoke
- 1-hour / 6-hour validation
- CSV append/delete validation

Enable with `OPENFDD_SMOKE_HAYSTACK_PARITY=1` when the orchestration script lands in a follow-up PR.
