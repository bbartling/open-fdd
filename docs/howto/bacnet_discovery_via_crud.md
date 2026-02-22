---
title: BACnet discovery via CRUD (step-by-step)
parent: How-to Guides
nav_order: 5
---

# BACnet discovery via CRUD (step-by-step)

After a blank data model (e.g. you ran the [delete-all-sites and reset](danger_zone#delete-all-sites-and-reset) flow), you can learn in new BACnet devices by driving the API yourself. No new data gets orphaned: create site → equipment (optional) → points with BACnet refs, then push discovery into the graph so Brick and BACnet align.

Use **BASE** = your API base URL (e.g. `http://localhost:8000` or `http://192.168.204.16:8000`). All requests use `accept: application/json` and, for POST/PATCH/PUT, `content-type: application/json`.

---

## 1. (Optional) Discover devices — Who-Is

See which BACnet devices respond in an instance range:

```bash
curl -X POST "${BASE}/bacnet/whois_range" \
  -H "accept: application/json" \
  -H "content-type: application/json" \
  -d '{"request": {"start_instance": 1, "end_instance": 3456799}}'
```

Use the gateway `url` in the body if needed (e.g. `"url": "http://192.168.1.50:8080"`). Omit to use the server default (e.g. `OFDD_BACNET_SERVER_URL` or `http://localhost:8080`). From the response, pick a **device_instance** (e.g. `3456789`) for the next step.

---

## 2. Get points for one device — Point discovery (JSON only)

Returns the list of objects for that device. You’ll use this to create points in the DB:

```bash
curl -X POST "${BASE}/bacnet/point_discovery" \
  -H "accept: application/json" \
  -H "content-type: application/json" \
  -d '{"instance": {"device_instance": 3456789}}'
```

Response shape (from diy-bacnet-server): `result.data.objects` is a list of objects. Each has at least:

- **object_identifier** — e.g. `"analog-input,1"`, `"device,3456789"`
- **object_name** or **name** — human-readable name

Skip the `device` object when creating points; use analog-input, binary-value, etc. Save the **device_instance** and the **objects** list; you’ll use them in step 4.

---

## 3. Push device into the graph (Brick + BACnet in TTL)

So the in-memory graph and `config/data_model.ttl` contain this device’s BACnet RDF:

```bash
curl -X POST "${BASE}/bacnet/point_discovery_to_graph" \
  -H "accept: application/json" \
  -H "content-type: application/json" \
  -d '{
    "instance": {"device_instance": 3456789},
    "update_graph": true,
    "write_file": true
  }'
```

You can do this **before** or **after** creating sites/points in the DB. Doing it before lets you inspect the TTL; doing it after keeps Brick (from DB) and BACnet (from discovery) in sync after your CRUD.

---

## 4. CRUD: Create site

```bash
curl -X POST "${BASE}/sites" \
  -H "accept: application/json" \
  -H "content-type: application/json" \
  -d '{"name": "MyBuilding", "description": "Main campus"}'
```

From the response, copy **id** → `SITE_ID`.

---

## 5. (Optional) CRUD: Create equipment

```bash
curl -X POST "${BASE}/equipment" \
  -H "accept: application/json" \
  -H "content-type: application/json" \
  -d '{"site_id": "'"${SITE_ID}"'", "name": "AHU-1", "description": "Air handler"}'
```

Copy **id** → `EQUIPMENT_ID`. If you skip equipment, omit `equipment_id` when creating points.

---

## 6. CRUD: Create points (one per BACnet object)

For each object from step 2 (excluding the `device,...` object), create a point with BACnet addressing so the scraper and FDD can use it:

```bash
curl -X POST "${BASE}/points" \
  -H "accept: application/json" \
  -H "content-type: application/json" \
  -d '{
    "site_id": "'"${SITE_ID}"'",
    "external_id": "ZoneTemp",
    "bacnet_device_id": "3456789",
    "object_identifier": "analog-input,1",
    "object_name": "Zone Temperature",
    "equipment_id": "'"${EQUIPMENT_ID}"'"
  }'
```

- **site_id** (required): UUID from step 4.
- **external_id** (required): unique per point; used as the time-series key (e.g. `ZoneTemp`, or the BACnet object_name).
- **bacnet_device_id**: device instance as string (e.g. `"3456789"`).
- **object_identifier**: e.g. `"analog-input,1"`.
- **object_name**: optional but useful for display.
- **equipment_id**: optional; use if you created equipment in step 5.

Repeat for each object you want to scrape. You can add **brick_type** and **fdd_input** (rule_input) now or later via **PATCH /points/{id}** or **GET /data-model/export** → edit → **PUT /data-model/import**.

---

## 7. (Optional) Tag Brick / rule_input in bulk

- **GET /data-model/export?site_id=...** — list points with BACnet refs.
- Edit the JSON (set **brick_type**, **rule_input** per point).
- **PUT /data-model/import** with the edited list (use **point_id** from export). BACnet refs are preserved.

---

## 8. Verify

- **GET /sites** — list sites.
- **GET /points?site_id=...** — list points; check `bacnet_device_id` and `object_identifier`.
- **GET /data-model/check** — triple count, orphan count, sites/devices.
- **GET /data-model/ttl** — full TTL (Brick + BACnet).

Then run the BACnet scraper; it will read only points that have `bacnet_device_id` and `object_identifier` set.
