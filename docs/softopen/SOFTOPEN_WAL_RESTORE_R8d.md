# Soft-OPEN R8d — Timescale WAL / restore tip-safe contract

Soft-OPEN ≠ FQ. **No Soft-OPEN agent site/DB/Railway backups.**

## Tip-safe Soft-OPEN (what this train claims)

| Item | Soft-OPEN state |
| --- | --- |
| Product historian | Timescale only (`OPENFDD_HISTORIAN=timescale`); dual_write=false |
| Parquet compaction / Parquet data-budget | Soft-OPEN **N/A** envelopes on Timescale tip (#1244) |
| Soft-OPEN Railway hub | Re-pin GHCR `sha-*` after Publish; **do not** instruct Grok/agents to take volume/DB backups |
| Local `workspace/` tar backups | Production/local lifecycle docs only — **forbidden** as Soft-OPEN overnight proof |
| Timescale WAL / PITR / restore drill | **FQ still open** — not Soft-OPEN-complete |

## Forbidden during Soft-OPEN

- `railway volume` delete / reattach / “heroic” restore from agents (owner UI only)
- Soft-OPEN prompts that tell Grok to backup ACME/Railway/DB
- Claiming FQ durability from green CI, API smoke, or tip health alone
- Treating empty Parquet roots under `/tmp/openfdd` as product restore paths

## Still need for FQ (out of Soft-OPEN scope)

- Documented Timescale backup/WAL/retention/restore runbook with ART evidence
- Fresh-volume upgrade + rollback proof against shared SQL contract hash
- Image Soft-OPEN without bind mounts under load

Locks: Rust · Timescale only · `/tmp` worktrees · Soft-OPEN ≠ FQ.
