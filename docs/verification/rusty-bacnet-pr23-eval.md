# rusty-bacnet PR #23 compatibility (Open-FDD 3.2.2)

**Upstream:** [jscott3201/rusty-bacnet#23](https://github.com/jscott3201/rusty-bacnet/pull/23) — network sample binaries (Who-Is, point discovery, RPM read, WriteProperty + priority-array verify).

**Status (2026-06-27):** Open. Samples and additive server APIs; no breaking changes to `bacnet-client` 0.9 APIs used by Open-FDD.

## Verdict

**No driver modifications required for 3.2.2 merge.**

Open-FDD edge drivers already implement the same production patterns exercised in PR #23:

| Capability | PR #23 sample | Open-FDD implementation |
|------------|---------------|-------------------------|
| Who-Is discovery | `whois-scan` | `bacnet_live::whois_devices`, poll/discover paths |
| Object-list / points | `point-discover` | `discover_device_points_rpm` + sequential fallback |
| RPM present values | `rpm-read` | `poll_present_values_rpm`, override scan RPM batch |
| WriteProperty + priority | `bacnet-write` | `write_present_value` → `write_property_to_device` |
| Priority-array scan | write sample verify | `read_priority_array`, `read_priority_arrays_rpm` |
| Local BACnet server | `mini-device-revisited` | `bacnet_server_runtime.rs` (`BACnetServer`, `DeviceConfig.vendor_id`) |

## Dependency pins (edge `Cargo.toml`)

```toml
bacnet-client = "0.9"
bacnet-server = "0.9"  # package name: rusty-bacnet-server
```

Published **0.9** crates do not yet include PR #23’s additive APIs:

- `BACnetServer::broadcast_i_am()` (lifecycle.rs)
- `BipServerBuilder::vendor_id()` (server/mod.rs)

Open-FDD already sets `vendor_id` on `DeviceConfig` when building the Device object. I-Am broadcast from the local Open-FDD server is a **nice-to-have follow-up** after upstream merges and a crates.io release — not a blocker.

## Integration tests

Field BACnet tests are opt-in only (`OPENFDD_BACNET_INTEGRATION=1`, device from env — no bench ID hardcoding):

- `edge/tests/bacnet_live_integration.rs`

## Post-merge follow-up (when PR #23 lands on crates.io)

1. Bump `bacnet-*` workspace deps to the release that includes `broadcast_i_am`.
2. Call `broadcast_i_am()` once after `BACnetServer` start (and optionally on interval) so device 599999 is discoverable on the LAN.
3. Re-run opt-in integration against field gear.

## References

- `edge/src/drivers/bacnet_live.rs` — client: Who-Is, RPM, WriteProperty
- `edge/src/drivers/bacnet.rs` — facade: override scan, poll cycles, CSV retention
- `edge/src/drivers/bacnet_server_runtime.rs` — local Open-FDD BACnet/IP server
