# BUG REPORT — OT Modbus / Haystack (low-RAM GHCR loop)

**Date:** 2026-08-25 (updated 2026-08-26 probe)  
**Platform:** `3.3.3` / `c7dfd92`  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local` / `rusty-haystack/.../.env`.

## Confirmed PASS

| Gate | Result |
|------|--------|
| Modbus `04` vs Pi Modbus TCP sim | **GATE PASSED** |
| BACnet / MQTT / suspend / synth | **PASS** |
| **Direct Niagara nHaystack** (2026-08-26) | **PASS** — see B2 closed below |

## Haystack probe (niagara_sample / BENCH_VALIDATION) — 2026-08-26

From bench host via OT path, following [`rusty-haystack/demo/niagara_sample/BENCH_VALIDATION.md`](https://github.com/jscott3201/rusty-haystack/tree/main/demo/niagara_sample):

| Check | Result |
|-------|--------|
| TCP `:443` | OPEN |
| `GET /haystack/about` HTTP Basic + insecure TLS | **OK** — Niagara 4.15.3.28, nHaystack 3.3.0.0, `v4Fifteen` |
| `read?filter=point and dis=="SomeRandomPoint"` | **OK** — `@C.haystack_tests.SomeRandomPoint`, curVal changing (~50.64 → ~50.36) |
| `read?filter=point and cur` | Multiple live/stale points (BACnet bindings + SomeRandomPoint) |

**Conclusion:** Niagara + creds + firewall are fine. Failure is **only** Open-FDD fieldbus client pin (no Basic on rusty-haystack **v0.8.1**).

## Open / blocked

### B1 — Fieldbus Haystack Basic auth not usable on pin v0.8.1 (OPEN)

- Fieldbus returns 502 / auth failure for `/haystack/*` (tries SCRAM-style path).
- Latest **tagged** rusty-haystack is still **v0.8.1**. Tip **0.9.0** has `AuthMode::Basic` + `connect_with_config` / `ClientConfig::niagara_lab()` but needs newer rustc / `rand` — bump via **GHCR**, not local cargo on this host.
- **Preferred architecture:** split Haystack into its own GHCR service (`openfdd-haystack`) so BACnet/Modbus fieldbus is not blocked by haystack dep churn. Same MQTT telemetry schema (`protocol: haystack`).

### B2 — Live SomeRandomPoint — CLOSED at Niagara layer

- Direct HTTPS Basic read works; value changes.
- Remaining: wire same read through Open-FDD after B1 fix; set `HAYSTACK_EXPECT_LIVE=1` in gitignored `bench.env.local` for gate.

### B3 — rusty-bacnet `add_routed_device` — OPEN (MS/TP)

- Release **v0.10.1** lacks it; vendor 0.9 patch remains; `dev` tip has new API.

### B4 — rusty-modbus — CLOSED (on v0.1.1)

## Point discovery (product)

Straightforward path after B1:

1. `POST /haystack/read` with filter `point and cur` (or operator filter).
2. Present grid → operator picks rows → save bindings (id / dis / kind) into site config.
3. Poll selected ids on interval → MQTT telemetry like BACnet points.

Do **not** invent a second discovery protocol; use Haystack `read`/`nav` allowlist already on fieldbus.

## Hygiene

Keep looping: probe Niagara with demo scripts → patch fieldbus/haystack service via GHCR → OT gates → UI.
