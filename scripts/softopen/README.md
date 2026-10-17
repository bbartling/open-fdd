# Soft-OPEN Railway / hub suite

Orchestrates **lessons + stress + DB sample checks + plot bools** against a live
hub (Railway or LAN). Soft-OPEN ≠ FQ. **No screenshots** — plot gates are API
`point_count > 0` bools. ZAP / security Soft-OPEN is deferred.

## Unique building id

```bash
python scripts/softopen/run_softopen_railway.py \
  --host openfdd-web-production.up.railway.app \
  --unique-building --shortsha 52e1045
```

Allocates `SOFTOPEN_<YYYYMMDD>_<sha7>`. Import a fixture into that id before
expecting PASS (see #1281). Or pass an existing synth / `BUILDING_100`:

```bash
python scripts/softopen/run_softopen_railway.py \
  --base-url https://openfdd-web-production.up.railway.app \
  --building-id SYNTH_03
```

## Pieces

| Script | Job |
| --- | --- |
| `run_softopen_railway.py` | Orchestrator |
| `validate_db_samples.py` | Mapped roles must have Timescale history |
| `validate_plot_bool.py` | RDF/type → AHU rules → FDD plot + RCx runtime bools |

Also uses `scripts/lessons/*` and `scripts/stress/run_gate.py --remote-api`.

Env: `OPENFDD_AGENT_PASSWORD`, optional `OPENFDD_API_BASE`.
