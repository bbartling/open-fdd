# Deterministic fixture catalog (P1-M1-01)

Schema version: `react_parity_fixtures.v1`  
Manifest: [`manifest.json`](manifest.json) (content hashes).

| fixture_id | scenarios | notes |
|---|---|---|
| clean_single_equip | CAP-UPLOAD, CAP-MAP, CAP-RULES | monotonic UTC; °F |
| multi_equip_package | CAP-UPLOAD, CAP-OVERVIEW | AHU + VAV + relationship |
| missing_role | CAP-MAP | unresolved roles |
| dup_timestamps | CAP-UPLOAD | duplicate timestamps |
| irregular_sampling | CAP-RULES | irregular Δt |
| unit_mismatch | CAP-MAP | mixed °C/°F columns |
| empty_interval | CAP-ERRORS | empty CSV body |
| hostile_zip | CAP-UPLOAD | security case placeholders |
| partial_weather | CAP-WEATHER | OAT gaps |
| rule_outcomes | CAP-RULES | pass / insufficient / error |
| job_full | CAP-JOBS, CAP-FINDINGS | meta + mappings + run + findings |
| wattlab_v3 | CAP-WATTLAB | dump v3 stub |

Do not commit confidential Building 100 data. Regenerate hashes after edits:

```bash
python3 - <<'PY'
# or re-run inventory hash refresh used in M1 PR
PY
```

Reference exporter (oracle-only): `tools/react_parity/export_reference_json.py`  
Interaction baseline: `docs/migration/react-rust/evidence/INTERACTION_BASELINE.md`
