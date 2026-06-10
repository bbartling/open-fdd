# Patch cycle 3.0.22 — Acme dashboard & FDD (2026-06-11)

## Shipped in this branch (`fix/3.0.22-acme-dashboard`)

| Area | Change |
|------|--------|
| UI version strip | Shows `v3.0.22` only — git SHA removed |
| Ollama status | Gray on CPU-only / optional hosts; no “offline” banner on insight card |
| Poll health | Dedupe equipment rows by BACnet device instance → **33 physical devices** not 66 BRICK rows |
| FDD alerts | Titles use BAS names (`Trane Vav 12035 · VAV-C · …`); group by equipment not fault family |
| Zone comfort | Collapsible per-AHU tree on dashboard; worst-zone dedupe by equipment name |
| FDD rules | +3 Arrow rules: damper stuck (VAV-D), airflow low (VAV-B), reheat DAT vs SAT (VAV-A) |
| Column sweep | Arrow bound-column runs record `flagged_columns` for equipment resolution |

## Deploy Acme (GHCR)

```bash
source infra/ansible/secrets/acme.env.local
git checkout fix/3.0.22-acme-dashboard   # after merge/tag
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
python3 scripts/setup_gl36_fdd.py --site-id acme --building-id vm-bbartling \
  --host "$ACME_SSH_HOST" --token "$TOKEN"
./infra/ansible/scripts/acme_operational_verify.sh --host "${ACME_SSH_HOST}"
```

## Validate after deploy

1. Dashboard footer: `v3.0.22` (no `2866799`)
2. Stack strip: Ollama dot **gray**, not red
3. Poll health sentence: `33/33` (or ~33/x) not `33/66`
4. Fault cards: equipment name first, fault code second
5. Comfort panel: expand AHU → all VAV rows; recovery `—` until fan column mapped on RTU 1100
6. FDD batch: re-run; confirm new VAV rules bind where brick types exist

## Known follow-ups (next patch)

| Issue | Notes |
|-------|--------|
| Recovery rates all `—` | Needs AHU fan point in model + `supply-fan-*` in feather; verify `--fan-point-id` on setup_gl36 |
| 64 cols / 128 sensors | Re-ingest after unique `external_id` per zone point (plot_column_name uses full point id) |
| `acme-zn-t-oob-occupied` ~71% | Tune bounds / occupied mask after column fix |
| Historian lag (12 devices) | Feather ingest behind live poll — verify post-upgrade ingest loop |
| Duplicate Trane rows in table | Should improve with equipment-name dedupe; full fix needs unique historian columns |

## Tuning wake (after stability)

```bash
./scripts/acme_wake_orchestrator.sh   # 6h FDD tuning + portfolio collect
```
