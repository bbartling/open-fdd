# BACnet OT polling policy (production + agent context)

Operators and AI agents must treat BACnet as a **shared, fragile OT resource** — especially on MS/TP trunks and cell-modem edges.

## Hard rules (Wave N)

1. **`openfdd-fieldbus` is never deployed on Railway / public cloud.** It is an **OT-behind-firewall** edge only. Cloud hub = `openfdd-central` + `openfdd-mqtt` + `openfdd-web` (+ optional `openfdd-mcp`). Fieldbus publishes **inbound MQTTS** to the hub.
2. **Poll + MQTT publish interval is fixed at 300 seconds** (compiled into fieldbus). Operator env/TOML knobs that used to lower the interval are **ignored**. This protects legacy MS/TP from MQTTS bursts.
3. Target **~30%** of configured points — HVAC health / cookbook roles only (`OPENFDD_POLL_HEALTH_ONLY=1` or `[poll] health_roles_only = true`). Bandwidth throttle is the point subset, **not** a faster poll.
4. **Never** bulk-discover and poll an entire BACnet network on a production site.
5. MS/TP routed devices must be seeded via `field_devices.toml` (`mstp_network`, `mstp_mac`) — see B3 notes in [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md).
6. For hard BACnet commissioning/debug only, use companion [rusty-bacnet-mcp](../mcp-agents/companion-rusty-bacnet-mcp.md) — **read-only**; do not replace `openfdd-fieldbus`.

## Production defaults (fieldbus)

| Setting | Production |
|---------|------------|
| Poll interval | **300 s fixed** (`FIXED_POLL_INTERVAL_SECS` in fieldbus Rust) |
| MQTT publish | **300 s fixed** (aligned with poll) |
| Point subset | Optional **health roles only** (~30% cap) |

## Agent rules

1. Do not ask for or invent a poll interval below 300 s.
2. Prefer health-role catalogs on live OT (especially MS/TP).
3. After GHCR fieldbus refresh, wait ≥ one 300 s cycle before declaring ingest dead.
4. Private site kits (ACME, etc.) stay off GitHub; use generic patterns in public docs only.

## Related

- [`deploy/mqtt/README.md`](../../deploy/mqtt/README.md) — cell payload / bandwidth
- [`AGENTS.md`](../../AGENTS.md) — stack + low-RAM bench
- [`services/fieldbus/AGENTS.md`](../../services/fieldbus/AGENTS.md) — fieldbus agent contract
- [`config/fieldbus/gateway.toml`](../../config/fieldbus/gateway.toml) — non-interval settings
- Wave N tracker: [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md)
- Local Mint Who-Is + MQTTS smoke: [`LOCAL_BACNET_BACPYPE3_BENCH.md`](LOCAL_BACNET_BACPYPE3_BENCH.md)
