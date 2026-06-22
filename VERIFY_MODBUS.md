# Verify Modbus live path (RPi bench sensor)

Bench device on Ben's OT LAN:

```text
RPi3B 192.168.204.14:1502  unit_id=1
HR 40001 temp °F x10
HR 40002 temp °C x10
HR 40003 setpoint °F x10 (writable)
IR 30003 humidity x10
```

Simulated CI mode (default compose):

```bash
docker compose up --build
```

Live Modbus against the RPi simulator:

```bash
OPENFDD_MODBUS_MODE=live docker compose --env-file .env up --build
```

Or add to `.env`:

```text
OPENFDD_MODBUS_MODE=live
OPENFDD_MODBUS_HOST=192.168.204.14
OPENFDD_MODBUS_PORT=1502
OPENFDD_MODBUS_UNIT_ID=1
```

API checks:

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"sub":"ben","role":"integrator"}' | jq -r .access_token)

curl -s http://localhost:8080/api/modbus/commission/status \
  -H "Authorization: Bearer $TOKEN" | jq .

curl -s -X POST http://localhost:8080/api/modbus/scan \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .

curl -s -X POST http://localhost:8080/api/modbus/read \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"point_id":"modbus:tcp:1:40001","scale":0.1,"unit":"°F"}' | jq .
```

Expected live read: `"source":"modbus-tcp-live"` and a temperature near the RPi sine wave (~72°F ± amplitude).

Implementation: pure Rust Modbus/TCP in `edge/src/drivers/modbus_live.rs` (FC03/FC04). No Python.
