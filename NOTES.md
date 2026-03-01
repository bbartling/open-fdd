## Mega nuke prune

### 1) Stop everything

```bash
docker ps -aq | xargs -r docker stop
```

### 2) Remove all containers

```bash
docker ps -aq | xargs -r docker rm -f
```

### 3) Remove all images

```bash
docker images -aq | xargs -r docker rmi -f
```

### 4) Remove all volumes (THIS deletes DB data)

```bash
docker volume ls -q | xargs -r docker volume rm -f
```

### 5) Remove all custom networks

```bash
docker network ls --format '{{.Name}}' | grep -vE '^(bridge|host|none)$' | xargs -r docker network rm
```

### 6) Final system prune (build cache, leftovers)

```bash
docker system prune -a --volumes -f
docker builder prune -a -f
```


## Notes for FDD ideas for the future not to use a Bool flag for a fault based on a white paper

4) Store energy impact in a structured way

Add:

fault_energy_impact(fault_id, metric, low, typical, high, unit, notes, confidence)

Even if early values are coarse, it enables:

ranking + triage

“savings potential” dashboards

5) Test vectors + validation harness (this is huge)

In DB and/or RDF, store:

fault_test_vectors(fault_id, name, input_payload jsonb, expected_output jsonb)

Then build a small runner in your CI:

load vectors

run the fault rule engine

assert outputs

This is how you ensure “no rock left unturned” as your catalog grows.


## Verify weather scrape (Open-Meteo → timeseries_readings)

Weather is stored in `timeseries_readings` with points `temp_f`, `rh_pct`, `dewpoint_f`, etc. (see Grafana cookbook).

```bash
docker exec -it openfdd_timescale psql -U postgres -d openfdd -c \
"SELECT tr.ts, p.external_id, tr.value
 FROM timeseries_readings tr
 JOIN points p ON p.id = tr.point_id
 WHERE p.external_id IN ('temp_f','rh_pct','dewpoint_f','wind_mph','cloud_pct')
 ORDER BY tr.ts DESC
 LIMIT 50;"
```


## Check Faults Manually From Docker

### Check the FDD Engine Logs


```bash
docker exec -it openfdd_timescale psql -U postgres -d openfdd -c "SELECT run_ts, status, sites_processed, faults_written, error_message FROM fdd_run_log ORDER BY run_ts DESC LIMIT 10;"
```

```bash
$ docker exec -it openfdd_timescale psql -U postgres -d openfdd -c "SELECT fr.ts AS time, fd.name AS fault_name, fr.flag_value AS active FROM fault_results fr JOIN fault_definitions fd ON fd.fault_id = fr.fault_id WHERE fr.site_id = 'TestBenchSite' ORDER BY fr.ts DESC LIMIT 20;"
```

```bash
docker exec -it openfdd_timescale psql -U postgres -d openfdd -c "SELECT external_id AS raw_point_name, fdd_input AS mapped_role, brick_type, equipment_id FROM points WHERE fdd_input IS NOT NULL OR brick_type IS NOT NULL LIMIT 20;"
```


---

## Addon docs

The HA addon (stack/ha_addon/openfdd) has no DOCS.md. Addon install, API key, and smoke-test info are in the online docs (docs/integrations/home_assistant) and in bootstrap/help. High-level dev notes are in this file (NOTES.md) only.

- **Local addon image:** `./scripts/bootstrap.sh --ha-addon` builds `openfdd-addon:local`. To use it in HA: copy **stack/ha_addon** to your HA addons folder and set the addon image to `openfdd-addon:local` (see [Home Assistant integration — Addon image and local install](docs/integrations/home_assistant.md#addon-image-and-local-install-eg-same-linux-host)).
- **Replicating graph_and_crud_test from HA:** Use Developer Tools → Services and call the `openfdd.*` services (get_health, list_sites, run_sparql, etc.); see the same doc section “Replicating the CRUD/graph test from Home Assistant”.


---

## PyPI: integration-helpers-only package (architecture)

**Recommendation:** Use PyPI only for a small **integration helpers** package. The full platform stays “run from repo / Docker”; no need to publish the whole open-fdd to PyPI.

### What it is

- A **thin client library** that third parties can `pip install` to talk to the Open-FDD API: HTTP client (sync/async), optional WebSocket helper for `/ws/events`, and optional Pydantic models for request/response shapes.
- **Consumers:** HA integration (could depend on it instead of bundling api_client.py), Node-RED nodes, cloud/MSI scripts, or any integrator that wants “Open-FDD API client” without pulling in the full stack (FastAPI, DB, rdflib, etc.).

### What it would entail

1. **Package name**  
   Use a **new** name on PyPI so we don’t overwrite legacy `open-fdd`, e.g. **`openfdd-client`** or **`open-fdd-client`**. (Legacy `open-fdd` stays as the old v1 thing or can be deprecated with a readme pointing to the repo.)

2. **Contents**
   - **HTTP client:** Base URL + API key; methods for the main API surface (e.g. `get_capabilities()`, `get_faults_active()`, `get_config` / `put_config`, sites/equipment/points CRUD, data-model export/import, BACnet proxy, download, run_fdd). Mirror the current `stack/ha_integration/.../api_client.py` surface so HA could optionally depend on this package instead of shipping its own client.
   - **Optional:** Small Pydantic models for request/response DTOs (e.g. CapabilityResponse, FaultActiveItem) so integrators get types and validation.
   - **Optional:** WebSocket helper for connecting to `/ws/events?token=...`, subscribing to topics, and parsing event payloads.
   - **Dependencies:** Minimal — e.g. `httpx` (or `aiohttp`) and `pydantic`. No FastAPI, no DB, no rdflib.

3. **Where it lives**
   - **Option A:** Separate repo (e.g. `open-fdd-client` or `openfdd-integration`) with its own pyproject.toml, versioning, and CI to publish to PyPI. Main repo’s HA integration and Node-RED nodes could depend on it.
   - **Option B:** Subfolder in this repo (e.g. **`integration_client/`** or **`packages/openfdd_client/`**) with its own pyproject.toml; CI in this repo builds and publishes that package to PyPI under the chosen name. Keeps client and API in one place and lets you keep client in sync with API changes.

4. **Versioning**
   - Track the Open-FDD API version (e.g. match major.minor with main repo’s pyproject.toml) so “openfdd-client 2.0.x” implies “works with Open-FDD API 2.0.x”. Bump when the API surface or semantics change.

5. **Steps to make it**
   - Create the package (new name, pyproject.toml, minimal deps).
   - Move or copy the current HA `api_client` logic into the package (sync + async wrappers around httpx/aiohttp).
   - Optionally add Pydantic models for a few key request/response types.
   - Add optional WebSocket helper if useful.
   - Add README: “pip install openfdd-client”, “works with Open-FDD API 2.x”, link to main docs and API base URL.
   - Publish to PyPI (manual or CI). Then HA integration (and/or Node-RED) can depend on `openfdd-client` instead of bundling their own client.

6. **What we do *not* put on PyPI**
   - The full **open-fdd** platform (API, DB, rules engine, FDD loop). That stays “clone repo + Docker” or “pip install -e .” from repo. So no need to publish the monorepo as one big PyPI package for the server.

Summary: PyPI = one small **integration-helpers** package (client + optional models + optional WS). Everything else stays repo/Docker. That keeps PyPI simple and gives integrators a single, versioned dependency.