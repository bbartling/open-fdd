# Protocol connector runtime contract

`openfdd_connector_runtime` is the small shared runtime crate used by the
split edge connector services. It does not contain BACnet, Modbus, or Haystack
protocol clients.

## Identity

Phase 5A defines the versioned
`openfdd.connector.service-identity.v1` object for the split connector
processes. The identity includes a fixed profile (`bacnet_modbus` or
`haystack`), the build, process id, start time, and the selected edge recipe.
Phase 5B exposes it at the authenticated `GET /api/connector/hello` route and
adds the `openfdd-bacnet-modbus` and `openfdd-haystack` entrypoints. A cloud
hub cannot validate as an OT connector recipe.

## Authentication

The shared Phase 5A middleware defines the fail-closed API-key policy for a
management bind that is reachable beyond loopback. `/health` and
`/api/health` are the public readiness paths; the split routers do not mount a
root route. It uses a constant-time comparison for bearer API keys. Both
Phase 5B entrypoints enforce the policy during startup. Haystack additionally
requires a non-empty `OPENFDD_CONNECTOR_API_KEY` and an explicit HTTP(S)
endpoint even on a loopback bind.

The optional Compose Haystack profile may be resolved while its endpoint
variable is blank; `openfdd-haystack` rejects that configuration during
startup. A configured profile still requires an explicit outbound HTTP(S)
endpoint and the connector API key.

## Process surfaces

The BACnet/Modbus process starts BACnet UDP, configured polling, and the
read-only priority scanner. Its dedicated allowlist contains BACnet reads and
status, connector inventory/read, and scanner history; it excludes the legacy
root, compatibility aliases, writes, Who-Is/router discovery, point
discovery, weather controls, telemetry controls, and the arbitrary Modbus
read route. Its hello includes exactly the BACnet and Modbus compiled
protocols; Modbus readiness stays `not_configured` without a trusted typed
register inventory. The Haystack process starts only a TCP management
listener and outbound configured HTTP(S) Haystack operations. Its hello
includes only Haystack, and its health reports zero owned UDP sockets. The two
routers have negative tests for each other's prohibited paths, and the live
gate checks the actual processes and PIDs.

The split edge example is
[`docker/compose.edge.split.yml`](../../docker/compose.edge.split.yml).
The cloud `central` and `csv` recipes contain no OT image or process. The
legacy `openfdd-fieldbus` image and recipe remain available during migration.
The focused split gate starts both local entrypoints and checks their
process-owned descriptors under `/proc`: BACnet/Modbus owns UDP, while
Haystack owns no UDP socket. It builds and inspects the separate
`bacnet-modbus`, `haystack`, and `compatibility` Docker targets as well.

## Telemetry handoff

`TelemetrySinkConfig` recognizes `disabled`, `mqtts`, `local_ingest`, and
`dual`; the standalone Haystack process accepts only the authenticated
`local_fieldbus` setting and rejects new Haystack `mqtts` or `dual` activation.
It does not run automatic polling. An authenticated manual Haystack telemetry
route performs one bounded current read, converts it to the canonical envelope,
and reports the local receipt outcome. The fieldbus local sink requires an explicit central authority and
bearer token, joins the fixed `/api/ingest/local` path, disables redirects,
and enforces bounded connect/request timeouts and streaming request/response
bodies. A telemetry batch is bounded to 5,000 points and 1 MiB by default.
Central returns one typed receipt contract with exact scope/site/edge/message
correlation, payload-digest conflict detection, pending/committed/terminal/
retryable states, and persisted row counts. Terminal zero-eligible, rejected,
and conflict receipts are quarantined from the fieldbus retry spool; pending
and retryable receipts remain queued. These bounds protect the connector
process; they do not claim durable historian delivery until the receipt is
committed.

The Haystack read surface is separately bounded. A trusted startup catalog is
the only source of public keys and private upstream refs. Catalog pages are at
most 100 records; current reads are key based; history accepts at most 16
points, 5,000 samples, and a finite explicit UTC window of 24 hours. Typed
history samples carry genuine source `observed_at` timestamps. Central proxies
these operations only to the configured edge URL with its existing JWT,
tenant/building/edge scope checks, and bounded upstream body handling.

The existing `TelemetryEnvelope` remains the wire payload. Connector services
never open a DataFusion session or write Parquet directly.
