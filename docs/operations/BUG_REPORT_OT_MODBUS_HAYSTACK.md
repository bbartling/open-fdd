# BUG REPORT — OT Modbus / Haystack (low-RAM GHCR loop)

**Date:** 2026-08-25  
**Platform:** `3.3.3` / tip pre-merge of OT gates PR  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`)

Private OT LAN addresses live only in gitignored `scripts/nightly-ot-bench/bench.env.local` (see `bench.env.example`).

## Confirmed PASS (this loop)

| Gate | Result |
|------|--------|
| Modbus `04` vs Pi Modbus TCP sim (gist temp server) | **GATE PASSED** (10 pass / 0 fail) — IR/HR, heartbeat advance, negatives |
| Combined BACnet/MQTT/suspend/synth (earlier post-maint) | **COMBINED_EXIT=0** |
| Stack left up | fieldbus poll running, MQTT up, OT NIC bind from local compose override |

## Open / blocked (next patch cycles)

### B1 — Fieldbus Haystack Basic auth not usable on pin v0.8.1

- Niagara nHaystack requires **HTTP Basic** + insecure TLS ([niagara_sample](https://github.com/jscott3201/rusty-haystack/tree/main/demo/niagara_sample)).
- Fieldbus `services/fieldbus/src/services/haystack.rs` returns *"Basic auth is not supported with the pinned rusty-haystack client"* for `auth_mode=basic`.
- Latest **tagged** rusty-haystack release is still **v0.8.1** (no Basic/`connect_with_config`).
- `main` tip **0.9.0** has Basic but requires **rustc 1.97** + `rand 0.10` — not a safe low-RAM local bump; needs GHCR CI after toolchain alignment or a maintainer **0.9 tag**.

**Workaround in gates:** `05_haystack.sh` can probe Niagara **directly** with `HAYSTACK_USER`/`HAYSTACK_PASS` when `HAYSTACK_EXPECT_LIVE=1` (not via fieldbus).

### B2 — Live SomeRandomPoint not fully closed this pass

- Niagara HTTPS reachable; Workbench shows Random → `SomeRandomPoint`.
- No `HAYSTACK_USER` / `HAYSTACK_PASS` present in bench `.env` on this host → live change assert not executed.
- **Action:** add creds to local `.env` (gitignored), set `HAYSTACK_EXPECT_LIVE=1` in `bench.env.local`, re-run `05_haystack.sh`.

### B3 — rusty-bacnet latest release vs MS/TP seed

- Latest release **v0.10.1** still lacks `add_routed_device` on the published API (only `add_device`).
- Open-FDD keeps **0.9 + vendor patch** for MS/TP routed seed.
- `dev` tip has `add_routed_device(RoutedDeviceConfig)` (unreleased). Next loop: pin/adapt after release **or** temporary `dev` SHA + GHCR MS/TP `02` re-smoke.

### B4 — rusty-modbus

- **Already on v0.1.1** release commit — no bump needed.

## Hygiene note

Keep looping: script/gates PR → merge → (code/dep patches only) watch GHCR → pull → sequential OT re-smoke. No local fieldbus image builds on this host.
