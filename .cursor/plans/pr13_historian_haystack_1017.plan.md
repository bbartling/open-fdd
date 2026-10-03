---
name: "PR-13 Historian + Haystack hisRead #1017"
overview: "Harden historian ingestion; separate Haystack hisRead imports from OT fieldbus; use fake Haystack + BACnet OT bench for proof."
todos:
  - id: pr13-boundaries
    content: "Document/enforce BACnet-Modbus OT path vs Haystack history connector path"
    status: pending
  - id: pr13-ingest-harden
    content: "Harden shared historian ingestion durability (receipts, replay, compaction honesty)"
    status: pending
  - id: pr13-hisread
    content: "Scheduled/manual Haystack hisRead import into historian without requiring MQTT"
    status: pending
  - id: pr13-bench-7d
    content: "Benchmark seven-day hot storage on existing Parquet path; record numbers before any TSDB claim"
    status: pending
  - id: pr13-ot-local
    content: "Local verify: fake Haystack gate 05 + BACnet gate 02; preflight free 47808"
    status: pending
  - id: pr13-pr-ci
    content: "VERSION tip if product; muse-spark watch; merge; close #1017"
    status: pending
isProject: false
---

# PR-13 — Historian harden + Haystack hisRead (#1017)

**Parent:** [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md)  
**Prefer after:** PR-07 (HR C2 metadata) when imports need identity/revision  
**Branch:** `feat/historian-haystack-hisread-1017`  
**Closes:** #1017  
**Models:** design=`claude-opus-5-thinking-high` · code=`composer-2.5-fast` · critique=`claude-sonnet-5-5-high` · CI watch=`muse-spark-1.3-high`

## Goal

Keep Parquet/DataFusion canonical. Separate **Haystack history sync** from **BACnet/Modbus OT fieldbus**. Measure seven-day hot tier before proposing another database.

## Sub-PR split (required)

| Sub | Branch focus | Closes #1017? |
| --- | --- | --- |
| **L1** | Baseline trace + ADR + durability metrics (docs-heavy; after PR-02 C1 identity) | no |
| **L2** | Crash/replay, durable staging, atomic Parquet — `ingest`, `live_historian`, `fdd_store`, `openfdd_mqtt` spool | no |
| **L3** | Standalone Haystack hisRead connector + checkpointed import + **7-day hot-tier benchmark writeup** (benchmark ≠ new TSDB) | **yes** |

Do **not** absorb #1070 into this PR — use gate39 findings as a test case only.

## Local OT bench (this host)

```bash
./scripts/fieldbus/preflight_free_47808.sh
# BACnet device path
./scripts/nightly-ot-bench/02_bacnet_ot.sh
# Fake / configured Haystack
./scripts/nightly-ot-bench/05_haystack.sh
# Protocol split honesty
./scripts/gates/protocol_connector_split.sh
```

Refs: [`docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md`](../../docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md), [`scripts/nightly-ot-bench/README.md`](../../scripts/nightly-ot-bench/README.md), `services/fieldbus/src/bin/openfdd-haystack.rs`.

## Hard rules

- `openfdd-fieldbus` never on Railway
- One UDP 47808 owner
- Reuse Haystack RDF identity contracts (#997 wave); do not fork metadata
- CSV/ZIP ingest remains compatible
