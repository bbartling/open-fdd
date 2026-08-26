# BUG REPORT — OT Modbus / Haystack (low-RAM GHCR loop)

**Date:** 2026-08-26  
**Platform:** `3.3.4` / `8e7899e` (`sha-8e7899e` GHCR; includes tip `b1811da` + #778 Haystack Basic + #780 edge kits / agent auth / nginx resolver fix)  
**Host:** low-RAM GHCR-only bench (`OPENFDD_QUERY_MEMORY_MB=256`)

Private OT LAN addresses and Niagara creds live only in gitignored `.env` / `bench.env.local` / `rusty-haystack/.../.env`.

## Confirmed PASS

| Gate | Result |
|------|--------|
| Stack health `/api/health` | **PASS** — `3.3.4+8e7899e62c3d` |
| Synthetic-59 target pairs | **PASS** — 59/59 |
| Synthetic-59 overview analytics | **PASS** — 0 fails |
| Synthetic-59 health-matrix fault hours | **PASS** — 0 fails |
| Modbus `04` vs Pi Modbus TCP sim | **GATE PASSED** (10 pass / 0 fail) |
| Haystack `05` live (`HAYSTACK_EXPECT_LIVE=1`) | **GATE PASSED** — see B1/B2 closed |
| Fieldbus `/health` | **PASS** — poll_running, bacnet/modbus/haystack sidecars green on stack strip |

## Haystack via fieldbus (B1 / B2) — CLOSED

Proven on tip fieldbus (not only direct Niagara):

| Check | Result |
|-------|--------|
| `GET /haystack/about` via fieldbus | **OK** — Niagara 4 / nHaystack 3.3.0.0 grid |
| `POST /haystack/read` `point and dis=="SomeRandomPoint"` | **OK** — `@C.haystack_tests.SomeRandomPoint` |
| Live curVal change through fieldbus | **OK** — e.g. `50.1747 → 50.2187` (gate parse fixed; see Hygiene) |
| Allowlist (`/haystack/eval`) | **OK** — HTTP 404 |

**Conclusion:** #778 Basic auth on rusty-haystack **v0.8.1** is sufficient for this Niagara lab. Preferred long-term split to `openfdd-haystack` remains an architecture note, not a blocker for Basic.

## Open / residual

### B3 — rusty-bacnet `add_routed_device` / MS/TP routing — OPEN

BACnet `02` on this tip: **GATE FAILED** (hosted server 599999 objects PASS; device **5007** routed MS/TP + BIP companions FAIL — “device not in device table” / UNKNOWN_OBJECT class failures). Still needs bacnet crate bump / seed of routed devices; not closed by 3.3.4.

### MQTT ingest growth (`03`) — FAIL this run (honest)

- Central MQTTS client **connected** (`mqtt:8883`).
- After forced fieldbus `poll/once`, **ingest_ok stayed 0**; MQTTS subscribe peek captured no telemetry; feather file count unchanged in the wait window.
- Likely coupled to BACnet poll producing no live points (B3) rather than broker down. Re-check after bacnet routing is fixed or with a dedicated Modbus→MQTT publish path.

### Agent password on bench

`GET /api/auth/status` → `agent_login_configured: false` until `OPENFDD_AGENT_PASSWORD` is set in compose `.env` (Railway docs require it; optional on LAN admin-only benches).

## Point discovery (product)

Unchanged happy path after B1:

1. `POST /haystack/read` with filter `point and cur` (or operator filter).
2. Present grid → operator picks rows → save bindings.
3. Poll selected ids → MQTT telemetry like BACnet points.

## Hygiene

- GHCR publish for `b1811da` was cancelled/timed out earlier; tip images for this report are **`sha-8e7899e`** after #780 (nginx `15-openfdd-resolver.envsh` executable + 90m GHCR test timeout).
- Haystack gate `extract_cur_val` previously fed JSON via stdin into a `<<'PY'` heredoc (stdin stolen → empty v1/v2). Fixed to pass payload via env; gate now correctly PASSes live change.
- Do not invent a second discovery protocol; use Haystack `read`/`nav` allowlist on fieldbus.
