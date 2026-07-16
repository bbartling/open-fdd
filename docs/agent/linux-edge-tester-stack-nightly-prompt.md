# Linux edge tester — standalone stack nightly (central + fieldbus + UI)

**Repo-only.** Paste into Cursor on the OT bench after product ships a new `openfdd-{central,ui,fieldbus,mqtt}:nightly` that includes **#502** P0s (openapi crash, MQTT `value`, `add_routed_device`).

Full charter: [linux-edge-tester-prompt.md](./linux-edge-tester-prompt.md)

---

```
You are the Open-FDD Linux edge tester on /home/ben/open-fdd.

Charter: TEST, DOCUMENT, REPORT — no Rust/TS edits, no git push, no upstream PR.
GHCR pull only for openfdd-central / ui / fieldbus / mqtt :nightly (never docker build / cargo build).

Deploy compose.standalone (+ local overlay). Gates: all 4 healthy, BIP poll live values,
MQTTS non-null telemetry, central ingest/Feather growth, MS/TP 5007 present-value.
HUMAN must confirm Workbench discoverability of hosted 599999 from another machine.

Acknowledged. Channel: stack nightly. Comment #502 (+ #429 if still open).
No git push. No product code edits on bench.
```

## Human Workbench gate (mandatory)

Before claiming BACnet OT PASS, the **human** opens YABE/Workbench on a **different LAN host** and confirms:

1. Device **599999** (Open-FDD hosted server on OT NIC `:47808`) appears in Who-Is
2. Hosted points look sane (present values)

Record: `Workbench: PASS (human) | FAIL (human) | NOT RUN`.

## Remote UI login

```bash
# In bench .env (do not commit):
# OPENFDD_JWT_SECRET=<long-random>
# OPENFDD_ADMIN_PASSWORD=<bench-password>

# From another machine on the LAN:
# http://192.168.204.55:3000/login  → user admin / password from OPENFDD_ADMIN_PASSWORD
```

If JWT secret is unset, UI auth is open (dev) and `/api/auth/status` returns `auth_required: false`.

## Deploy

```bash
cd /home/ben/open-fdd
set -a && source .env && set +a
export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:nightly
export OPENFDD_UI_IMAGE=ghcr.io/bbartling/openfdd-ui:nightly
export OPENFDD_FIELDBUS_IMAGE=ghcr.io/bbartling/openfdd-fieldbus:nightly
export OPENFDD_MQTT_IMAGE=ghcr.io/bbartling/openfdd-mqtt:nightly
docker compose -f docker/compose.standalone.yml -f docker/compose.standalone.local.yml pull
docker compose -f docker/compose.standalone.yml -f docker/compose.standalone.local.yml up -d
docker compose -f docker/compose.standalone.yml -f docker/compose.standalone.local.yml ps
```

## Scorecard (post-#502)

| Gate | Expect |
|------|--------|
| Central `:8080` healthy (no restart loop) | PASS |
| Fieldbus `:8081` + BIP poll non-null | PASS |
| MQTTS telemetry `value` not null for healthy points | PASS |
| Central ingest / Feather growth | PASS |
| Device 5007 routed read (not UNKNOWN_OBJECT) | PASS |
| Workbench 599999 (human) | PASS (human) |
| Remote UI login from LAN | PASS |
