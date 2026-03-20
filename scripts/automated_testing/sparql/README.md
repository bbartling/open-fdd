# SPARQL queries for Open FDD data model

These `.sparql` files match the [SPARQL cookbook](../../../docs/modeling/sparql_cookbook.md) and mirror the **Data Model Testing** tab predefined buttons (Summarize your HVAC). Run them via:

- **API:** `POST /data-model/sparql` with body `{"query": "<contents>"}` (or use **POST /data-model/sparql/upload** with the file).
- **Frontend:** **Data Model Testing** tab (`/data-model-testing`) → click a predefined button (Sites, AHUs, Zones, …) or use Custom SPARQL → **Upload .sparql file** or paste query → Run SPARQL. **Data Model Setup** (`/data-model`) has sites, equipment, import, and **View full data model (TTL)**.

The script **2_sparql_crud_and_frontend_test.py** in the parent directory:

- Runs each `.sparql` file against the API, then (with `--frontend-parity`) tests the frontend on the **Data Model Testing** page in two ways: **upload each .sparql file** and **paste each query** in the form, asserting both match.
- **Expected results:** When `config/data_model.ttl` exists and **rdflib** is installed, expected bindings are computed from that TTL. Alternatively, place golden JSON in **expected/** (e.g. `expected/01_platform_config.json`). Use `--expected-from-ttl` to require TTL-based expected; use `--generate-expected` to write `expected/*.json` from the current API.

| File | Cookbook / frontend |
|------|---------------------|
| 01_platform_config.sparql | Recipe 1: Platform config |
| 02_sites_labels.sparql | Recipe 2 / **Sites** button |
| 02_site_counts.sparql | Recipe 2: Site aggregate counts |
| 03_equipment_labels_testbench.sparql | Recipe 3: Equipment for test-bench site (TestBenchSite + demo_site_llm_payload.json) |
| 03_point_labels_testbench.sparql | Recipe 3: Points for test-bench site |
| 04_bacnet_devices.sparql | Recipe 4: BACnet devices |
| 05_brick_rule_mapping.sparql | Recipe 5: Brick → rule input |
| 06_polling_points_brick_type.sparql | Polling points with Brick type + unit (no BACnet) |
| 07_count_triples.sparql | Recipe 7: Triple count |
| 08_bacnet_telemetry_points.sparql | BACnet telemetry points (polling=true + Brick + BACnet) |
| 09_graph_db_sync_counts.sparql | Graph vs DB sync (sites, equipment, points counts) |
| 10_ahus.sparql | **AHUs** button |
| 11_zones.sparql | **Zones** button |
| 12_building.sparql | **Building** button |
| 13_vav_boxes.sparql | **VAV boxes** button |
| 14_vavs_per_ahu.sparql | **VAVs per AHU** button |
| 15_chillers.sparql | **Chillers** button |
| 16_cooling_towers.sparql | **Cooling towers** button |
| 17_boilers.sparql | **Boilers** button |
| 18_central_plant.sparql | **Central plant** button |
| 19_hvac_equipment.sparql | **HVAC equipment** button |
| 20_meters.sparql | **Meters** button |
| 21_points.sparql | **Points** button |
| 22_class_summary.sparql | **Class summary** button |
| 23_orphan_external_references.sparql | Ref-schema hygiene: orphan `ref:BACnetReference` / `ref:TimeseriesReference` nodes not linked by `ref:hasExternalReference` |
