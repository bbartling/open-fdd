# Historical 3.5 OT, MQTT, and Parquet ops

**Status: historical/non-executable.** This page is not `architecture_epoch: portal-timescale-v1`.

Do not run these recipes on the 4.0 product. Product ingest is the Normal Framework portal API and CSV. The historian is Timescale. Railway services for that product are central and web, with Timescale. MQTT, fieldbus, DataFusion, and Parquet-as-historian steps below are kept so the old commands are not lost. The container snapshot is [`archive/ot-edge/`](../../../archive/ot-edge/).

## Retired image pins

These pins are not the 4.0 portal tip. Do not re-pin a hub to them.

| Label | Pin |
| --- | --- |
| Wave U V6 FQ ops (2026-09-21) | `sha-7ad6479` / 3.5.43 · stress `20260921T234148Z` |
| Prior Wave U FQ | `sha-1677c33` / 3.5.37 |
| Soft Tip B | `sha-4a5c11e` / 3.5.28 |
| Wave S1 FQ (2026-09-19) | `sha-7b81eb8` / 3.5.31 · stress `reports/nightly-ot-bench_20260919T195100Z/` |
| Hub smoke, not an FQ claim | `sha-3cd3745` / 3.5.33 |
| Wave N | `sha-9072e0b` / 3.5.10 |
| Wave K closed | `sha-9c3e8b1` / 3.4.0 |

## Retired Railway order

Live service names at the time included `openfdd-central-cQ-F`, `openfdd-mqtt`, and `openfdd-web` on project `gleaming-cooperation` / `production`. The order was central, then mqtt, then web.

```bash
./scripts/railway_central_workspace_backup.sh
railway service source connect --service "$CENTRAL_SVC" \
  --image "ghcr.io/bbartling/openfdd-central:${SHA}"
railway service source connect --service openfdd-mqtt \
  --image "ghcr.io/bbartling/openfdd-mqtt:${SHA}"
railway variable set OPENFDD_PARQUET_ROOT=/workspace/openfdd --service "$CENTRAL_SVC"
railway service source connect --service openfdd-web \
  --image "ghcr.io/bbartling/openfdd-web:${SHA}"
```

MQTT cert volume was `/mosquitto/certs` (`ca.pem`, `server.cert.pem`, `server.key.pem`, `acl`), with `acl_file /mosquitto/certs/acl`. Field publish was x86 `openfdd-fieldbus` into Railway MQTTS. Poll and publish were compiled to 300 s. Pis were out of that stress. `OPENFDD_INGEST_MODE` values `mqtts`, `local_fieldbus`, and `dual` belonged to that lane.

## Retired public stress

`run_railway_hub_stress.sh` ran gates 00–17, including ZAP against the public Railway URL, after fieldbus was up. Wave L called for one enhanced full stress at L8 with `fully_qualified=true` and no `SKIP_ZAP`. That is not the 4.0 disposable portal check.

## Retired local pull

```bash
for img in openfdd-central openfdd-web openfdd-fieldbus openfdd-mqtt; do
  docker pull "ghcr.io/bbartling/${img}:sha-${SHORT}"
done
./scripts/openfdd_stack_up.sh react-ot --no-pull
```

`openfdd_stack_up.sh` now refuses `standalone`, `edge`, and `react-ot`. The archive render, which does not start containers, is:

```bash
OPENFDD_OT_ARCHIVE_RESTORE=1 ./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay
```
