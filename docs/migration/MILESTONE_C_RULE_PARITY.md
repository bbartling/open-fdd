---
title: Milestone C SQL rule parity
parent: Migration
nav_order: 25
---

# Milestone C SQL rule parity

**Date:** 2026-07-28

Tracks honest SQL ↔ Pandas cookbook parity states for Milestone C. Full mutation
harness and family-by-family `PROVEN_MULTI_BUILDING` claims are **residuals**.

## Canonical states

| State | Meaning |
|-------|---------|
| `UNPORTED` | No SQL expression / not in registry path under test |
| `SCHEMA_ONLY` | Contract or stub without behavioral parity |
| `FIXTURE_PASS` | Passes obvious-fault / normal JSONL fixtures |
| `PARITY_TOLERANCED` | Matches pandas within documented tolerances |
| `PROVEN_SINGLE_BUILDING` | Validated on one real building export |
| `PROVEN_MULTI_BUILDING` | Validated across multiple buildings (C10 goal) |

Public cookbook vs registry counts must stay honest (see README / cookbooks);
do not silently diverge badge vs `sql_rules/registry.yaml`.

## Fixture library

Synthetic `telemetry_pivot` JSONL under
[`docs/rules/cookbook/fixtures/`](../rules/cookbook/fixtures/):

| Fixture | Intent |
|---------|--------|
| `fc1_obvious_fault.jsonl` / `fc2_obvious_fault.jsonl` | AHU FC obvious faults |
| `reset1_obvious_fault.jsonl` / `reset1_normal.jsonl` | Reset fault vs normal |
| `sched1_obvious_fault.jsonl` / `sched247_obvious_fault.jsonl` | Schedule faults |
| `vav1_obvious_fault.jsonl` / `vav6_obvious_fault.jsonl` / `vav7_obvious_fault.jsonl` | VAV faults |

Run: `python3 scripts/cookbook_parity_check.py --all`

See also [`fixtures/README.md`](../rules/cookbook/fixtures/README.md).

## Mutation-check section

**D2 path harness:** [`scripts/rule_parity_mutation_check.py`](../../scripts/rule_parity_mutation_check.py)
(registry count, dual cookbooks, heading floor, high-risk keywords, delete-path
guards). See [`MILESTONE_D_RULE_PARITY.md`](MILESTONE_D_RULE_PARITY.md).

High-risk families should also get selective **logical** mutation checks before
claiming parity. Until those land, reviewers manually verify that tests **fail**
if any of the following regressions are introduced:

| Mutation | Expected failure signal |
|----------|-------------------------|
| Remove fan-on / occupancy gate | False positives on economizer / schedule / comfort |
| Flip `>` / `<` on ΔT or comfort band | Inverted OA fraction or comfort ranking |
| Duration = sample count (not Δt) | Runtime / occupied hours inflate with poll rate |
| Treat pump or valve as compressor proof | Mechanical cooling eligibility becomes true on pump-only |
| Drop `|OAT−RAT|` identifiability gate | OA fraction on non-identifiable samples |

Central analytics already encodes the pump≠compressor gate in
`mechanical_cooling.rs` unit tests and Δt runtime in `runtime.rs`.

## Residual

- Broader SQL rule fixture coverage per family
- Logical gate-mutation tests (path mutation CI is done in D2)
- Honest per-rule state column in the parity matrix beyond docs-only notes
