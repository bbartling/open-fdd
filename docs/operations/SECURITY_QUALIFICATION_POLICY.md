# Security qualification policy

This policy defines acceptance for Open-FDD deployment and penetration-test evidence.
It is a target contract, not a declaration that all controls have been implemented or
that a deployment has passed Nessus. Track measured readiness in
[Nessus readiness](NESSUS_PASS_READINESS.md), [protocol connector runtime](protocol-connector-runtime.md)
and the release's candidate evidence. Report vulnerabilities privately under
[SECURITY.md](../../SECURITY.md).

## Deployment profiles

| Profile | Intended services | Network boundary |
| --- | --- | --- |
| OT local, BACnet/Modbus | HTTPS entry, React web, central, selected BACnet/Modbus connector | Approved LAN/VPN clients; private API and authenticated management; BACnet only to approved OT peers |
| OT local, Haystack | HTTPS entry, React web, central, selected Haystack connector | Approved LAN/VPN clients; private API/management; configured outbound Haystack endpoint; no BACnet/Modbus process |
| Cloud MQTT hub | Web, central and MQTT broker | HTTPS web ingress, private central, explicit mTLS broker proxy or private tunnel; no OT connector image/process |
| Local development | Explicit loopback/disposable components | Development evidence only |

Use the same product images across environments. OT local ingestion does not require a
broker. MQTTS egress or an additional local broker is an explicit feature with its own
exposure and ACL requirements. Select one connector by default; a combined profile must
declare both. Existing compatibility recipes remain distinct until their replacements
are qualified. Haystack is currently manual collection/local ingest; automatic collection
and dual delivery require separate implementation and evidence.

Every deployment declares expected services, image digests/platforms, host versus
container interfaces, TCP/UDP ports, IPv4/IPv6, allowed client networks, egress destinations,
transport/authentication and denied paths. Observe resolved configuration, processes and
sockets, then verify allowed and denied paths from a second peer. A manifest describes
intent; it is not a scan. Cloud profiles must prove absence of OT images and processes.

## HTTPS, identities and runtime

