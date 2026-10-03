# ADR: Open-FDD protocol connector process split

Status: Phase 5C2 bounded Haystack/catalog/receipt hardening (partial, draft)

## Decision

Phase 5A reserves separate edge process profiles for the two protocol families:

| Process profile | Owns | Must not own |
| --- | --- | --- |
| `openfdd-bacnet-modbus` | BACnet/IP and routed BACnet UDP, configured Modbus/TCP, polling, and the read-only priority scanner | Haystack HTTP credentials or Haystack routes |
| `openfdd-haystack` | Outbound authenticated Haystack HTTP (`about`, catalog/read, and later bounded `hisRead`) | BACnet UDP sockets, BACnet discovery, or arbitrary Modbus connections |

The Phase 5B implementation ships separate Rust entrypoints and a split edge
Compose example. `openfdd-bacnet-modbus` starts the hosted BACnet server,
BACnet client, poll engine, and priority scanner. Its dedicated HTTP allowlist
contains only BACnet reads/status, connector inventory/read, and scanner
history routes. Modbus remains closed until a trusted register inventory
contract exists; it is not an arbitrary host/port read route. The process does
not construct `HaystackService` and its router has no Haystack paths.
`openfdd-haystack` constructs only the outbound Haystack client and a TCP
management listener. It never starts a BACnet server/client, binds UDP, or
mounts BACnet/Modbus routes. A deployment recipe selects one profile; a
runtime mode flag cannot turn one process into the other. `openfdd-fieldbus`
remains a deprecated compatibility image while deployments migrate to the
split images.

Both profiles use the shared `openfdd_connector_runtime` crate for:

- versioned service identity and recipe vocabulary;
- fail-closed management API-key middleware;
- bounded telemetry batches and sink status.

The BACnet/Modbus connector process may forward telemetry only over the
authenticated fixed local ingest path for the Phase 5C Haystack slice. The
standalone Haystack process has no automatic polling producer; its
`local_fieldbus` setting is a startup policy and its process surface includes
the typed read API plus an explicitly triggered current-read to local-ingest
route. Only
`openfdd-central` validates the ingest envelope and writes canonical
Parquet/DataFusion historian state. The local path returns a typed receipt
with exact scope/site/edge/message correlation, persisted envelope digest,
pending/committed/terminal/retryable/conflict outcomes, and no second database
or direct Parquet writer. Terminal zero-eligible, rejected, and conflict
receipts are quarantined from the fieldbus retry spool; pending and retryable
receipts remain queued.

## Safety boundaries

- Cloud hub recipes never start an OT connector process.
- The Haystack process never binds UDP. Its only remote protocol is outbound
  HTTP(S) to a configured, trusted Haystack endpoint.
- The split BACnet process does not expose the legacy root, compatibility
  aliases, writes, Who-Is/router discovery, point discovery, weather controls,
  or telemetry suspend/resume routes. The legacy `openfdd-fieldbus` process
  retains those historical routes during migration.
- Modbus is not advertised as ready from a container name alone. It requires a
  later trusted register catalog and bounded typed read contract.
- Public health is lean. The split entrypoints expose identity and health
  routes through the shared fail-closed API-key middleware; BACnet/Modbus
  exposes only its protocol routes and Haystack exposes only its Haystack
  routes. Haystack does not claim automatic telemetry delivery from the read
  process; an explicit manual request reports the authenticated local receipt
  outcome.
- No connector action writes a BAS value. BACnet WriteProperty and release
  remain outside this process-split phase.
- Haystack callers address only keys from the startup trusted catalog. URL,
  Zinc filter, upstream ref, credential, and navigation path inputs are not
  part of the public contract. Catalog revision is immutable for the process
  lifetime; current and finite history reads validate typed values, units,
  quality, and source timestamps.
- Basic and SCRAM transport require explicit credentials, fixed operation paths,
  TLS verification by default, redirects disabled, bounded connect/request
  timeouts, and streaming body limits. An unprobed or incomplete capability
  remains `checking`, unavailable, or auth-failed as observed; configuration
  alone never claims durable delivery.

## Migration

Phase 5A defines the shared vocabulary. Phase 5B adds the two isolated binary
entrypoints, an explicit split route allowlist, profile-specific settings,
separate Docker targets, a split edge recipe, and live cloud/process gates.
The split hello identities are profile-bound and Modbus remains
`not_configured` until a trusted register inventory contract exists. Phase 5C1
adds the bounded Haystack catalog/current-read/history contract, authenticated
Central proxy, and receipt-backed local delivery evidence. Image publication,
authenticated Haystack application qualification, and OT bench qualification
remain open; live authenticated Haystack remains Soft-OPEN and the legacy
image is kept until split recipes are qualified on the bench. Remaining Phase
5C delivery work must preserve these bounds and add evidence before the
milestone can move beyond PARTIAL.
