# Agent prompt: Open-FDD bench — Haystack driver + all drivers + MCP context

Paste this entire document into a **WSL Cursor agent** session working on **Open-FDD 3.2.x** at `/home/ben/src/open-fdd` (legacy path `/home/ben/open-fdd` may symlink here). The agent must **implement/patch**, **run validation**, and **document** — not just advise.

External orchestrators (Codex, cloud agents) should follow [openfdd-agent-architecture.md](openfdd-agent-architecture.md); **this doc is for the on-bench WSL agent** with LAN access to OT devices.

---

## Mission

**Minimum success (this round):** Haystack protocol driver returns **live sensor readings** from Niagara nHaystack on the bench, validated alongside BACnet, Modbus, and JSON API.

**Stretch (same branch/session if time):** Extend **`openfdd-mcp`** (`ghcr.io/bbartling/openfdd-mcp`) so Cursor MCP tools expose driver health, point reads, and bench topology — see [openfdd-mcp-tool-contract.md](openfdd-mcp-tool-contract.md).

**Do not regress** drivers that already PASS on this bench.

---

## Bench topology (fixed facts — do not guess)

| Item | Value |
|------|--------|
| Host NIC | `enp3s0` @ **192.168.204.55/24** |
| Edge image | `ghcr.io/bbartling/openfdd-edge-rust:3.2.3` (pull-only site; patch source in `bbartling/open-fdd`) |
| Bridge API | `http://127.0.0.1:8080` |
| Commission API (BACnet OT) | `http://127.0.0.1:9091` (host-network; use for Who-Is / field reads) |
| BACnet field device | **5007** @ **192.168.204.200** (MSTP net 2000 via Niagara router) |
| Modbus simulator | **192.168.204.14:1502** unit 1 |
| Niagara nHaystack | **https://192.168.204.11/haystack** (Niagara 4.15.3.28, nHaystack 3.3.0.0) |
| Haystack service user | `open_fdd` with **`HTTPBasicScheme`** in N4 Workbench (NOT DigestScheme, NOT Haystack SCRAM) |
| rusty-haystack fork | `/home/ben/rusty-haystack` — `AuthMode::Basic`, `ClientConfig`, `niagara-read` demo |

**Critical BACnet bench workaround (already applied — preserve):**

`workspace/bacnet/commissioning/commission.env` must keep:

```
OPENFDD_BACNET_SERVER_ENABLED=0
```

With `=1`, the local BACnet server owns UDP 47808 and **client Who-Is never sees device 5007**.

---

## Baseline: readings that MUST still work after your patches

Use these as **regression targets**. Re-run `./scripts/openfdd_drivers_validate.sh` and capture fresh readings.

### BACnet — device 5007 @ 192.168.204.200 (commission `:9091`)

| Sensor | Object | Expected ballpark |
|--------|--------|-------------------|
| OA-T | analog-input 1173 | ~72 °F |
| OA-H | analog-input 1168 | ~51 %RH |
| DUCT-T | analog-input 1192 | ~69 °F |
| ZN-T | analog-input 10014 | ~72 °F |

Commission read format: `bacnet:5007:analog-input:<instance>` via `/api/bacnet/read` on **commission**, not bridge.

### Modbus — RPi @ 192.168.204.14:1502

| Sensor | Register | Expected ballpark |
|--------|----------|-------------------|
| Temp °F | 40001 | ~74–76 °F |
| Temp °C | 40002 | ~23–25 °C |
| Setpoint °F | 40003 | ~72 °F |
| Humidity | 30003 | ~45 %RH |

### JSON API — health probes (configure in workspace, not repo defaults)

Add endpoints under `workspace/data/json_api/endpoints.json` (gitignored). Example probe IDs on this bench:

| Point ID | Expected |
|----------|----------|
| json-api-bench-health | HTTP 200 |
| httpbin-health | HTTP 200 |
| postbin-echo | HTTP 200 |

Production Rust **does not** ship fake httpbin/postman URLs — bench agents must configure workspace JSON only.

### Haystack — Niagara nHaystack (TARGET — currently SKIP/FAIL)

Proven **outside** Open-FDD with `niagara-read --auth basic`:

| Haystack point | Expected ballpark |
|----------------|-------------------|
| OA-H | ~51 %RH |
| OA-T | ~72 °F |
| DUCT-T | ~65–69 °F |
| DUCT-P | ~-0.14 in/wc |
| STAT ZN-T | ~73 °F |
| ACTUATOR-POS / ACTUATOR-0 | % |

