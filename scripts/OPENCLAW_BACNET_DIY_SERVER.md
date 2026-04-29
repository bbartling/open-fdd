# OpenClaw + DIY BACnet server → Open-FDD bridge scrape

Open-FDD does **not** speak BACnet on the wire. It calls your **[DIY BACnet Server](https://github.com/bbartling/diy-bacnet-server)** (or any compatible gateway) over **HTTP JSON-RPC** using a fixed contract implemented in `open_fdd/desktop/drivers/bacnet_driver.py`.

**If your DIY server’s paths or JSON differ**, paste its **OpenAPI/Swagger** into the chat (or link it) so the agent can diff against the contract below; you may need a small adapter or a PR to align `bacnet_driver.py`.

---

## What the bridge expects (RPC contract)

- **Base URL** (no trailing slash): e.g. `http://192.168.1.50:8080` or `http://diy-bacnet:8080` from the **same network namespace** as the bridge (OpenClaw container must reach this host/port; publish ports or use Docker host gateway).
- **HTTP:** `POST {base}/client_read_multiple`
- **Headers:** `Content-Type: application/json`, `accept: application/json`; optional `Authorization: Bearer <api_key>` if you set `api_key` on `/config/bacnet` or on `/ingest/bacnet`.
- **Body (JSON-RPC 2.0):**

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "client_read_multiple",
  "params": {
    "request": {
      "device_instance": 123456,
      "requests": [
        {
          "object_identifier": "analog-input,1",
          "property_identifier": "present-value"
        }
      ]
    }
  }
}
```

- **`device_instance`:** integer parsed from each model point’s `bacnet_device_id` (see below).
- **Response (driver expectation):** top-level JSON with `result.data.results` as a **list** aligned with `requests` order; each item should include a numeric or coercible **`value`** (booleans/strings like `active`/`inactive` are mapped to 1.0/0.0). JSON-RPC **`error`** is treated as failure for that device batch.

If your Swagger uses different method names, nesting, or result shapes, document the delta for the agent.

---

## Model points the driver will poll

For `site_id`, each point in `model.json` (via `/model/import` or desktop UI) must include at least:

| Field | Example | Notes |
|--------|---------|--------|
| `site_id` | same as ingest | |
| `external_id` | `sat` | Becomes the **column name** in the BACnet Feather row. |
| `bacnet_device_id` | `device,123456` or `123456` | Driver uses the **integer device instance** (after optional `device,` prefix). |
| `object_identifier` | `analog-input,1` | Passed through to `requests[].object_identifier`. |
| `polling` | `true` | String `"false"` / `"0"` disables polling for that point. |

Optional: `brick_type`, `fdd_input`, `unit` — stored in point metadata after ingest.

If no qualifying points exist for the site, ingest returns **success: false** with a message like *No BACnet points with polling=true found in model for site.*

---

## Bridge API (same as human curl / OpenClaw)

1. **Create site** (if needed): `POST /sites` `{"name":"BACnet Lab"}` → `site_id`.
2. **Import or patch model** with BACnet points: `POST /model/import` with `replace: false` and `points: [...]` including the fields above (see OpenAPI `/docs` on the bridge).
3. **Configure server + optional poll loop:**  
   `POST /config/bacnet`  
   `{"enabled":true,"interval_seconds":300,"site_id":"<id>","server_url":"http://HOST:PORT","api_key":"<optional>"}`  
   Or set env before starting the bridge: `OFDD_BACNET_SERVER_URL`, `OFDD_BACNET_SERVER_API_KEY`, `OFDD_BACNET_SITE_ID`, `OFDD_BACNET_POLL_ENABLED`, `OFDD_BACNET_POLL_INTERVAL_SECONDS`.
4. **One-shot scrape:**  
   `POST /ingest/bacnet`  
   `{"site_id":"<id>","server_url":"http://HOST:PORT","api_key":"<optional>"}`  
   (`server_url` required if not already in config.)
5. **Health:** `GET /config/drivers/health` — check `bacnet` entry; `GET /config/bacnet` for last poll / error.

**Interactive API docs:** with the bridge running, open **`http://127.0.0.1:8765/docs`** (Swagger UI). That is the authoritative list of request bodies; use it alongside this file.

**MCP (optional):** with action tools + shared secret, MCP can proxy `bacnet_config_get` / `bacnet_config_set` / `bacnet_ingest_run` — see `open_fdd/mcp_rag/app.py` and the main smoke doc.

---

## Prompt to paste into OpenClaw

```text
You are wiring Open-FDD desktop bridge BACnet scrape to a DIY BACnet HTTP gateway.

Inputs the human provides (ask if missing):
- Bridge base URL (default http://127.0.0.1:8765)
- DIY server base URL (http/https, reachable FROM the bridge process — same container network or host-published port)
- Optional API Bearer token for the DIY server
- site_id (or create site via POST /sites)
- Whether model points already exist with bacnet_device_id, object_identifier, external_id, polling

Use the repo file scripts/OPENCLAW_BACNET_DIY_SERVER.md as the contract reference (POST {diy}/client_read_multiple JSON-RPC client_read_multiple).

Steps:
1) curl bridge GET /health
2) GET /config/bacnet — note current server_url
3) If the human supplied a Swagger/OpenAPI for the DIY server, compare POST path and JSON body/response to the contract in OPENCLAW_BACNET_DIY_SERVER.md; list any mismatches before calling ingest.
4) POST /config/bacnet with enabled false first, set server_url, site_id, api_key as needed; GET /config/bacnet to confirm
5) Ensure model has at least one BACnet point for that site_id (POST /model/import minimal point if needed — use fields from the markdown table)
6) POST /ingest/bacnet with site_id and server_url (and api_key if required)
7) Report JSON response (success, rows, devices_polled, points_polled, error). If failure, curl the DIY server directly with the same JSON-RPC body (redact secrets) and paste HTTP status + body snippet
8) Optional: enable polling POST /config/bacnet enabled true, wait one interval, GET /config/drivers/health

Stop on hard network/HTTP errors; do not guess device/object ids.
```

---

## Related docs

- **Desktop how-to (BACnet section):** [docs/howto/desktop_app.md](../docs/howto/desktop_app.md) — curl examples for `/ingest/bacnet` and `/config/bacnet`.
- **Phase 2 smoke (merged plots including bacnet):** [OPENCLAW_DASHBOARD_PHASE2_PROMPT.md](OPENCLAW_DASHBOARD_PHASE2_PROMPT.md).
