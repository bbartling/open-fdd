---
name: "Post–Wave-X 3.6.1 Timescale patch train"
overview: "Bugfix-only overnight/patch cycle on the Timescale-only 3.6.0 tip. No dual-write. No DataFusion/Parquet/Arrow resurrection. Nightlies from 3.6.0 once merged/published. Grok Soft-OPEN after each tip. Soft-OPEN ≠ FQ."
todos:
  - id: p0-land-360
    content: "P0 Land 3.6.0 PR → master; wait GHCR publish; pin newest-by-created sha-*"
    status: pending
  - id: p1-branch-361
    content: "P1 Branch wave-x/3.6.1-patch from Wave-X tip; bump VERSION 3.6.1"
    status: pending
  - id: p2-fc1-defaults
    content: "P2 FC1 confirm_min / confirmation_seconds defaults align registry vs run-now (300 vs 600 Soft-OPEN)"
    status: pending
  - id: p3-analytics-gaps
    content: "P3 Remaining analytics query_id thin SQL ports + Overview matrices honesty"
    status: pending
  - id: p4-mqtt-soak
    content: "P4 MQTTS → Timescale live soak (fieldbus unchanged); no Parquet writer"
    status: pending
  - id: p5-package-edges
    content: "P5 Package import edge cases (maps, timestamps, equipType stamps) → Timescale COPY"
    status: pending
  - id: p6-spa-ci
    content: "P6 SPA thin spots + CI green on Timescale tip; no legacy-* ON"
    status: pending
  - id: p7-grok
    content: "P7 Grok Soft-OPEN after each tip; HUMAN_PASTE if unattended send fails; ≠ FQ"
    status: pending
isProject: true
---

# Post–Wave-X — 3.6.1 Timescale patch train — 2026-10-12

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Status:** Ready once **3.6.0** merge-ready PR is landed / Actions green. Soft-OPEN ≠ FQ.

**Parent cutover:** [`.cursor/plans/timescale_sql_warehouse_greenfield_explore_20261012.plan.md`](timescale_sql_warehouse_greenfield_explore_20261012.plan.md)  
**ADR:** [`docs/architecture/adr-010-timescale-hard-cutover.md`](../../docs/architecture/adr-010-timescale-hard-cutover.md)  
**Ops:** [`docs/operations/TIMESCALE_WAVE_X.md`](../../docs/operations/TIMESCALE_WAVE_X.md)  
**ART (3.6.0):** `/tmp/openfdd-softopen/3.6.0/` — start 3.6.1 ART under `/tmp/openfdd-softopen/3.6.1/` when branch opens.

---

## Hard rules (unchanged from Wave-X)

1. **No dual-write.** Never Parquet + Timescale co-canonical.
2. **No DataFusion / Parquet / Arrow product path.** `legacy-*` stay OFF on tip.
3. **Bugfixes only** on Timescale tip — no architecture re-litigation.
4. **UI stays the same.** Fieldbus BACnet/Modbus unchanged; Haystack optional.
5. **Pandas / DuckDB test-only.**
6. **Soft-OPEN ≠ FQ.** Grok after each tip; do not claim FQ from this train.
7. mintbench: no local docker build of stack images; GHCR via Actions after merge.
8. No `compose down -v` / volume prune / delete `workspace/`.

---

## Scope (3.6.1)

| Bucket | Work |
| --- | --- |
| FC1 defaults | Align `confirm_min` / `confirmation_seconds` registry defaults with Soft-OPEN prove path (W10: 600s → 107.08h MATCH W6; registry 300s → 111.42h) |
| Analytics gaps | Thin SQL ports for remaining `query_id`s; Overview honesty when maps incomplete |
| MQTT soak | Live MQTTS → Timescale writer prove; fieldbus unchanged |
| Package import | Edge cases on COPY→Timescale (timestamps, maps, equipType) |
| SPA / CI | Thin SPA spots; keep Actions green; no DF CI resurrection as product gate |
| Nightlies | Retarget OT/API nightlies to Timescale tip once 3.6.0 published |

Out of scope: dual-write bridges, DF SessionContext product path, Parquet historian restore as product, Haystack-only OT replacement.

---

## Train loop

```text
FAIL / Soft-OPEN gap → tiny patch on wave-x/3.6.1-patch → VERSION bump if product
→ PR → Actions → GHCR sha-* → pin newest-by-created → smoke → Grok Soft-OPEN
→ next gap
```

---

## Exit (3.6.1 Soft-OPEN tip)

- [ ] 3.6.0 on master + GHCR published
- [ ] 3.6.1 tip addresses FC1 default + named analytics/MQTT/package/SPA items or honest BLOCKED
- [ ] `cargo tree -p openfdd-central` still has no `datafusion` / `fdd_sql` on default features
- [ ] Grok ART under `/tmp/openfdd-softopen/3.6.1/`
- [ ] Still Soft-OPEN ≠ FQ (pandas vs SQL delta may remain)
