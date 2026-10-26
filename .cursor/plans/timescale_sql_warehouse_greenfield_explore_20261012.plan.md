---
name: "Wave-X — Timescale 3.6.0 hard cutover (overnight mega)"
overview: "AUTHORIZED overnight: Rust BPS-shaped Open-FDD — Timescale-only historian + .sql FDD, same SPA. Edge drivers STAY (BACnet/Modbus fieldbus → MQTTS → Timescale). BPS is Haystack-only; Open-FDD keeps BACnet/Modbus/MQTTS direct-to-Timescale and optional Haystack like BPS. Seeds: warehouse + BUILDING_50 zips. NO dual-write, NO Parquet/Arrow/DF product path. Pandas/DuckDB test-only. VERSION 3.6.0. Grok Soft-OPEN. Next: 3.6.1 patch train."
todos:
  - id: w0-bootstrap
    content: "W0 Bootstrap — /tmp worktree; mount BPS reference; unpack both zips under /tmp/openfdd-softopen/3.6.0/; read BPS ADR 0009 + bps/tsdb + vendor SQL"
    status: completed
  - id: w1-adr-version
    content: "W1 ADR + VERSION 3.6.0 — supersede datafusion-first / Parquet historian ADRs; bump workspace VERSION + Cargo to 3.6.0; MILESTONES Wave-X"
    status: completed
  - id: w2-schema-compose
    content: "W2 openfdd-timescale — schema from BPS bps/tsdb/schema.sql adapted; compose profile timescale-only; auto-seed warehouse SQL + BUILDING_50 on first up"
    status: completed
  - id: w3-sql-rules-pack
    content: "W3 Full .sql pack — duplicate BPS/vendor/openfdd-warehouse + cookbook into sql/fdd/; sql_runner; inventory; no incomplete pack"
    status: completed
  - id: w4-ingest-api
    content: "W4 Soft-OPEN — package import COPY→Timescale (8.87M); hot analytics/FDD timescale-sql; MQTT writer Timescale-only (live soak deferred). Thin SQL ports for some query_ids."
    status: completed
  - id: w5-spa-contract
    content: "W5 Soft-OPEN — local Overview :5180→:18080 browser BUILDING_50; Inspect/RCx/FDD series + /api/fdd/run Timescale FIXED (W9); FC1 run-now hours MATCH W6 107.08h (W10 numeric→float8); Grok morning ≠ FQ."
    status: completed
  - id: w6-pandas-duckdb-stress
    content: "W6 Soft-OPEN — FC1 AHU_1 pandas 116.17h vs Timescale SQL 107.08h (delta~9h ART table); ≠ FQ. Grok HUMAN_PASTE morning."
    status: completed
  - id: w7-grok-softopen
    content: "W7 Grok kickoff DONE (clipboard+open). HUMAN_PASTE / prove = morning item — do not block ship. Soft-OPEN ≠ FQ."
    status: completed
  - id: w8-retire-apache
    content: "W8 DONE default binary — cargo tree no datafusion/fdd_sql; legacy-datafusion + legacy-parquet OFF; Parquet writer unreachable when Timescale configured. Soft-OPEN ≠ FQ."
    status: completed
  - id: w9-ship-pr
    content: "W9 Ship — commit+push wave-x/3.6.0-timescale; PR to master; docs/agent_spec Timescale; GH tidy; hand off 3.6.1 plan"
    status: completed
isProject: true
---

# Wave-X — Timescale 3.6.0 hard cutover (overnight mega) — 2026-10-12

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Status:** Soft-OPEN tip shipping (≠ FQ). Pin **`3.6.0`**. Default binary Timescale-only (`legacy-*` OFF). Product path + FC1 run-now hours FIXED (W9/W10): run-now `confirmation_seconds=600` → **107.0833h MATCH W6 SQL**; pandas delta~9h Soft-OPEN. Grok HUMAN_PASTE = morning (kickoff clipboard+open OK).

**Next:** [`.cursor/plans/post_wave_x_361_patch_ghcr_20261012.plan.md`](post_wave_x_361_patch_ghcr_20261012.plan.md) — **3.6.1** bugfix patch cycle on Timescale tip only.

**Shape:** Rust-port of BPS product core (Timescale + `.sql` FDD + thin API + same React UI). **Not** a Python BPS clone. **Not** Haystack-only.

Reference (RO Windows mount): `/media/ben/Windows/Users/ben/OneDrive/Documents/BPS Fault Detection and Diagnostics`

Seeds: `/home/ben/Downloads/OPENFDD_WAREHOUSE_SYNTHETIC_HANDOFF_20261012.zip`, `/home/ben/Downloads/BUILDING_50_openfdd.zip`

