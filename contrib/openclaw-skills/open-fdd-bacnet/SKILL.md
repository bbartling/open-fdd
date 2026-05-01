---
name: open-fdd-bacnet
description: Wire Open-FDD desktop BACnet ingest to a DIY BACnet HTTP JSON-RPC gateway; uses bridge /config/bacnet and /ingest/bacnet.
---

# Open-FDD BACnet + DIY server (OpenClaw)

## When to use

- Operator has a **DIY BACnet Server** (or compatible) exposing **`POST {base}/client_read_multiple`** JSON-RPC.
- Goal is **model points** with `bacnet_device_id`, `object_identifier`, `external_id`, `polling`, then **ingest** via the Open-FDD bridge.

## Contract (summary)

- **POST** `{diy_base}/client_read_multiple`
- **Headers:** `Content-Type: application/json`, optional `Authorization: Bearer <api_key>`
- **Body:** JSON-RPC 2.0 with `method`: `client_read_multiple` and `params.request` containing `device_instance` and `requests[]` with `object_identifier`, `property_identifier` (typically `present-value`).

Full tables and examples: **`scripts/OPENCLAW_RUNBOOK.md`** section **6) DIY BACnet server contract**.

## Bridge sequence

1. `POST /sites` → `site_id`
2. Ensure model has BACnet points (`POST /model/import` if needed)
3. `POST /config/bacnet` — `server_url`, `site_id`, optional `api_key`, polling `enabled` / `interval_seconds`
4. `POST /ingest/bacnet` — `site_id`, optional overrides
5. `GET /config/drivers/health`, `GET /config/bacnet` for status

## Safety

- Confirm **DIY base URL** is reachable **from the bridge process** (not only from the agent container).
- Do not guess **device_instance** or **object_identifier**; use operator-supplied lists or discovery output.

## References

- `scripts/OPENCLAW_RUNBOOK.md` §6–7, `docs/howto/desktop_app.md`, `open_fdd/platform/drivers/bacnet_driver.py`.
