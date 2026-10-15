# Soft-OPEN R7 — exposure profiles (≠ FQ)

Soft-OPEN ≠ FQ. Policy source: [deployment_route_exposure_wave_x_20261013.md](../../.cursor/agents/deployment_route_exposure_wave_x_20261013.md) + [ROUTE_EXPOSURE_WAVE_X.md](../operations/ROUTE_EXPOSURE_WAVE_X.md).

## Three profiles (Soft-OPEN snapshot)

| Profile | Soft-OPEN tip evidence | Still FQ |
| --- | --- | --- |
| Railway / cloud | Tip JWT anon **401** on `/api/model/sparql`, `/api/fdd/plots-by-rule`, `/api/fdd/plot`; JWT plots-by-rule **200**; health lean public | Full profile matrix scan, proxy chain, Nessus |
| Full OT LAN/server | Soft-OPEN **BLOCKED** — no OT edge on Railway tip Soft-OPEN night | Caddy+OT overlay + local-ingest denial |
| Field-only edge | Soft-OPEN **BLOCKED** — no fieldbus edge attached to Soft-OPEN tip | Field spool + MQTTS ACL Soft-OPEN |

## Tip-proven Soft-OPEN negatives (3.6.12+)

| Probe | Result |
| --- | --- |
| Anon SPARQL / plots-by-rule / plot | **401** |
| JWT agent compaction/budget | **403** hub admin |
| JWT admin compaction (Timescale) | Soft-OPEN `parquet_compaction=not_applicable` |
| JWT SPARQL INSERT / SERVICE | Rejected pre-meta (#1244) |

## Soft-OPEN honesty

- Inventory includes `GET /api/fdd/plots-by-rule` and SPARQL routes.
- Soft-OPEN tip probes ≠ ZAP/Nessus PASS and ≠ full cloud/OT/field profile FQ.
- Do not expose Timescale/DB ports to agents; JWT before SQL remains Rust-owned.

Locks: no Soft-OPEN backups · volume Deletes owner-UI BLOCKED · Soft-OPEN ≠ FQ.
