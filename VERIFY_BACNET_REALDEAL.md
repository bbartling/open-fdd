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

The scanner service, API, UI buttons, hourly loop, and CSV logging are now real Rust code.

The actual BACnet field-bus read is intentionally isolated in:

```text
edge/src/drivers/bacnet.rs
read_priority_array_for_point(...)
```

That function currently returns deterministic data so the end-to-end pipeline can be tested without hardware. Replace that adapter with `rusty-bacnet` ReadProperty(priority-array) calls for live BACnet devices.
