---
title: ADR — Historian ingest path split (OT MQTTS vs Haystack hisRead)
parent: Architecture
nav_order: 17
---

# ADR: Historian ingest path split (#1017 L1)

**Status:** Accepted for L1 baseline (docs + metrics contract). L2/L3 implement crash durability and scheduled `hisRead`.  
**Issue:** [#1017](https://github.com/bbartling/open-fdd/issues/1017)  
**Related:** [#781](https://github.com/bbartling/open-fdd/issues/781) protocol split · [#997](https://github.com/bbartling/open-fdd/issues/997) Haystack RDF · [ADR protocol connector process split](ADR_protocol_connector_process_split.md)

## Decision

Open-FDD keeps **one** canonical historian (Parquet under `OPENFDD_STORAGE_URL` + DataFusion). Two **edge collector** families feed it; they must not share process/socket ownership:

```text
BACnet / Modbus OT
        │
        ▼
openfdd-bacnet-modbus  ──MQTTS──►  openfdd-mqtt  ──►  openfdd-central ingest
                                                         │
Haystack Project HTTP                                    │  shared validation,
openfdd-haystack  ──HTTPS hisRead / catalog──►           │  identity, Parquet writer
        (MQTT optional; not required for history sync)   ▼
                                              immutable Parquet parts
```

| Path | Owns | Must not own |
| --- | --- | --- |
| OT MQTTS | BACnet/IP UDP, Modbus/TCP, poll → MQTTS publish | Haystack HTTP credentials, `hisRead` schedulers |
| Haystack history | Outbound authenticated Haystack HTTP (`about`, catalog/read, bounded `hisRead`) | BACnet UDP, Modbus sockets, broker requirement for history import |
| Central | Envelope validation, tenant/building identity, receipt journal, sole Parquet writer | Edge protocol sockets |

CSV/ZIP package import remains a third **operator** path into the same historian. It does not replace either live path.

## Durability metrics baseline (measure before claiming)

L1 records the **metric names** operators and L2 tips must emit. Numbers are Soft-OPEN until measured on a tip.

| Metric | Meaning | Fail-closed signal |
| --- | --- | --- |
| `ingest_receipts_pending` | Envelopes accepted but not committed | Growth without commit → spool retention pressure |
| `ingest_receipts_committed` | HTTP 200 path; `persisted_rows > 0` | Zero-row “success” is not durable |
| `ingest_receipts_terminal_zero` | Empty eligible payload; not retriable as data loss | Distinct from reject |
| `ingest_receipts_rejected` / `conflict` | Auth, schema, digest mismatch, duplicate message id | Quarantine; do not retry blindly |
| `ingest_replay_count` | Exact replay of a committed envelope | Must stay at documented acceptance count |
| `historian_flush_rows` / `historian_flush_latency_ms` | Micro-batch publish | Bound memory; do not claim crash durability from graceful shutdown alone |
| `historian_watermark_lag_s` | Watermark vs newest committed part | Stale analytics `stale: true` honesty |
| `hisread_checkpoint_ts` (L3) | Last successful Haystack history cursor per site/equip | Missing checkpoint → no “caught up” claim |

Graceful shutdown flush is **necessary but not sufficient** for crash durability. L2 must prove staging → atomic publish → receipt journal compaction across kill -9 / process restart.

## Seven-day hot tier

Do **not** introduce a second time-series database in L1–L2. L3 may **benchmark** seven-day hot access on the existing Parquet layout and write numbers; choosing another store requires that writeup, not a predetermined dependency.

## Non-goals (this ADR)

- Closing #1070 (gate39 MQTTS prove) — separate Soft-OPEN wall-clock.
- Rewriting Haystack RDF identity (#997 / C2+ `semantic_meta`) — reuse, do not fork.
- FQ / OPS pin from docs alone.
- Sacred cookbook rewrites.

## Exit for L1 tip

- [x] This ADR + historian.md pointer + architecture index link
- [ ] L2 implements crash/replay + metric emission on the shared ingest path
- [ ] L3 ships standalone scheduled `hisRead` + 7-day hot-tier benchmark writeup → may close #1017
