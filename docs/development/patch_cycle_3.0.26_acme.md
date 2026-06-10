# Patch cycle 3.0.26 — Weather OAT + BACnet override scans (2026-06-10)

## Shipped (`fix/3.0.26-acme-weather-bacnet`)

| Item | Change |
|------|--------|
| Override scans | 15 min BACnet timeout; bridge proxy 900 s; loop try/except so thread survives errors |
| Weather FDD | `acme-oat-vs-web-spread` in `setup_gl36_fdd.py`; configurable columns in `oat_vs_web_spread_1h.py` |
| OAT alias | `scripts/acme_patch_oat_column.py` → `1100-unknown-2` as `oa-t` |
| Portfolio | Fix `override_status` import → `scan_status` |
| Docs | `docs/bacnet/override-scans.md`, polling strategy, JSON API weather section |
| Verify | `acme_operational_verify.sh` — OpenWeather + override status + OAT patch |

## Post-merge deploy

```bash
gh workflow run "Publish Docker addons" --ref master
source infra/ansible/secrets/acme.env.local
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
python3 scripts/acme_patch_oat_column.py --host "$ACME_SSH_HOST" --token "$TOKEN"
python3 scripts/setup_gl36_fdd.py --site-id acme --building-id vm-bbartling \
  --host "$ACME_SSH_HOST" --token "$TOKEN" \
  --ahu-equipment-id acme-vm-bbartling-rtu-01 --fan-point-id 1100-analog-output-1
./infra/ansible/scripts/acme_operational_verify.sh --host "${ACME_SSH_HOST}"
```

## Validate live

```bash
curl -s "$BASE/health" | jq .openfdd_version   # 3.0.26
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/json-api/endpoints" | jq '.endpoints[]|select(.label=="web-oat-t")'
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/bacnet/overrides/status" | jq '{devices:.device_count,last:.last_scan_at}'
# Optional: trigger one override scan (may take several minutes)
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$BASE/api/bacnet/overrides/scan-once"
```
