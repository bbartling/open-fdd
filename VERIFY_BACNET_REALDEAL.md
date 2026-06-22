# Verify real-deal BACnet override path

Build and run:

```powershell
docker compose down
docker compose build --no-cache
docker compose up
```

Open:

```text
http://localhost:8080
```

Login and run a scan:

```powershell
$TOKEN = (curl.exe -s -X POST http://localhost:8080/api/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"sub\":\"windows-test\",\"role\":\"agent\"}' | ConvertFrom-Json).access_token

curl.exe -s -X POST http://localhost:8080/api/bacnet/overrides/scan-once `
  -H "Authorization: Bearer $TOKEN" `
  -H "Content-Type: application/json" `
  -d "{}"

curl.exe -s http://localhost:8080/api/bacnet/overrides/status `
  -H "Authorization: Bearer $TOKEN"

curl.exe -s http://localhost:8080/api/bacnet/overrides/export `
  -H "Authorization: Bearer $TOKEN"

curl.exe -s http://localhost:8080/api/bacnet/overrides/export/p8 `
  -H "Authorization: Bearer $TOKEN"

curl.exe -s http://localhost:8080/api/bacnet/overrides/export/non-p8 `
  -H "Authorization: Bearer $TOKEN"
```

CSV files should appear on the host at:

```text
.\workspace\overrides\
```

Expected files:

```text
bacnet_overrides.csv
bacnet_priority8_overrides.csv
bacnet_non_priority8_overrides.csv
last_scan.json
```

Honest status:

The scanner service, API, UI buttons, hourly loop, and CSV logging are real Rust code.

Live BACnet (`OPENFDD_BACNET_MODE=live`) uses [rusty-bacnet](https://github.com/jscott3201/rusty-bacnet) v0.9 for:

- Who-Is / I-Am discovery (global + routed MS/TP via `OPENFDD_BACNET_ROUTER_IP` + `OPENFDD_BACNET_MSTP_NET`)
- `POST /api/bacnet/point-discovery` object-list walks
- `POST /api/bacnet/driver/sync-discovery` → `workspace/data/drivers/bacnet/driver_tree.json`
- `POST /api/bacnet/read` present-value reads
- `read_priority_array_for_point` → ReadProperty(priority-array) on writable points

Simulated mode (`OPENFDD_BACNET_MODE=simulated`, CI default) keeps deterministic demo data so Docker/GitHub Actions run without an OT BACnet network.

Bench device **5007** (MS/TP net 2000 behind router `192.168.204.200`) is seeded in `driver_tree.json` with oa-t / oa-h / duct-t / stat_zn-t points.
