# Simulation engine adapters — EnergyPlus and optional eQUEST

## Boundary

Open-FDD central remains Rust. Building simulation engines are external tools
invoked by separately operated workers. A worker is not part of the synchronous
web request path and receives only a validated, immutable run package.

```text
React -> Rust central creates simulation run
             |
             +-> signed run manifest + input artifact IDs
             |
       external worker claims job
             +-> EnergyPlus container by digest
             or
             +-> approved eQUEST/DOE-2 Windows worker by exact version/license
             |
       output artifacts + hashes + logs + result manifest
             |
Rust central validates/attaches -> React/twin/model pipeline
```

The worker adapter may be written in Rust or a constrained platform-native
launcher. Production Open-FDD never requires a Python service. The simulation
binary itself is not “rewritten in Rust.”

## Common worker protocol

### Claim

A worker authenticates with a scoped service identity and claims a queued run
matching its engine, platform, version, and resource capability. Claims have a
lease and heartbeat; expired leases return safely to a retry/review state.

### Input manifest

`openfdd.simulation_run_request.v1` includes:

- run/job/twin version IDs;
- engine family and exact allowed version/digest;
- immutable input artifact IDs and SHA-256 hashes;
- weather, schedules, scenario patch set, output-variable request;
- CPU/memory/wall-time/output limits;
- deterministic seed where applicable;
- network policy (normally none);
- expected output schema;
- license/worker pool requirements;
- idempotency key and attempt number.

The worker stages inputs into a fresh run directory. It does not receive the
whole Open-FDD workspace or a Docker socket from central.

### Result manifest

`openfdd.simulation_run_result.v1` includes:

- status and structured failure class;
- engine/version/image digest/host architecture;
- input and patch hashes;
- start/end/elapsed/resource usage;
- exit code and bounded sanitized logs;
- output artifact file list, MIME, bytes, hashes;
- parsed summary metrics with units and provenance;
- warnings/severe/fatal counts;
- adapter version and source commit.

Central verifies the result and artifact hashes before attachment. Failed runs
remain evidence; retry creates another attempt rather than overwriting history.

## EnergyPlus adapter

- Pin an approved EnergyPlus image by digest.
- Run non-root with read-only root filesystem, isolated writable run volume,
  dropped capabilities, no host Docker socket, bounded resources, and normally
  no network.
- Validate IDF/epJSON and EPW size/type/version before execution.
- Keep patch operations typed and allowlisted; never execute arbitrary text as
  a shell command.
- Capture `.err`, SQL/CSV outputs, version info, and requested output variables.
- Parse generic production output transformations in Rust where practical.
  Offline Python may prepare farms or oracle fixtures but is not needed by the
  production worker/control plane.

## eQUEST/DOE-2 adapter

eQUEST is optional and requires a separate product/license/platform decision.
Treat it as a Windows worker pool, not as a container assumption.

- Record exact eQUEST/DOE-2 version and licensing/distribution constraints.
- Run under a dedicated low-privilege service account on an isolated Windows
  host/VM with a clean per-run directory.
- Use a constrained adapter to stage approved `.inp`/weather artifacts and
  collect `.sim`/reports; do not use unrestricted desktop automation from
  central.
- Keep UI dialogs and interactive failures out of the worker contract; detect
  and time out hung processes.
- Define typed scenario patches and result extractors with golden fixtures.
- Do not redistribute proprietary binaries in Open-FDD images or repositories.
- If unattended execution/licensing cannot be qualified, support eQUEST as an
  export/import engineering handoff rather than a production worker.

## Engine-neutral twin workflow

React uses engine-neutral concepts—inputs, run, calibration metrics, scenario,
artifacts, provenance—while showing the selected engine and limitations.
Engine-specific settings appear only in a typed advanced section. Model/twin
versions record their engine lineage.

EnergyPlus and eQUEST results are not assumed numerically interchangeable. A
cross-engine comparison is a separate engineering study with explicit weather,
schedule, system, and reporting-basis alignment.

## Acceptance

- central never launches an engine or mounts a worker control socket;
- worker cannot escape the staged run directory or access unrelated jobs;
- version/digest/license and every input/output hash are recorded;
- timeout/crash/retry/duplicate claim/expired lease are tested;
- output parsing has golden and malformed fixtures;
- React clearly displays engine, version, source, run status, warnings, and
  evidence links;
- an unavailable engine degrades to export/import or a clear blocked state, not
  fabricated results.

