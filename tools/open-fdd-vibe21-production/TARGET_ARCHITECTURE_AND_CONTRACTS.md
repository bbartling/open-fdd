# Target architecture and contract map

## Runtime topology

```text
Browser
  |
  +-- React SPA ------------------------------------------------------+
  |      | jobs, mapping, FDD, reports, twin studio, exact charts     |
  |      +-- /api/* ------------------------------------------------+ |
  |      +-- /twins/{twin_id}/viewer ------------------------------+| |
  |                                                               || |
  +-- Unity WebGL iframe or same-page host                         || |
         | bootstrap, scenario, telemetry, selection via postMessage|| |
         +-- same-origin /api/twins/* -----------------------------+| |
                                                                  || |
                    reverse proxy / Rust central <----------------++-+
                               |
        +----------------------+--------------------------+
        |                      |                          |
  job/artifact store      DataFusion/Arrow          Rust inference
        |                 SQL FDD/analytics          signed models
        |
  external digest-pinned workers
  EnergyPlus / Unity build import / report rendering where approved

Fieldbus/edge -> MQTTS -> central ingest -> quality-aware observation store
External AI agent -> stdio/HTTP MCP -> central capabilities and approval gates
```

The preferred deployment is same-origin. A standalone Nginx web image may
proxy `/api`, `/artifacts`, and `/twins`; alternatively central may embed the
immutable React distribution and Unity artifacts. Pick one supported default in
Phase 1 and test it. Do not maintain two unqualified “primary” topologies.

## Bounded contexts and owners

| Context | Owner | Must not own |
|---|---|---|
| Product navigation and interaction state | React | formulas, model authority, durable permissions |
| Engineering plots/tables | React with server datasets | hidden calculation variants |
| Auth, tenancy/site scope, jobs, artifacts | Rust central | browser-only authority |
| Deterministic FDD/analytics | DataFusion SQL + Rust registry/runner | pandas fallback |
| Online surrogate inference | Rust inference crate/service module | joblib/sklearn runtime |
| Offline model training | notebooks/training repository | production serving |
| EnergyPlus simulation | external digest-pinned worker | central process or browser |
| Unity scene/build | external Unity project/pipeline | canonical engineering data |
| Unity artifact validation/serving | Rust central/artifact store | Unity Editor execution |
| Agent operations | MCP facade over central | bypass of auth/approval/audit |
| Pandas rule oracle and spreadsheets | PyPI `open-fdd` | production web requests |

## Canonical identity graph

All APIs use opaque stable IDs and separate display names:

```text
organization_id
  +-- site_id
       +-- building_id
            +-- equipment_id
            |    +-- point_id
            +-- twin_id
                 +-- twin_version_id
                      +-- geometry_artifact_id
                      +-- unity_build_id
                      +-- model_release_id
                      +-- scenario_schema_id

job_id
  +-- dataset_id
  +-- mapping_revision_id
  +-- fdd_run_id
  +-- simulation_run_id
  +-- training_dataset_release_id
  +-- model_release_id
  +-- scenario_run_id
  +-- report_id / artifact_id
```

Vibe 21 names such as `geo_b100_dual_ahu_shape_ops11` become external aliases or
version labels; they are not substituted for Open-FDD IDs.

## Contract families

Every wire artifact carries:

- `schema_version` as a namespaced semantic identifier;
- `request_id` and, for durable work, `job_id`/`run_id`;
- stable entity IDs;
- unit metadata;
- source/provenance classification;
- created/effective timestamps;
- content hash for immutable artifacts;
- warnings and a machine-readable status.

### Twin manifest

Minimum `openfdd.twin_manifest.v1` fields:

```json
{
  "schema_version": "openfdd.twin_manifest.v1",
  "twin_id": "twin_...",
  "twin_version_id": "twinver_...",
  "site_id": "site_...",
  "building_id": "building_...",
  "display_name": "Building 100",
  "status": "CANDIDATE",
  "geometry": {
    "artifact_id": "artifact_...",
    "sha256": "...",
    "coordinate_system": "ENERGYPLUS_Z_UP_METERS",
    "binding_schema_version": "openfdd.unity_binding.v1"
  },
  "viewer": {
    "unity_build_id": "unitybuild_...",
    "bootstrap_url": "/api/twins/twin_.../bootstrap"
  },
  "scenario_schema_id": "scenario_schema_...",
  "model_release_ids": ["modelrel_..."],
  "provenance": {
    "source": "ENERGYPLUS_SIMULATED",
    "idf_sha256": "...",
    "weather_sha256": "..."
  }
}
```

### Observation envelope

