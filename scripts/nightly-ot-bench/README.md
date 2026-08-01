# Nightly OT LAN bench harness (post–Phase-2)

Expert-tester scripts for **immutable GHCR tip** images on the BACnet OT LAN,
with the **React** product UI (`compose.react.yml` + fieldbus overlay).

Source tree is for compose/config/analysis only — **do not build Rust runtime
images from local src**. Phase `00` pulls `sha-<7>`, asserts digests match
`:nightly`, and compose-builds `openfdd-web` only when GHCR has no web image.

## Topology

| Service | Image / source | Port |
|---------|----------------|------|
| mqtt | `openfdd-mqtt:sha-*` | 8883 |
| central | `openfdd-central:sha-*` (`OPENFDD_REACT_UI=1`) | 8080 |
| web | `openfdd-web` (GHCR when published, else `frontend/web` build) | 3000 |
| fieldbus | `openfdd-fieldbus:sha-*` (host net) | 8081 |
| mcp | `openfdd-mcp:sha-*` (gate 13) | — |

Recipe helper: `./scripts/openfdd_stack_up.sh react-ot`

## Lab inventory (context)

| Instance | Role | Notes |
|----------|------|--------|
| **5007** | `BENS-BENCHTEST-BOX` | Routed MS/TP via `192.168.204.200`, network `2000`, MAC `7` |
| **3456789** | BensFakeAhu | BIP — AI:2 SA-T |
| **3456790** | Zone1VAV | BIP — AI:1 ZoneTemp |
| **599999** | Hosted OpenFDD | Fieldbus server on UDP `47808` @ OT NIC |

OT NIC on this host: `enp3s0` → `192.168.204.55/24`.

**Arch note:** GHCR stack nightlies are **`linux/amd64` only**.

Put real IPs / keys in **`bench.env.local`** and
`docker/compose.react.fieldbus.local.yml` (both gitignored).

## Playbook

```bash
cd ~/open-fdd
git pull --ff-only origin master

cp scripts/nightly-ot-bench/bench.env.example scripts/nightly-ot-bench/bench.env.local
# edit OT IPs, API key, SITE/EDGE, optional OPENFDD_ADMIN_PASSWORD

cp docker/compose.react.fieldbus.local.example.yml docker/compose.react.fieldbus.local.yml
# edit OT bind + API key

# Seed field devices (local overlay; not committed)
# cp scripts/nightly-ot-bench/field_devices.bench.example.toml config/fieldbus/field_devices.toml

./scripts/nightly-ot-bench/run_all.sh
```

Individual phases:

```bash
./scripts/nightly-ot-bench/00_pull_ghcr_up.sh
./scripts/nightly-ot-bench/01_health_gates.sh
./scripts/nightly-ot-bench/02_bacnet_ot.sh
./scripts/nightly-ot-bench/10_react_spa.sh
```

Optional:

```bash
BENCH_ALLOW_WRITES=1 ./scripts/nightly-ot-bench/09_rest_ot.sh   # REST write clamp
RUN_CLOUD_SIM=1 ./scripts/nightly-ot-bench/run_all.sh
SKIP_PULL=1 ./scripts/nightly-ot-bench/run_all.sh               # reuse running stack
```

## Success definition

**PASS** only if all are true:

1. Tip `sha-*` digests match `:nightly` for central/fieldbus/mqtt/mcp
2. react-ot healthy: fieldbus + mqtt + **central** + **React SPA** (`/api/ui/generation` → react)
3. At least one LAN BACnet device discovered **and** poll returns live values
4. Device **5007** read/poll of AI:1173 succeeds
5. Central ingest/Feather shows **new** telemetry when MQTT path is live
6. React SPA routes + honesty/MCP gates pass

**FAIL with evidence** if any gate fails — do not weaken asserts.

Default write policy is **read/poll/discover**. Active REST write clamps require
`BENCH_ALLOW_WRITES=1`.

## Related

- `scripts/openfdd_stack_up.sh react-ot` / `openfdd_stack_pull.sh`
- `openfdd_agent_spec/CONTAINER_AGENT.md` — nightly → immutable pin protocol
- `scripts/fieldbus/smoke_test.sh` — deep BACnet matrix
- `scripts/openfdd_auth_smoke.sh` — JWT login vs central