Filter: `point and cur`. Path prefix: `@C.Drivers.BacnetNetwork.BENS-BENCHTEST-BOX.points.*`

---

## Haystack: what is broken today in Open-FDD

1. **`workspace/haystack/local.nhaystack.toml`** may point at **wrong host** (`192.168.204.200:80` — BASRT web UI, not nHaystack). Must be **`https://192.168.204.11/haystack`**.
2. **No credentials wired** — bridge `/api/haystack/status` shows `username: null`, `password_set: false`, `enabled: false`.
3. **`tls_verify = true`** — Niagara lab uses **self-signed HTTPS**; need `tls_verify = false` (equivalent to `curl -k`).
4. **Auth mode** — Niagara uses **`auth_mode = "basic"`** (HTTP Basic). **Do NOT use SCRAM** against nHaystack; SCRAM HELLO returns 401 HTML with no `WWW-Authenticate: SCRAM`.
5. **Validation profile** — ensure `[haystack] enabled = true` in operator `workspace/smoke-profiles/local/local_validation_profile.local.toml` (gitignored copy from `.example`).

### Haystack protocol vs SCRAM (agent must understand)

- **HTTP Basic (Niagara `HTTPBasicScheme`)**: `Authorization: Basic base64(user:pass)` on every request. **This is what works today.**
- **Haystack SCRAM**: `HELLO` → `SCRAM` → `BEARER` token. Works on **SkySpark** and **rusty-haystack server**, **not** on Niagara nHaystack 3.3.

Reference: `/home/ben/rusty-haystack/demo/niagara_sample/niagara-rusty-scrape` (`cargo run -p niagara-read -- --auth basic`).

---

## Required config patches (minimum)

### 1. `workspace/haystack/local.nhaystack.toml`

Copy from `workspace/haystack/local.nhaystack.example.toml`. Set (password via env/secret store — **never commit plaintext**):

```toml
[haystack]
id = "local-niagara-nhaystack"
name = "Local Niagara nHaystack"
enabled = true
base_url = "https://192.168.204.11/haystack"
source_id = "source:local-niagara-haystack"
site_id = "site:local"
auth_mode = "basic"
username_env = "OPENFDD_HAYSTACK_USER"
password_env = "OPENFDD_HAYSTACK_PASS"
poll_interval_seconds = 60
polling_enabled = true
model_import_enabled = true
timeout_seconds = 15
tls_verify = false
```

### 2. `workspace/data.env.local`

Ensure:

```
OPENFDD_HAYSTACK_ENABLED=1
OPENFDD_HAYSTACK_CONFIG=/var/openfdd/workspace/haystack/local.nhaystack.toml
OPENFDD_HAYSTACK_USER=open_fdd
OPENFDD_HAYSTACK_PASS=<from operator / Niagara Workbench — not in repo>
```

### 3. `workspace/smoke-profiles/local/local_validation_profile.local.toml`

```toml
[haystack]
enabled = true
base_url = "https://192.168.204.11/haystack"
username = "open_fdd"
source_id = "source:local-niagara-haystack"
poll_interval_seconds = 60
```

### 4. Rust edge driver (if config alone insufficient)

Haystack driver lives in **`open_fdd_edge_prototype`** / `openfdd-haystack-gateway` container. Ensure:

- HTTP client accepts **insecure TLS** when `tls_verify = false`
- Uses **HTTP Basic**, not SCRAM, when `auth_mode = "basic"`
- Poll `/read?filter=point and cur` or POST read with zinc — match `niagara-read`
- Maps Haystack ids to Open-FDD point model for parity with BACnet 5007

See `edge/src/drivers/haystack/client.rs` and [local_haystack_niagara.md](../development/local_haystack_niagara.md).

---

## Validation gates (run in order)

```bash
cd /home/ben/src/open-fdd

# 1. All drivers — target pass=4, fail=0 (haystack must PASS, not SKIP)
./scripts/openfdd_drivers_validate.sh

# 2. Edge stack health
./scripts/openfdd_rust_edge_validate.sh

# 3. Haystack-specific API (integrator token via auth.env.local)
source scripts/openfdd_auth_lib.sh
TOKEN=$(openfdd_auth_login_token http://127.0.0.1:8080 workspace/auth.env.local integrator)
curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/status | jq .
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/haystack/test -d '{}' | jq .

# 4. External sanity (optional)
cd /home/ben/rusty-haystack/demo/niagara_sample/niagara-rusty-scrape
source .env && cargo run -p niagara-read -- --auth basic --probe-scram
```

