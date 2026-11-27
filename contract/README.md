# Open-FDD UI API contract

The REST contract between the Open-FDD web UI and any host backend, a reference mock and a contract test suite.

| Path | What |
|---|---|
| [`../openapi/open-fdd-ui-api.yaml`](../openapi/open-fdd-ui-api.yaml) | OpenAPI 3.1 contract. `info.version` is the contract's own semver, independent of the app version. |
| `mock/server.mjs` | Reference backend, Node 22 stdlib only, synthetic in-memory fixtures (`mock/fixtures.mjs`). |
| `test/run.mjs` | Contract suite any backend can run. |
| `test/selftest.mjs` | Runs the suite against the mock in three host profiles (CI). |

## Run the mock

```bash
node contract/mock/server.mjs                 # http://127.0.0.1:8790, auth on, writes off
node contract/mock/server.mjs --writes        # enable PUT /api/rules/{rule_id}/confirm_min (or OFDD_MOCK_WRITES=1)
node contract/mock/server.mjs --no-auth       # host authenticates outside the contract; /api/auth/* answer 404
```

Options: `--port N` (0 = any free port), `--host H` (default `127.0.0.1`). State is in memory and resets on exit.

The refresh cookie is `Secure`, so browsers keep it only over HTTPS or on `localhost`. On plain `http://<lan-ip>`
login works but refresh does not: put a TLS front door (for example Caddy) in front, or use `localhost`.

Fixture data: one site, two AHUs, three VAVs, three days of 5-minute SI samples from 2026-01-05T00:00Z, one stale
point, four rules, and daily results with `FAULT`, `PASS`, `METRIC` and `NOT_ASSESSED` rows. Role names, units and
value types come from [`../roles/openfdd-roles.json`](../roles/openfdd-roles.json); rule inputs and confirmation
defaults come from the shipped rule catalog (`nf-app/static/fdd-catalog.json`) through the roles file's `legacy_keys`.

Fixture users (dev-only, stored as scrypt hashes in `mock/fixtures.mjs`):

| User | Password | Role |
|---|---|---|
| `viewer` | `viewer-demo` | viewer |
| `operator` | `operator-demo` | operator |
| `admin` | `admin-demo` | admin |

## Test a backend

```bash
cd contract && npm ci          # dev dependencies: yaml, ajv (pinned)
node test/run.mjs --base http://host:port --viewer user:pass --operator user:pass
npm test                       # the suite against the mock, all three profiles
node test/run.mjs --base http://host:port --manifest path/to/rules-manifest.json   # also check a rules bundle
```

`--roles PATH` overrides the vocabulary file (default `roles/openfdd-roles.json` of this repo).

Credentials may also come from `OFDD_CONTRACT_VIEWER` and `OFDD_CONTRACT_OPERATOR` (`user:pass`); the defaults are
the mock's users. With `rules_write` on, the suite changes one rule's `confirm_min` and restores it.

What the suite checks:

| Area | Checks |
|---|---|
| Schema | Every JSON response against its operation and status in the OpenAPI file; every error body against `Error`. |
| Meta | Contract major version equals the spec's; capability flags present. |
| Auth | 401 and `WWW-Authenticate` without or with a bad token; `invalid_credentials`; refresh token only in an `HttpOnly; Secure; SameSite=Strict; Path=/api/auth` cookie, never in the body; refresh rotates; reuse of a rotated token revokes the login's newest token; logout clears and revokes; `no-store`. With `auth` off, `/api/auth/*` answer 404. |
| Writes | 401 without a token; 403 `capability_disabled` when `rules_write` is off; 403 `forbidden` for a viewer; 404, 409 `not_tunable`, 400 on bad values; round trip. |
| Vocabulary | `Unit` equals the roles file's QUDT local names (`DEG_C`, `PERCENT`, ...) plus `HR` and null, same spelling, and its table matches each unit's Haystack display symbol; every role the spec names and every role the host returns (points, rule inputs) is a roles-file role with its unit, `unit_display` and value type; with `--manifest`, every rule input of a rules bundle manifest too. |
| Data | SI units only (`Unit`), freshness equals the last sample, half-open `[from, to)`, ascending samples, result status semantics and `fault_pct` arithmetic, filters, pagination and bad `limit` / `cursor`; 405 with `Allow`. |

## Versioning

A minor contract version only adds optional fields, endpoints or capability flags; a breaking change bumps the
major version. The suite accepts any host whose major version equals the spec's.
