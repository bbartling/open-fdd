# Patch cycle 3.0.25 — Acme FDD bundle + mixed units (2026-05-30)

## Shipped (`fix/3.0.25-acme-fdd-bundle`)

| Item | Change |
|------|--------|
| README | PDF docs badge → `pdf/open-fdd-docs.pdf` |
| Flatline windows | `flatline_window_samples()` derives from `poll_interval_s` (60 s → 60 samples/h) |
| Acme rule bundle | Phased Phase 0+1 rules in `setup_gl36_fdd.py`; OAT BLD-B; occupied zone rules; VAV-D airflow fix |
| Mixed units | Documented Trane `metric_temp_f` vs JCI imperial in guidance + setup header |
| Duplicates | Removed stale `rules_py` alias copies (`vav_airflow_low_with_damper_open`, etc.) |
| Docs | `docs/operations/acme_vav_ahu_rule_guidance.md` |
| Validation | `scripts/acme_validate_fdd_bundle.py` (model dedupe, profiles, rule lint) |

## Post-merge deploy

```bash
gh workflow run "Publish Docker addons" --ref master
source infra/ansible/secrets/acme.env.local
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
python3 scripts/setup_gl36_fdd.py --site-id acme --building-id vm-bbartling \
  --host "$ACME_SSH_HOST" --token "$TOKEN" \
  --ahu-equipment-id acme-vm-bbartling-rtu-01 --fan-point-id 1100-analog-output-1
python3 scripts/acme_validate_fdd_bundle.py
./infra/ansible/scripts/acme_operational_verify.sh --host "${ACME_SSH_HOST}"
```

## Validate + tune

```bash
curl -s "$BASE/health" | jq .openfdd_version   # expect 3.0.25
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/building-agent/checkin" \
  -d '{"site_id":"acme","run_fdd_batch":true}' -H 'Content-Type: application/json'
```

## Known follow-ups

- `acme-zn-t-oob-occupied` bounds auto-tune (Arrow sweep analytics)
- Enable economizer / reheat-leak rules after RTU point audit
- Recovery rates — map RTU 1100 fan column in model/feather
