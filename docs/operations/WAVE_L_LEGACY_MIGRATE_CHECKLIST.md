# Wave L — Legacy-tenant migrate operator checklist (L7)

**Scope:** Map today’s single-hub inventory into control-plane tenant **`legacy`**.  
**Default:** dry-run only. **No silent live migrate** on Railway volumes or customer DNS.

Related: [`ADR_multi_client_shared_hosting.md`](../architecture/ADR_multi_client_shared_hosting.md) · dry-run script [`scripts/ops/wave_l_legacy_migrate_dry_run.sh`](../../scripts/ops/wave_l_legacy_migrate_dry_run.sh)

## Preconditions

- [ ] Wave L tip LIVE; `multi_tenant=false` on `/api/health`
- [ ] Backup taken (`scripts/railway_central_workspace_backup.sh` / Railway CLI skill)
- [ ] Rollback pin known: Wave K **`sha-9c3e8b1` / 3.4.0**
- [ ] Operator authorization recorded (who / when / why)

## Dry-run (required)

```bash
export OPENFDD_API_BASE=https://openfdd-web-production-af99.up.railway.app
export RAILWAY_ADMIN_PASSWORD=…   # from Railway vars; do not clobber with local .env
./scripts/ops/wave_l_legacy_migrate_dry_run.sh
```

Expect:

- `migrate_plan.json` with `writes: false`, `target_tenant_id: "legacy"`
- Package buildings + MQTT sites listed under `planned_building_ids`
- Exit **2** if `APPLY=1` on HTTPS hub (refused)

## Planned cutover (manual — not Wave L auto)

1. Keep **`OPENFDD_MULTI_TENANT=false`** until Tier-2 A?B evidence is accepted.
2. When enabling mode in **lab only**: assign all inventoried buildings to tenant `legacy` in the control-plane file; do **not** delete Parquet.
3. Prefer additive `tenants/legacy/…` prefix when rewriting roots; hub root remains SoT while flag OFF.
4. Verify `/api/tenants` lists `legacy` and historian_prefix stays empty while OFF.
5. Smoke gates **11–16** (and **17** dry-run) before any production enable.

## Rollback

1. Flag OFF ? single-tenant hub semantics.
2. Re-pin GHCR to Wave K **`sha-9c3e8b1`** (central ? mqtt ? web ? fieldbus).
3. Do not delete Parquet during failed experiments.

## Sign-off

| Field | Value |
|-------|-------|
| Operator | |
| Date (UTC) | |
| Tip / health | |
| Dry-run artifact | |
| Authorized live APPLY? | **no** (Wave L) / yes (post–Wave L Stage C) |
