# BACnet OT polling policy (production + agent context)

Operators and AI agents must treat BACnet as a **shared, fragile OT resource** — especially on cell-modem edges.

## Production defaults (fieldbus)

| Setting | Production | Dev / bench override |
|---------|------------|----------------------|
| Poll interval | **300 s** (`gateway.toml` `[poll].interval_secs`) | `OPENFDD_FIELDBUS_DEV_FAST_POLL=1` + lower `OPENFDD_FIELDBUS_POLL_INTERVAL_SECS` |
| Minimum interval | **60 s** (enforced unless dev flag) | Same flag allows faster poll for OT gates |
| MQTT publish | **300 s** default (`OPENFDD_MQTT_PUBLISH_INTERVAL_SECS`) | Dev flag allows 5 s floor |
| Point subset | Optional **health roles only** (~30% cap) | Full catalog when dev flag set |

## Health-point subset

Enable for cell sites:

- Env: `OPENFDD_POLL_HEALTH_ONLY=1`
- Or `gateway.toml`: `[poll] health_roles_only = true`

Only points whose `point_name` maps via `haystack_point_to_role` to a known cookbook role are polled. If that set exceeds ~30% of the configured catalog, fieldbus logs a warning and caps the list.

## Agent rules

1. **Never** bulk-discover and poll an entire BACnet network on a production/cell site.
2. Default to **300 s** poll and publish; use faster cadence only on labeled dev benches.
3. Target **~30%** of points — HVAC health roles (AHU SAT/RAT/OAT, VAV flow/temp, chiller/boiler status, key sensors).
4. MS/TP routed devices must be seeded via `field_devices.toml` (`mstp_network`, `mstp_mac`) — see B3 notes in [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md).
5. For hard BACnet commissioning/debug only, use companion [rusty-bacnet-mcp](companion-rusty-bacnet-mcp.md) — **read-only**; do not replace `openfdd-fieldbus`.

## Related

- [`deploy/mqtt/README.md`](../../deploy/mqtt/README.md) — cell payload / bandwidth
- [`AGENTS.md`](../../AGENTS.md) — stack + low-RAM bench
- [`config/fieldbus/gateway.toml`](../../config/fieldbus/gateway.toml) — poll defaults
