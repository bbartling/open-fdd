---
title: Cloud export example
parent: Concepts
nav_order: 1
---

# Cloud export example

Open-FDD runs **inside the building, behind the firewall**. It does not push data to the cloud itself. Cloud-based FDD providers, MSI (Monitoring, Savings, and Intelligence) vendors, and commissioning or IoT contractors run their **own** export process: a small script or edge gateway on the building or OT network that **pulls** from the Open-FDD API over the LAN and then sends that data to their cloud or analytics platform. See [Behind the firewall; cloud export is vendor-led](../index#behind-the-firewall-cloud-export-is-vendor-led) on the docs home.

This page describes the **cloud export example** in the repo: a minimal Python script that demonstrates how vendor X, Y, or Z could use the Open-FDD API to get fault and timeseries data and use it as a starting point for their cloud pipeline.

---

## What the example does

The script `examples/cloud_export.py` calls standard Open-FDD download and analytics endpoints and prints the results. In a real integration you would replace the print steps with your own logic: POST to your REST API, write to S3, push to Azure IoT Hub or AWS IoT, send to SkySpark or another analytics platform, etc.

| Step | Endpoint | Purpose |
|------|----------|---------|
| 1 | `GET /download/faults?format=json` | Fault results for programmatic ingestion (JSON) |
| 2 | `GET /download/faults?format=csv` | Fault CSV (Excel-friendly) |
| 3 | `GET /analytics/motor-runtime` | Motor runtime (data-model driven) |
| 4 | `GET /download/csv` | Timeseries wide-format CSV |
| 5 | `GET /analytics/fault-summary` | Fault counts by fault_id |

All requests use date range and optional `site_id`; the API docs at `/docs` list full parameters.

---

## Run the example

**Prerequisites:** Open-FDD API running (e.g. `http://localhost:8000`), `pip install httpx`.

```bash
# From repo root
python examples/cloud_export.py
python examples/cloud_export.py --site default --days 14
API_BASE=http://your-openfdd-host:8000 python examples/cloud_export.py
```

**Docker:** See [`examples/cloud_export/README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/cloud_export/README.md) for building and running the example in a container (e.g. on a vendor edge device that reaches the Open-FDD API over the LAN).

---

## Use it as your starting point

1. **Clone or copy** `examples/cloud_export.py` into your integration codebase.
2. **Keep** the HTTP calls to `/download/faults`, `/download/csv`, and the analytics endpoints; adjust `API_BASE` (or env) to point at the customer’s Open-FDD instance.
3. **Replace** the `print()` / local handling with your cloud send: REST POST, message queue, blob storage, or IoT hub. Add auth (e.g. API key or TLS client cert) if you expose the puller to a wider network.
4. **Schedule** the script (cron, systemd timer, or container restart policy) so you poll the Open-FDD API at the interval that fits your product (e.g. hourly or daily fault sync).

Open-FDD does not initiate outbound cloud connections or manage your data transmission; the example shows how your process can pull data from Open-FDD and then send it to your cloud for deeper insights.