ART: `/tmp/openfdd-softopen/3.6.0/` (`REBOOT_SAFE.md`, `DONE.md`)

---

## Hard rules (non-negotiable)

1. **No dual-write.** Never Parquet + Timescale co-canonical. No sidecar.
2. **Timescale is the only product historian + FDD engine** after the flip branch lands.
3. **UI stays the same** — Overview / RCx / FDD / Inspect / Lab envelopes and routes; backend becomes SQL/Timescale.
4. **Edge drivers stay the same** — keep `openfdd-fieldbus` **BACnet + Modbus** (and existing OT driver surface). Do **not** replace fieldbus with BPS’s Python Haystack collector.
5. **OT → Timescale:** BACnet / Modbus → (existing fieldbus) → **MQTTS** → central ingest → **Timescale only**. Package import also → Timescale only.
6. **Haystack is optional** — same general fashion as BPS (optional Haystack pull/profile), **not** the sole OT path. BPS = Haystack-only; Open-FDD = BACnet/Modbus/MQTTS first-class + optional Haystack.
7. **Full `.sql` rules pack** — duplicate BPS pattern into Open-FDD `sql/fdd/` (+ Rust runner). Incomplete pack = no claim done.
8. **Auto-seed on stack up:** warehouse SQL pack + BUILDING_50 → Timescale.
9. **Pandas oracle / DuckDB test-only** — never product runtime.
10. **VERSION = 3.6.0**. Grok Soft-OPEN ≠ FQ.
11. Worktrees `/tmp/open-fdd-wt-*`; ART `/tmp/openfdd-softopen/3.6.0/`; no Desktop wt; mintbench no local builds; no `compose down -v`; no secrets / no BPS `.env`.
12. equipType / roles / registry only — no fixture `equipment_id` heuristics in product SQL.

---

## Target architecture (post–3.6.0)

```text
                    ┌─ openfdd-fieldbus (UNCHANGED drivers)
                    │    BACnet + Modbus ──► MQTTS ──┐
BUILDING_50 +       │                                │
warehouse SQL ──────┼─ auto-seed / package import ───┤
optional Haystack ──┘  (BPS-like optional profile)   │
                                                     ▼
                                            openfdd-timescale
                                            (SOLE store + sql/fdd/*)
                                                     │
                                                     ▼
                                            openfdd-central (Rust, thin)
                                            JWT + analytics/FDD → SQL
                                            NO DF / NO Parquet / NO Arrow
                                                     │
                                                     ▼
                                            openfdd-web (same SPA)

Oracle/CI only: pandas open_fdd.rules + DuckDB test harness
```

**Removed from product central/historian:** DataFusion `SessionContext`, Parquet canonical store, Arrow analytics materialize path, Feather.

**Kept:** `openfdd-fieldbus` edge drivers, MQTT broker role, React SPA surfaces.

**Residual note:** `fdd_store` may still pull `arrow`/`parquet` crates in the graph; product request/ingest path must not use DF SessionContext or Parquet historian. Default features: no `datafusion` / `fdd_sql`.

---

## Soft-OPEN tip evidence (shipping)

| surface | engine | BUILDING_50 |
| --- | --- | --- |
| Inspect / RCx / FDD series | timescale-sql | live |
| `/api/fdd/run` FC1 | timescale-sql | **107.0833h** @ confirm 600s (MATCH W6) |
| pandas FC1 | test-only | 116.17h — delta Soft-OPEN ≠ FQ |

Default binary: `legacy-*` OFF. Grok: clipboard+open kicked; HUMAN_PASTE remaining.

---

## Relationship to Soft-OPEN 371 / 3.6.1

| Prior 371 (DF 3.5.x) | This Wave-X | Next 3.6.1 |
| --- | --- | --- |
| Memory Soft-OPEN on DataFusion | **Superseded** — architecture flip to 3.6.0 Timescale | Bugfixes on Timescale tip only |
| Parquet historian | **Deleted** from product path | No DF resurrection |
| Explore-only plan | **Authorized execute overnight** | Patch train plan linked above |

Do **not** keep a DF fallback “just in case.” Rollback = git revert / prior GHCR sha, not dual-write.

---

## Exit criteria (3.6.0 Soft-OPEN ship)

- [x] VERSION **3.6.0** on health + sidebar (host tip).
- [x] Timescale sole store; auto-seed warehouse + BUILDING_50.
- [x] Full `.sql` pack (77 rules).
- [x] SPA same surfaces; Soft-OPEN smoke (Grok HUMAN_PASTE morning).
- [x] Pandas/DuckDB test-only parity table filed.
- [x] Zero product DataFusion/fdd_sql on default `cargo tree -p openfdd-central`.
- [ ] PR merged + GHCR published (W9) — then nightlies → 3.6.1 train.
