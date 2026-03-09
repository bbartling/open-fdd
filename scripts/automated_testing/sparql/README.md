# SPARQL queries for Open FDD data model

These `.sparql` files match the [SPARQL cookbook](../../../docs/modeling/sparql_cookbook.md). Run them via:

- **API:** `POST /data-model/sparql` with body `{"query": "<contents>"}` (or use **POST /data-model/sparql/upload** with the file).
- **Frontend:** Data Model page → either **Upload .sparql file** or paste query into the SPARQL textarea → Run SPARQL. You can also **View full data model (TTL)** to inspect the graph.

The script **sparql_crud_and_frontend_test.py** in the parent directory:

- Runs each query against the API, then (with `--frontend-parity`) tests the frontend in two ways: **upload each .sparql file** and **input each query in the form**, asserting both match.
- **Expected results:** When `config/data_model.ttl` exists and **rdflib** is installed, expected bindings are computed from that TTL (source of truth). Alternatively, place golden JSON in **expected/** (e.g. `expected/01_platform_config.json`). Use `--expected-from-ttl` to require TTL-based expected; use `--generate-expected` to write `expected/*.json` from the current API.

| File | Cookbook recipe |
|------|-----------------|
| 01_platform_config.sparql | Recipe 1: Platform config |
| 02_sites_labels.sparql | Recipe 2: Sites with labels |
| 02_site_counts.sparql | Recipe 2: Site aggregate counts |
| 03_equipment_labels_testbench.sparql | Recipe 3: Equipment for TestBenchSite |
| 03_point_labels_testbench.sparql | Recipe 3: Points for TestBenchSite |
| 04_bacnet_devices.sparql | Recipe 4: BACnet devices |
| 05_brick_rule_mapping.sparql | Recipe 5: Brick → rule input |
| 06_polling_points_brick_type.sparql | Polling points with Brick type + unit (no BACnet) |
| 07_count_triples.sparql | Recipe 7: Triple count |
| 08_bacnet_telemetry_points.sparql | BACnet telemetry points (polling=true + Brick + BACnet addressing, like scraper) |
