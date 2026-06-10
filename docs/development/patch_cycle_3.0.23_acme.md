# Patch cycle 3.0.23 — Acme FDD tuning fixes (2026-06-11)

## Shipped (`fix/3.0.23-acme-tuning`)

| Bug | Fix |
|-----|-----|
| Poll health 0/33 (all historian_lag) | Dedupe model points by `point_id`; use `resolve_historian_column` so fdd aliases (`da-t`) don't shadow live BACnet columns |
| VAV damper/airflow/reheat rules error | Return `pa.array([False]*n)` when columns missing; fix damper cast-on-timestamp bug |
| `/health` shows 3.0.21 | Sync `open_fdd.__version__` with `pyproject.toml` |
| `acme-ahu-run-hours` pytz error | Strip tz from Arrow timestamp before script metrics (same as acme_rtu recipe) |

## Post-merge deploy

```bash
gh workflow run "Publish Docker addons" --ref master
# wait for success
source infra/ansible/secrets/acme.env.local
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
python3 scripts/setup_gl36_fdd.py --site-id acme --building-id vm-bbartling --host "$ACME_SSH_HOST" --token "$TOKEN"
```

## Validate + tune

```bash
curl -s "$BASE/health" | jq .openfdd_version   # expect 3.0.23
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/building-agent/checkin" \
  -d '{"site_id":"acme","run_fdd_batch":true}' -H 'Content-Type: application/json'
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/building-agent/tuning-brief?site_id=acme"
```

## Known follow-ups (3.0.24+)

- `acme-zn-t-oob-occupied` ~71% — needs analytics on Arrow sweep for bounds tuning proposals
- Recovery rates `—` — map RTU 1100 fan point in model/feather
- 64 unique columns / 128 zone sensors — model column uniqueness + re-ingest