CSV replay and live MQTTS data normalize to the same contract:

```json
{
  "schema_version": "openfdd.observation.v1",
  "site_id": "site_...",
  "building_id": "building_...",
  "equipment_id": "equip_...",
  "point_id": "point_...",
  "event_time": "2026-08-01T15:00:00Z",
  "ingest_time": "2026-08-01T15:00:01Z",
  "sequence": 12345,
  "value": 34.2,
  "unit": "degC",
  "quality": "GOOD",
  "source": "BACNET_MQTT",
  "replay_id": null
}
```

Quality includes at least `GOOD`, `UNCERTAIN`, `BAD`, `STALE`, `MISSING`, and
`SIMULATED`. FDD, inference, React, and Unity must preserve it.

### Scenario request/result

Vibe 21 action fields become a versioned, validated scenario schema rather than
a free-form dictionary. A request references immutable releases:

```json
{
  "schema_version": "openfdd.twin_scenario_request.v1",
  "job_id": "job_...",
  "twin_version_id": "twinver_...",
  "model_release_id": "modelrel_...",
  "scenario_schema_id": "scenario_schema_...",
  "weather_day_id": "weatherday_...",
  "strategy_id": "precool_shift",
  "hour_ending": 15,
  "actions": {
    "precool_delta_f": 2.0,
    "cooling_relax_delta_f": 5.0,
    "heating_relax_delta_f": 2.5,
    "dat_delta_f": 5.0,
    "chw_availability": 1.0,
    "fan_availability": 1.0
  },
  "lookback": []
}
```

Response fields include `domain_status`, `feature_coverage`, per-target values
with units, uncertainty where supported, warnings, model/training provenance,
and latency. Invalid enum/range/relationship combinations return RFC 9457-style
field errors and never silently default.

### Model release

`openfdd.model_release.v1` records:

- portable artifact format and opset/runtime version;
- artifact SHA-256 and optional signature/SBOM;
- immutable feature order, types, units, normalization, categorical vocabulary;
- output order, units, constraints, and post-processing;
- training dataset hash and source commit;
- grouped split and leakage checks;
- global/per-target metrics and acceptance thresholds;
- training-domain bounds and domain classifier;
- approved status and approving identity;
- oracle conformance fixture hash;
- compatible scenario and twin schema versions.

### Unity build manifest

`openfdd.unity_webgl_build.v1` records Unity version, build target, compression,
fallback, entry point, required content types/headers, file list with hashes,
total/uncompressed size, browser compatibility, CSP needs, API bridge version,
smoke evidence, and rollback predecessor.

## React–Unity bridge

Use a versioned `postMessage` protocol with strict origin checks. Direct Unity
API calls may coexist, but React owns navigation and cross-panel selection.

Required messages:

- `viewer.ready` / `host.bootstrap`;
- `selection.changed` in both directions;
- `scenario.preview.requested` and `scenario.result.available`;
- `time.cursor.changed`;
- `visual.mode.changed`;
- `viewer.health` and `viewer.error`.

Every message contains `bridge_version`, `twin_id`, `correlation_id`, and a
validated payload. Never accept wildcard origins in production.

## Artifact layout

```text
workspace/jobs/{job_id}/
  manifests/job.json
  datasets/{dataset_id}/...
  mappings/{mapping_revision_id}.json
  fdd/{fdd_run_id}/...
  twins/{twin_version_id}/
    twin-manifest.json
    geometry/...
    scenarios/{scenario_run_id}/result.json
  simulations/{simulation_run_id}/...
  models/{model_release_id}/
    model.onnx
    model-release.json
    conformance.jsonl
  unity/{unity_build_id}/
    build-manifest.json
    webgl.zip
    extracted/...
  reports/{report_id}/...
```

Paths are implementation details; API clients use IDs and download URLs. All
archive extraction uses path traversal, symlink, file-count, expanded-size, and
MIME/content checks.

## API groups

The target central OpenAPI must cover:

- `/api/sites`, `/api/buildings`, `/api/equipment`, `/api/points`;
- `/api/jobs` and typed runs/artifacts;
- `/api/datasets`, mappings, replay, and observation quality;
- `/api/fdd`, `/api/analytics`, and plot datasets;
- `/api/twins`, versions, geometry, bindings, bootstrap;
- `/api/twins/{id}/scenarios` and scenario runs;
- `/api/models/releases` and qualification state;
- `/api/unity/builds` upload/import/validate/activate/rollback;
- `/api/reports` and downloads;
- `/api/capabilities` with versions and enabled operations.

MCP tools are derived from these authoritative operations; they do not invent a
parallel domain contract.

