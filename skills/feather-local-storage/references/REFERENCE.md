# Feather storage — reference

Legacy: `open_fdd/desktop/storage/paths.py`, `feather_store.py`, `connectors.py`.

## Paths

| Function | Result |
|----------|--------|
| `desktop_data_dir()` | `OFDD_DESKTOP_DATA_DIR` or OS user data `open-fdd-desktop` |
| `feather_root()` | `<data_dir>/feather_store` |
| `model_json_path()` | `<data_dir>/model.json` |
| `model_ttl_path()` | `OFDD_MODEL_TTL_PATH` or `<data_dir>/data_model.ttl` |
| `default_rules_root()` | `<data_dir>/rules` |

## Bridge endpoints (legacy)

- `GET /storage/timeseries/stats`
- `POST /storage/timeseries/purge`
