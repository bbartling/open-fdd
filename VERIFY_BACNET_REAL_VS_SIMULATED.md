# Verify BACnet real vs simulated

## Simulated mode (CI default)

```bash
OPENFDD_BACNET_MODE=simulated docker compose up --build
```

Expect:

- Yellow **SIMULATED** badge in UI
- Driver tree may include `AHU-1 Controller (simulated)` and `192.168.1.100`
- Override scan may return demo priority-8 value `58.0`
- `source` / `generated_from_demo_fixture` indicate simulated data

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"sub":"ci","role":"agent"}' | jq -r .access_token)

curl -s http://localhost:8080/api/drivers/tree \
  -H "Authorization: Bearer $TOKEN" | jq '.source, .generated_from_demo_fixture, .schema_version'
```

## Live mode (OT LAN)

```bash
OPENFDD_BACNET_MODE=live
OPENFDD_BACNET_BIND=192.168.204.55/24:47808
OPENFDD_BACNET_ROUTER_IP=192.168.204.200
OPENFDD_BACNET_MSTP_NET=2000
OPENFDD_BACNET_DISCOVER_LOW=5007
OPENFDD_BACNET_DISCOVER_HIGH=5007

docker compose -f docker-compose.yml -f docker-compose.bacnet-live.yml --env-file .env up --build
```

Expect:

- **LIVE** badge, `source: real` when snapshot is from discovery
- No `AHU-1 Controller`, no `192.168.1.100` in tree
- Override scan uses rusty-bacnet ReadProperty(priority-array); no fixed `58.0`
- If BACnet unavailable: `degraded: true`, visible red warning, `read_errors` in scan response

## Packet proof (manual)

On the OT NIC host:

```bash
sudo tcpdump -ni enp3s0 'udp port 47808' -vv
```

Run Who-Is or override scan from the UI/API and confirm BACnet/IP traffic.

## Rust guard tests

```bash
cargo test -p open_fdd_edge_prototype framework::tests -- --nocapture
```

Tests fail if live validation accepts demo AHU-1 markers or demo override `58.0`.
