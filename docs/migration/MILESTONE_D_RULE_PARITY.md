---
title: Milestone D SQL rule parity
parent: Migration
nav_order: 32
---

# Milestone D SQL rule parity

**Date:** 2026-07-28 · Branch `milestone-d/d1-historian-datafusion-runtime`

Hardens Milestone C parity docs with an automated mutation path check
([`scripts/rule_parity_mutation_check.py`](../../scripts/rule_parity_mutation_check.py))
wired into Cookbook parity CI. Companion: [`MILESTONE_C_RULE_PARITY.md`](MILESTONE_C_RULE_PARITY.md).

## Canonical states

| State | Meaning |
|-------|---------|
| `UNPORTED` | No SQL expression / not in registry path under test |
| `SCHEMA_ONLY` | Contract or stub without behavioral parity |
| `FIXTURE_PASS` | Passes obvious-fault / normal JSONL fixtures |
| `PARITY_TOLERANCED` | Matches pandas within documented tolerances |
| `PROVEN_SINGLE_BUILDING` | Validated on one real building export |
| `PROVEN_MULTI_BUILDING` | Validated across multiple buildings |

Public cookbook (≈59 headings) vs SQL registry (63 rules) must stay honest;
do not silently diverge badge vs `sql_rules/registry.yaml`.

## BUILDING_100 note

`BUILDING_100`-style package exports remain the primary **single-building**
evidence path for `PROVEN_SINGLE_BUILDING`. Multi-building
`PROVEN_MULTI_BUILDING` claims require additional named buildings and are
**not** claimed by D2 alone. Fixture JSONL under
[`docs/rules/cookbook/fixtures/`](../rules/cookbook/fixtures/) is synthetic
screening evidence (`FIXTURE_PASS`), not a substitute for BUILDING_100.

## Automated mutation check (D2)

```bash
python3 scripts/rule_parity_mutation_check.py
```

| Check | Expectation |
|-------|-------------|
| Registry count | `sql_rules/registry.yaml` ≥ 63 rules |
| Dual cookbooks | `pandas-cookbook.md` + `datafusion-sql-cookbook.md` exist |
| Heading floor | ≥ 59 `### RULE —` headings per cookbook |
| High-risk keywords | `fan-status` / `fan_status`, `occupied` / `occ_mode`, `compressor`, identifiability language |
| Mutation paths | Missing protected cookbook file → exit non-zero |

CI: `.github/workflows/cookbook-parity.yml` runs this after ownership smoke.

## Residual

- Per-rule state column in parity matrix beyond docs notes
- Selective logical mutation of gate predicates (fan-on / occupancy / ΔT) as executable tests
- Honest `PROVEN_MULTI_BUILDING` qualification beyond BUILDING_100
