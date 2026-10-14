# Grok Soft-OPEN — ACME + Railway hub (3.6.3)

**Soft-OPEN ≠ FQ.** Stay on the **newest GHCR `sha-*` tip** pinned to Railway after Publish.
Wrong tip / empty hub / stale nightly = **FAIL**.

## FORBIDDEN (strict)

1. **No site / DB / volume backups.** ACME + Railway Soft-OPEN is **not production**. Do **not** run backup scripts, `railway_central_workspace_backup.sh`, or invent `OPENFDD_BACKUP_ON_UPDATE` for this Soft-OPEN.
2. **No Desktop worktrees.** Agents use `/tmp/open-fdd-wt-*` only. ART under `/tmp/openfdd-softopen/3.6.3/` + durable `~/Documents/openfdd-softopen-art/3.6.3/`.
3. **No dual-write / Parquet co-canonical / DataFusion resurrection.**
4. **No `compose down -v` / volume prune.** Do not auto-delete the pending-delete central volume (owner Railway UI only).

## Candidate

- Resolve tip: `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web openfdd-mqtt`
- Confirm Railway hub services show that `sha-*` and `/api/health` reports **3.6.3+…** matching the tip.
- Record immutable digests + OCI created in ART `CANDIDATE_MANIFEST.md`.

## Exercise (real browser)

1. Login to **Railway public web** (ACME hub Soft-OPEN).
2. Site: live **ACME** (and BUILDING_100 if present for open issues).
3. Overview: tables/health matrices load; do **not** spam Run-all if results already current — prefer Lab single-rule when tuning.
4. FDD Plots: lean plot / fault detail / confirmed_fault when hours > 0.
5. RCx: at least one preset with nonempty series.
6. SPARQL / Model: predefined query if ready (mech-system summary Soft-OPEN when shipped).
7. Note continuous ingest / memory in `RAILWAY_CRASH_MEMORY_NOTES.md`.
8. Fill `SOFTOPEN_MATRIX.md` with PASS/FAIL/BLOCKED/NOT_RUN per row — no silent PASS.

## Exit

Write SUMMARY under `/tmp/openfdd-softopen/3.6.3/grok/` and copy to `~/Documents/openfdd-softopen-art/3.6.3/`. Soft-OPEN ≠ FQ.