Production UI/API access requires authenticated HTTPS even behind an OT firewall. Use
an operator-provided certificate or a managed local CA with deliberately distributed
public trust and protected persistent CA keys. Caddy's local CA does not automatically
establish trust on remote browsers or scanners. [Caddy HTTPS documentation](https://caddyserver.com/docs/automatic-https).

An explicitly selected self-signed lab certificate may serve a disposable build with
hostname validation and explicit trust. It cannot close production or Nessus certificate
acceptance. Never disable certificate validation to obtain a pass. Test wrong hostname,
untrusted/expired certificate, renewal and restart. HTTP may provide only a canonical
HTTPS redirect; it must never proxy login or authenticated API requests in plaintext.

Caddy owns local TLS; nginx serves the UI and same-origin API proxy. Keep direct central
and connector management private. Define trusted proxy sources before accepting forwarded
scheme/client/host values; test redirects and required headers on successful, denied and
error responses. Apply documented per-route body/time/rate limits compatible with CSV
imports and async jobs. Authenticate and authorize in central, independently of proxies.

Bootstrap fails closed for missing/default credentials and incompatible profile settings.
Use separate JWT, admin, connector and ingest identities; protect keys and generated kits.
Run containers with least privileges, no-new-privileges, minimal capabilities, explicit
writable mounts, resource/log limits and no Docker socket. Host-network BACnet does not
require privileged mode. Test host firewall rules along Docker's actual packet path.
[Docker firewall documentation](https://docs.docker.com/engine/network/packet-filtering-firewalls/).

## Authorized test modes

Topology and test permissions are separate settings. `live_readonly` runs bounded approved
reads; `isolated_full` allows fixture-owned writes on a disposable application with no
route or command connection to live OT. Negative write tests belong in isolation because
a broken authorization control can let the write succeed. GET routes that trigger OT
work are not automatically harmless reads. Never perform BAS writes during qualification.

The Python default budget is one concurrent request, one request/second, 200 requests,
10 seconds/request, 300 seconds/run, a 1 MiB response cap and ten requests reserved for
cleanup. Larger isolated matrices require explicit finite budgets. Count authentication,
controls, retries and cleanup. Apply one monotonic deadline through DNS/connect/read and
subprocess execution. Stop new work after repeated errors, throttling, scope drift or
failed positive controls; record incomplete checks as BLOCKED or ERROR.

Use exact origin allowlists, TLS verification, disabled automatic redirects/proxies and
credentials from protected environment/file references. Do not follow external redirects
with credentials. SSRF tests use isolated canary endpoints. Active/fuzz/load tests run
only on isolated equivalents. Railway testing targets the operator's approved application
origins and broker endpoints; it does not scan shared provider networks or claim host-OS
assessment of provider-managed infrastructure.

## Coverage and scanner evidence

Maintain a versioned method/route/role/object policy inventory. Required controls include
authentication/JWT/session behavior; tenant/role isolation; datasets, mapping, jobs,
analytics, cache and exports; uploads/archive/parser limits; SQL/RDF/path traversal and
SSRF; CORS/CSRF/browser cache/security headers; connector management/local-ingest identity;
and WebSockets if present. Missing credentials are BLOCKED. Feature-absent N/A requires
evidence. Pair foreign denial with authenticated own-object success in both directions.

MQTT profiles require mTLS identity and real generated ACL evidence: permitted publication
and subscription, forbidden foreign/wildcard/command topics, healthy observers, payload
identity, retained/replay behavior, certificate rotation/revocation and key permissions.
Transport continuity alone cannot establish authorization. Outbound MQTT can carry
subscribed commands; it is not a one-way boundary.

Use the existing [Python harness](../../scripts/security/README.md) and ZAP automation.
ZAP qualification needs a pinned scanner, exact scope, verified authentication during
scanner traffic, route/method coverage, completed jobs, finite limits and cleanup.
Successful login outside ZAP or an auth URL in an alert does not establish scan coverage.
Passive, active, browser, synthetic and real-app evidence remain distinct.
[ZAP authentication documentation](https://www.zaproxy.org/docs/desktop/addons/automation-framework/authentication/).

Test evaluators with healthy and deliberately broken fixtures. Always-401, HTML/empty
200, foreign leakage, skipped suites, false auth coverage, wrong origins, malformed,
stale or empty reports, missing controls and cleanup failures must prevent qualification.
Real Rust middleware/storage and browser tests complement fake-server detector tests.

## Nessus and release acceptance

Assess an isolated representative Linux installation from an approved peer with a
licensed scanner and current feed. Keep external exposure, credentialed host checks,
container/runtime configuration and final-image dependency/SBOM assessments as separate
evidence. Preserve scanner policy/version/feed, target aliases, image/config fingerprints,
completed scope, successful per-host credentialed checks, timestamps and private report
hashes. Verify the scanner did not stop after identifying OT services.
[Tenable discovery settings](https://docs.tenable.com/nessus/Content/DiscoverySettings.htm).

Default release policy requires zero unresolved Critical/High findings. Every Medium
requires exact finding/component/port scope, owner, rationale, expiry and retest; a blanket
allow flag is insufficient. The report importer rejects incomplete, foreign, stale and
unassessed targets. Missing licensed evidence stays BLOCKED; Python/ZAP/image results
cannot substitute for Nessus. Readiness engineering and importer tests need no license.

Evidence uses versioned JSON with run, candidate, configuration, fixture and policy
identity; required/executed checks; positive controls; budgets; cleanup and artifact hashes.
PASS, FAIL, ERROR, BLOCKED, SKIPPED and evidenced NOT_APPLICABLE are distinct. Derive
verdicts from required controls, never trust a claimed qualification boolean. Reject
unknown/duplicate IDs, contradictory counts, stale evidence and candidate drift.

Keep raw findings, scan XML, authentication material and private inventories in protected
storage. Public CI artifacts contain bounded allowlisted summaries without credentials
or raw HTTP bodies. Candidate/config, auth, proxy, broker, image, host or policy changes
invalidate affected evidence. Record limitations honestly: no universal security,
Nessus certification or superiority-to-human claim follows from passing automated tests.
