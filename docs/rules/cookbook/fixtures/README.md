# Cookbook parity fixtures

Fixtures use declared source-unit metadata and SI-processing expectations. Frozen IP goldens are qualification data only. Offline fixture results do not prove post-cutover live P3 or FQ.

Synthetic `telemetry_pivot` JSONL for offline Pandas parity checks. Not published to GitHub Pages.

Run: `python3 scripts/cookbook_parity_check.py --all`

## Canonical files

| File | Family intent |
|------|---------------|
| `fc1_obvious_fault.jsonl`, `fc2_obvious_fault.jsonl` | AHU FC obvious faults |
| `reset1_obvious_fault.jsonl`, `reset1_normal.jsonl` | Reset fault vs normal |
| `sched1_obvious_fault.jsonl`, `sched247_obvious_fault.jsonl` | Schedule faults |
| `vav1_obvious_fault.jsonl`, `vav6_obvious_fault.jsonl`, `vav7_obvious_fault.jsonl` | VAV faults |

The fixture suite includes unit vectors for declared source units and SI processing. Frozen IP goldens remain qualification test data only. Fixture results do not establish live post-cutover P3 or FQ.


## Milestone C parity states

Honest SQL rule parity states and a mutation-check checklist (no full harness yet)
live in [`docs/migration/MILESTONE_C_RULE_PARITY.md`](../../../migration/MILESTONE_C_RULE_PARITY.md).
