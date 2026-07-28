# Cookbook parity fixtures

Synthetic `telemetry_pivot` JSONL for offline Pandas parity checks. Not published to GitHub Pages.

Run: `python3 scripts/cookbook_parity_check.py --all`

## Canonical files

| File | Family intent |
|------|---------------|
| `fc1_obvious_fault.jsonl`, `fc2_obvious_fault.jsonl` | AHU FC obvious faults |
| `reset1_obvious_fault.jsonl`, `reset1_normal.jsonl` | Reset fault vs normal |
| `sched1_obvious_fault.jsonl`, `sched247_obvious_fault.jsonl` | Schedule faults |
| `vav1_obvious_fault.jsonl`, `vav6_obvious_fault.jsonl`, `vav7_obvious_fault.jsonl` | VAV faults |

## Milestone C parity states

Honest SQL rule parity states and a mutation-check checklist (no full harness yet)
live in [`docs/migration/MILESTONE_C_RULE_PARITY.md`](../../../migration/MILESTONE_C_RULE_PARITY.md).
