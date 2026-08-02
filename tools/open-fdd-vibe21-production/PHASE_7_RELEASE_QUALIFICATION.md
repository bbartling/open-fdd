# Phase 7 — Turnkey release qualification and operations

## Objective

Qualify the combined analytics/FDD/digital-twin product for repeatable local or
edge deployment, upgrades, recovery, and honest support.

## P7-M0 — Release manifest and image set

- One signed release manifest ties Git commit, central/web/fieldbus/MQTT/MCP
  image digests, schema versions, SQL registry hash, React asset hash, model
  runtime version, and migration set.
- Publish SBOM, provenance, vulnerability results, supported architectures, and
  compatibility table.
- Never use `latest`/`nightly` as qualification evidence; record SHA digests.

## P7-M1 — Clean-host and upgrade matrix

Test supported Linux hosts/architectures:

- clean install with no Python;
- offline or controlled-network install where supported;
- fresh sample job through deliverable;
- previous qualified release upgrade with real workspace copy;
- interrupted migration recovery;
- rollback with schema/data compatibility;
- expired certificates/tokens and rotation;
- disk-full/low-memory/restart behavior.

## P7-M2 — Backup, restore, retention, and portability

- Document which state is authoritative and which is regenerable.
- Consistent backup while services run or a defined maintenance mode.
- Restore to a clean host and verify hashes, jobs, twins, active releases,
  reports, audit, and identity bindings.
- Test artifact retention and garbage collection with active references.
- Export a portable job/twin evidence package without credentials/local paths.

## P7-M3 — Security and privacy qualification

- Threat models for upload, archives, model artifacts, WebGL, browser bridge,
  MQTT, MCP, external workers, auth, and reports.
- Dependency/image/container/filesystem/secret scans.
- AuthN/AuthZ and cross-site isolation tests for every new object family.
- Rate/body/concurrency limits and denial-of-service probes.
- CSP/XSS/CSRF/CORS/clickjacking/token handling tests.
- Audit integrity and sensitive-log review.
- Published security response and model/Unity artifact revocation procedures.

## P7-M4 — Performance, reliability, and observability

Define and test budgets for:

- initial React and Unity load;
- CSV/Arrow import by dataset size;
- DataFusion FDD and analytics by rows/rules;
- inference p50/p95/p99 and concurrency;
- live observation latency/reconnect;
- report/artifact download;
- memory/disk growth and retention;
- 24-hour and multi-day soak.

Metrics/logs/traces use request/job/run IDs, redact secrets/private values, and
provide health/readiness for each service. Alerts include actionable recovery.

## P7-M5 — Support and release evidence

- Operator quickstart and architecture guide.
- Engineer workflow guide and source/provenance legend.
- Upgrade/rollback/backup/restore/runbook.
- Model retraining/publication/revocation runbook.
- Unity build import/activation/rollback runbook.
- Edge/MQTTS certificate and reconnect runbook.
- MCP safety and approval guide.
- Known limitations and non-claims.
- Reproducible qualification manifest with commands, logs, reports, screenshots,
  image hashes, fixture hashes, and approvers.

## Phase 7 exit gates

- All applicable tests in [TEST_RELEASE_AND_ACCEPTANCE.md](TEST_RELEASE_AND_ACCEPTANCE.md)
  pass on release artifacts.
- Clean-host, upgrade, backup/restore, rollback, and soak evidence is attached.
- No Python exists in a supported production runtime image or request path.
- Published images match compose and documentation.
- Critical/high security findings are resolved or explicitly release-blocking.
- Known limitations accurately describe model/FDD/Unity/live status.
- An independent verifier signs the release evidence manifest.

