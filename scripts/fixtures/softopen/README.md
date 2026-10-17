# Soft-OPEN stress fixtures

## `SYNTH_03_timeseries_semantic_meta.zip`

Committed package for Soft-OPEN gates (#1281): timeseries + `semantic_meta.json`
+ AHU/VAV maps (`openfdd_package_v1`). Synthetic only.

Import (JWT required):

```bash
# example — use hub import route or package import UI/API
python - <<'PY'
# Prefer product POST /api/csv/import/package with confirm:true
print("see scripts/softopen/README.md and stress helpers")
PY
```

Building id inside zip: `SYNTH_03`. For unique Soft-OPEN runs, re-pack or
remap building_id after import when the API supports rename.
