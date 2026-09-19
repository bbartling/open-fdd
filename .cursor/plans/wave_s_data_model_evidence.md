# Wave S — data model / graph / ECM evidence matrix

Tracks [wave_s_data_model_graph_review_handoff.md](wave_s_data_model_graph_review_handoff.md) against Wave S children.
**Parent master:** [`wave_s_master_ecb88a61.plan.md`](/home/ben/.cursor/plans/wave_s_master_ecb88a61.plan.md)  
**Bounded child:** [wave_s5_data_model_graph_ecm.plan.md](wave_s5_data_model_graph_ecm.plan.md)  
**Review tip (findings):** `471ef7a` / 3.5.30. Update rows as work lands; never claim PASS without artifact.

**Stress windows (master):** FQ MEGA only **S1** and **S4**. Model/ECM gate wires in **S5** (CI + smoke); FQ evidence for that gate lands on **S4**. S2/S3/S5 mid-tips = smoke + CI only. Do **not** launch a third FQ for this handoff.

| Req ID | Handoff § | Summary | Child | Implementation | Test / command | Tip SHA | Artifact | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADR-1 | §1 | Shared vocab vs tenant instances; vendor≠tenant; one revision authority | S2 | `docs/architecture/ADR_data_model_graph.md` | review checklist | tip pending 3.5.32 | ADR merged | PASS |
| DM-01 | §2 | Injective IRI segment (`AHU 1` vs literal `enc_…`) | S5 | TS+Rust `enc_` reserved | vitest + rust unit | tip 3.5.33 pending | dataModelTurtle tests | PASS |
| DM-02 | §2 | Unambiguous building/equip tuple + tenant identity | S5 | `ofdd:eq_<b>__<e>` | vitest + rust unit | tip 3.5.33 pending | tuple tests | PASS (tuple; tenant identity Soft-OPEN) |
| DM-03 | §2 | TS keep unmapped-only equipment | S5 | TS+Rust exporters | vitest dm03 + rust dm03 | tip 3.5.33 pending | unmapped-only tests | PASS |
| DM-04 | §2 | Honor stamped type/parent; no guessed feeds as fact | S5 | `package.rs` + stamps | fixture `AC_1`+`equipType:ahu` | | | BLOCKED |
| DM-05 | §2 | Tenant-scoped model storage/cache/exports | S5 | central handlers+storage | gate 31-style A/B | | | BLOCKED |
| DM-06 | §2 | Consumer/route matrix; SPARQL capability honesty | S2/S5 | `docs/modeling/consumer-route-matrix.md` | curl SPARQL expect unavailable | tip pending 3.5.32 | matrix + ADR | PASS (docs); live SPARQL still unavailable |
| DM-07 | §2 | Exact IRI/literal SPARQL bindings | S5 | `rdf.rs` | SPARQL JSON results tests | | | BLOCKED |
| DM-08 | §2 | Parser allowlist for SPARQL; no empty-ok on error | S5 | `sparql_select`/`query.rs` | `?address`/`"load"` cases | | | BLOCKED |
| DM-09 | §2/§6 | Bound rebuild/query CPU/RAM; measure first | S5 | oxigraph path | bench table § PERF-1 | | | BLOCKED |
| DM-10 | §2 | Versioned projection; no false markers / lossless claims | S5 | vocab+shapes | SHACL/fixture | | | BLOCKED |
| SEC-ML | §3 | Full model lifecycle authz (JSON/TTL/query/MCP) | S5 | ACL + inventory checks | security harness + CI | | | BLOCKED |
| JSON-PARITY | §4 | JSON↔TTL declared field crosswalk | S5 | exporters | isomorphism tests | | | BLOCKED |
| AI-TOOLS | §4 | Scoped model tools; SCAFFOLD vs shipped honesty | S5 | MCP/central | capability smoke | | | BLOCKED |
| SPARQL-SEM | §5 | Real SPARQL semantics (not TTL grep) | S5 | fixtures | SELECT path/aggregate | | | BLOCKED |
| PERF-1 | §6 | Baseline→candidate measurements | S5 | bench script | reports table | | | BLOCKED |
| EQ-VOCAB | §7.1 | Engineering quantity vocabulary + shapes | S5 | `docs/modeling/` + `.ttl` | Pages build | | | BLOCKED |
| EQ-PERSIST | §7.2 | Import→export retain capacities | S5 | package/importer | save/reload fixtures | | | BLOCKED |
| ECM-ADAPT | §7.3 | Model→`open_fdd.ecm_engineering` adapter | S3/S5 | PyPI tools | fan/schedule/kw_ton cases | | | BLOCKED |
| DOCS-PAGES | §8 | GitHub Pages vocab/onboarding/agent | S5 | `docs/` + workflow | jekyll + public URL | | | BLOCKED |
| STRESS-GATE | §9 | Model/ECM gate in stress profiles; fix 25b BLOCKED hole | S4/S5 | `run_railway_hub_stress.sh` | FQ on **S4** tip only | | | BLOCKED |
| UI-MV | master S4 | M&V charts on Metering / new radio | S4 | SPA | Vitest + smoke | | | BLOCKED |

## Incomplete coverage (visible)

Until a row is PASS with artifact path + tip SHA, treat that requirement as **not done**. Missing live SPARQL on central = report **unavailable**, not PASS via empty list. Soft-OPEN / deferred items stay listed here — do not greenwash.

## Reproducer (DM-01/02/03) — still failing until S5

```bash
# Review harness (external); permanent in-repo tests land on S5 tip
node …/openfdd-data-model-repro.mjs /home/ben/Desktop/open-fdd
```

Observed at `471ef7a`: exporter SHA-256 `38fac566…`, exit 1, all three cases failed.
