# Wave S — data model / graph / ECM evidence matrix

Tracks [wave_s_data_model_graph_review_handoff.md](wave_s_data_model_graph_review_handoff.md) against Wave S children.
**Parent master:** [`wave_s_master_ecb88a61.plan.md`](/home/ben/.cursor/plans/wave_s_master_ecb88a61.plan.md)  
**Bounded child:** [wave_s5_data_model_graph_ecm.plan.md](wave_s5_data_model_graph_ecm.plan.md)  
**Review tip (findings):** `471ef7a` / 3.5.30. Update rows as work lands; never claim PASS without artifact.

**Stress windows (master):** FQ MEGA only **S1** and **S4**. Model/ECM gate wires in **S5** (CI + smoke); FQ evidence for that gate lands on **S4**. S2/S3/S5 mid-tips = smoke + CI only. Do **not** launch a third FQ for this handoff.

| Req ID | Handoff § | Summary | Child | Implementation | Test / command | Tip SHA | Artifact | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADR-1 | §1 | Shared vocab vs tenant instances; vendor≠tenant; one revision authority | S2 | `docs/architecture/ADR_data_model_graph.md` | review checklist | `8b0eefe` / 3.5.32 | ADR merged #953 | PASS |
| DM-01 | §2 | Injective IRI segment (`AHU 1` vs literal `enc_…`) | S5 | TS+Rust `enc_` reserved | vitest 9/9 + rust 7/7 | `3cd3745` / 3.5.33 | #954 unit tests | PASS |
| DM-02 | §2 | Unambiguous building/equip tuple + tenant identity | S5 | `ofdd:eq_<b>__<e>` | vitest + rust unit | `3cd3745` / 3.5.33 | tuple tests | PASS (tuple; tenant identity Soft-OPEN) |
| DM-03 | §2 | TS keep unmapped-only equipment | S5 | TS+Rust exporters | vitest dm03 + rust dm03 | `3cd3745` / 3.5.33 | unmapped-only tests | PASS |
| DM-04 | §2 | Honor stamped type/parent; no guessed feeds as fact | S5 | `package.rs` + stamps | fixture `AC_1`+`equipType:ahu` | | | Soft-OPEN |
| DM-05 | §2 | Tenant-scoped model storage/cache/exports | S5 | central handlers+storage | gate 31-style A/B | | | Soft-OPEN |
| DM-06 | §2 | Consumer/route matrix; SPARQL capability honesty | S2/S5 | `docs/modeling/consumer-route-matrix.md` | curl SPARQL → 404 | `8b0eefe`+`3cd3745` | matrix + live 404 | PASS (docs); live SPARQL unavailable |
| DM-07 | §2 | Exact IRI/literal SPARQL bindings | S5 | `rdf.rs` injective `enc_` + W3C bindings | `cargo test -p open_fdd_edge_prototype rdf:: --lib` | tip V5 | unit dm07_* | **PASS (tip)** |
| DM-08 | §2 | Parser allowlist for SPARQL; no empty-ok on error | S5 | `spargebra` SELECT allowlist; `query.rs` propagates Err | `cargo test -p open_fdd_edge_prototype sparql:: --lib` + query Err path | tip V5 | unit dm08_* | **PASS (tip)** |
| DM-09 | §2/§6 | Bound rebuild/query CPU/RAM; measure first | S5 | early `SPARQL_MAX_ROWS+1` break | `cargo test -p open_fdd_edge_prototype rdf:: --lib` + `docs/operations/perf/dm09_baseline.md` | W4 / 3.5.45 | baseline table | **PARTIAL** (cap shipped; 1k/10k/100k RSS Soft-OPEN) |
| DM-10 | §2 | Versioned projection; no false markers / lossless claims | S5 | `ofdd_haystack_projection_v1` + no invented `hs:sensor` + EQ-VOCAB | unit `dm10_no_false_sensor_marker_*` + pytest | W4 / 3.5.45+4.4.7 | rdf.rs + vocab | **PASS (narrow)** — full JSON field crosswalk Soft-OPEN |
| SEC-ML | §3 | Full model lifecycle authz (JSON/TTL/query/MCP) | S5 | ACL + inventory checks | security harness + CI | | | Soft-OPEN |
| JSON-PARITY | §4 | JSON↔TTL declared field crosswalk | S5 | exporters | isomorphism tests | | | Soft-OPEN |
| AI-TOOLS | §4 | Scoped model tools; SCAFFOLD vs shipped honesty | S5 | MCP/central | capability smoke | | | Soft-OPEN |
| SPARQL-SEM | §5 | Real SPARQL semantics (not TTL grep) | S5 | fixtures | SELECT path/aggregate | | | Soft-OPEN |
| PERF-1 | §6 | Baseline→candidate measurements | S5 | `docs/operations/perf/dm09_baseline.md` | bench table | W4 tip | baseline doc | **PARTIAL** (budgets declared; no candidate win) |
| EQ-VOCAB | §7.1 | Engineering quantity vocabulary + shapes | S5 | `docs/modeling/` + `.ttl` + `eq_vocab.py` | pytest + Pages | tip W4 / 4.4.7 | `test_eq_vocab_adapter` | **PASS (tip)** |
| EQ-PERSIST | §7.2 | Import→export retain capacities | S5 | package/importer | save/reload fixtures | | | Soft-OPEN |
| ECM-ADAPT | §7.3 | Model→`open_fdd.ecm_engineering` adapter | S3/S5 | `model_adapter.py` | fan/schedule/kw_ton cases | tip W4 / 4.4.7 | `test_eq_vocab_adapter` | **PASS (tip)** |
| DOCS-PAGES | §8 | GitHub Pages vocab/onboarding/agent | S5 | `docs/` + workflow | jekyll + public URL | #958 + W4 pages | modeling/ecm docs | **PASS (tip)** (vocab pages on W4) |
| STRESS-GATE | §9 | Model/ECM gate in stress profiles; fix 25b BLOCKED hole | S4/S5 | `run_railway_hub_stress.sh` | FQ on **S4** tip only | | | Soft-OPEN |
| UI-MV | master S4 | M&V charts on Metering / new radio | S4 | SPA | Vitest + smoke | | | Soft-OPEN |

## Incomplete coverage (visible)

Until a row is PASS with artifact path + tip SHA, treat that requirement as **not done**. Missing live SPARQL on central = report **unavailable**, not PASS via empty list. Soft-OPEN / deferred items stay listed here — do not greenwash.

## Reproducer (DM-01/02/03) — CLOSED on S5 tip

Permanent in-repo tests: `frontend/web/src/api/dataModelTurtle.test.ts` (9) · `edge/src/csv_ingest/data_model_ttl.rs` tests (7). Tip **`sha-3cd3745`** / 3.5.33 (#954).

Observed at review tip `471ef7a` (pre-fix): exporter SHA-256 `38fac566…`, exit 1 — superseded.
