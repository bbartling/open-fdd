# Railway template drafts (open-fdd)

Not yet a published Railway Template. Do **not** add a README deploy button until validated.

## Target topology

1. `openfdd-central` (private, volume `/workspace`)
2. `openfdd-mqtt` (private MQTTS 8883) — **default for cloud MQTTS hub**
3. `openfdd-web` (public) with `OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080`

CSV-only variant may omit mqtt.

## Required generated variables

- `OPENFDD_JWT_SECRET`
- `OPENFDD_ADMIN_PASSWORD`
- Web: `OPENFDD_CENTRAL_UPSTREAM`, `OPENFDD_NGINX_RESOLVER=auto`

## Images

Pin `:sha-<7>` for qualification; offer `:nightly` as the floating channel after green GHCR publish.

## Platform gap

Railway does not currently expose a portable `dependsOn` for private-DNS peers. Templates and docs must still instruct: central healthy → mqtt → web.

## CLI

Operator hub ops use `@railway/cli` on bensbench — verified **`railway login`** + link to **`gleaming-cooperation`** / **`production`** (2026-08-29).

Docs: [RAILWAY_DEPLOYMENT.md](../docs/operations/RAILWAY_DEPLOYMENT.md#railway-cli-bensbench--agent-hosts) · skill [`openfdd-railway-cli`](../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md).

Live service names: `openfdd-central-cQ-F`, `openfdd-mqtt`, `openfdd-web` (confirm with `railway status` before re-pin).
