# BACnet override scanner

Validates the Rust override watch path: priority-array scan, status API, CSV export, and workspace persistence.

## Build and run

```bash
docker compose down
docker compose build --no-cache
docker compose up
```

Open `http://127.0.0.1:8080` and sign in.

## API smoke

```bash
TOKEN=$(curl -fsS -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"sub":"lab","role":"integrator"}' | jq -r .access_token)

curl -fsS -X POST http://127.0.0.1:8080/api/bacnet/overrides/scan-once \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{}'

curl -fsS http://127.0.0.1:8080/api/bacnet/overrides/status \
  -H "Authorization: Bearer $TOKEN" | jq .

curl -fsS http://127.0.0.1:8080/api/bacnet/overrides/export \
  -H "Authorization: Bearer $TOKEN" | head

curl -fsS http://127.0.0.1:8080/api/bacnet/overrides/export/p8 \
  -H "Authorization: Bearer $TOKEN" | head
```

## Expected workspace files

```text
workspace/bacnet/overrides/registry.json
workspace/bacnet/overrides/overrides_export.csv
workspace/overrides/bacnet_overrides.csv
workspace/overrides/bacnet_priority8_overrides.csv
workspace/overrides/bacnet_non_priority8_overrides.csv
workspace/overrides/last_scan.json
```

Environment:

```bash
OFDD_OVERRIDE_SCAN_INTERVAL_S=3600
OFDD_OPERATOR_OVERRIDE_PRIORITY=8
```

## Mode honesty

| Mode | Behavior |
| --- | --- |
| `simulated` | Deterministic demo data for CI and lab without OT BACnet |
| `live` | rusty-bacnet Who-Is, object-list, ReadProperty, priority-array on your LAN |

Live BACnet uses [rusty-bacnet](https://github.com/jscott3201/rusty-bacnet) for discovery, reads, and override scans. Simulated mode never pretends to be live.

The scanner service, API, UI actions, hourly loop, and CSV logging are real Rust code in all modes.