**Success criteria:**

- `./scripts/openfdd_drivers_validate.sh` → **`PASS haystack`**
- `/api/haystack/test` → `ok: true`, `enabled: true`
- Haystack poll returns **OA-T, OA-H, DUCT-T** within ~5 °F/% of BACnet 5007 reads
- BACnet, Modbus, JSON API remain **PASS**

Save artifacts under `workspace/logs/drivers_validate_*`.

---

## Known architecture gaps (do not “fix” by breaking commission)

| Gap | Workaround | Proper fix (separate issue) |
|-----|------------|----------------------------|
| Bridge BACnet Who-Is fails (`Cannot assign requested address`) | Use **commission :9091** for OT BACnet | Bridge must proxy BACnet to commission or host-network |
| `OPENFDD_BACNET_SERVER_ENABLED=1` breaks discovery | Keep `=0` on bench | Fix client/server UDP ownership in `bacnet_live.rs` |
| haystack-gateway healthcheck unhealthy | Functional gate is `/api/haystack/test` | Fix healthcheck port/path in compose |

---

## MCP server (`openfdd-mcp`) — design context

**Goal:** Cursor MCP tools so agents inspect/configure **all bench drivers** without guessing URLs.

Image: **`ghcr.io/bbartling/openfdd-mcp`** (separate container from edge). Stdio transport for Cursor; optional Docker sidecar profile `mcp-sidecar`.

Minimum tool surface — see [openfdd-mcp-tool-contract.md](openfdd-mcp-tool-contract.md) and `mcp/README.md`.

### Haystack-specific MCP knowledge (server instructions)

```
Niagara nHaystack:
  URL: https://192.168.204.11/haystack
  Auth: HTTP Basic (HTTPBasicScheme) — NOT SCRAM
  TLS: self-signed → tls_verify=false
  User: open_fdd
  SCRAM: will NOT work on nHaystack; use basic only

SkySpark / rusty-haystack-server:
  Auth: SCRAM (HELLO/SCRAM/BEARER)
```

### MCP env / secrets

- Read Niagara password from **`OPENFDD_HAYSTACK_PASS`** or Open-FDD secrets store — never log or commit
- Auth to bridge: integrator token from `workspace/auth.env.local` (`scripts/openfdd_auth_lib.sh`)

---

## Agent execution rules

1. **Run commands yourself** on WSL — this is a real bench, not a simulation.
2. **Do not commit** passwords, `.env`, or `bootstrap_credentials.once.txt`.
3. **Minimize scope** — fix Haystack + MCP scaffold; don’t refactor unrelated dashboard/RCx.
4. **Preserve** `OPENFDD_BACNET_SERVER_ENABLED=0` and commission-based BACnet reads.
5. **Document** changes in `workspace/logs/haystack_driver_round_<timestamp>/NOTES.md`.
6. If GHCR image lacks your Rust patch, document required image tag rebuild; patch source in repo anyway.
7. **Never hardcode** bench device IDs or IPs in production Rust/TS — workspace config only.

---

## Deliverables checklist

- [ ] `local.nhaystack.toml` corrected (IP, TLS, basic auth, enabled)
- [ ] Credentials wired via env/secrets (not git)
- [ ] `./scripts/openfdd_drivers_validate.sh` → PASS haystack + existing drivers
- [ ] Sample Haystack readings captured (OA-T, OA-H, DUCT-T) in NOTES
- [ ] Parity note: Haystack vs BACnet 5007 values within reasonable drift
- [ ] MCP: crate + GHCR image with tool list + bench context
- [ ] (Optional) Link to rusty-haystack PR `feat/niagara-nhaystack-basic-auth-demo` on `bbartling/rusty-haystack`

---

## External references

- [nHaystack Niagara Pi tutorial](https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_17/nhaystack-niagara-pi-tutorial)
- [rusty-haystack](https://github.com/jscott3201/rusty-haystack)
- Fork demo: `/home/ben/rusty-haystack/demo/niagara_sample/`
- Issue **#402** expert findings / MCP design notes
