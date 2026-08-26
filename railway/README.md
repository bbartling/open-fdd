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
