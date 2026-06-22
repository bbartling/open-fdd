# Modbus live verification

Validates Rust Modbus/TCP read path against a field device or lab simulator.

## Simulated mode (default)

```bash
docker compose up --build
```

`OPENFDD_MODBUS_MODE=simulated` — no external device required.

## Live mode

Set in `.env` or environment:

```text
OPENFDD_MODBUS_MODE=live
OPENFDD_MODBUS_HOST=<device-ip>
OPENFDD_MODBUS_PORT=1502
OPENFDD_MODBUS_UNIT_ID=1
```

```bash
docker compose --env-file .env up --build
```

## API checks

```bash
TOKEN=$(curl -fsS -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"sub":"lab","role":"integrator"}' | jq -r .access_token)

curl -fsS http://127.0.0.1:8080/api/modbus/commission/status \
  -H "Authorization: Bearer $TOKEN" | jq .

curl -fsS -X POST http://127.0.0.1:8080/api/modbus/scan \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{}' | jq .

curl -fsS -X POST http://127.0.0.1:8080/api/modbus/read \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"register":40001,"function":"holding_register"}' | jq .
```

## Pass criteria

- Simulated: response includes `"source":"modbus-simulated"` or equivalent honest label
- Live: `"source":"modbus-tcp-live"` and plausible register values

Implementation: pure Rust in `edge/src/drivers/modbus_live.rs` (FC03/FC04). No Python runtime.
