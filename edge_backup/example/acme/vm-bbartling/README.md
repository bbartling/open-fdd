# Acme vm-bbartling edge backup (example layout)

Real BACnet discovery CSVs live under `edge_backup/local/acme/vm-bbartling/` (gitignored).

## Commission scripts

```bash
# GL36 + economizer passive poll set (60s) → points.csv
./infra/ansible/scripts/acme_commission_gl36.sh

# Temperature-only subset (smaller footprint)
./infra/ansible/scripts/acme_commission_temp.sh
```

## GL36 poll coverage (from Trim & Respond guide)

| Layer | Points polled |
|-------|----------------|
| VAV | ZN-T, ZN-SP, DA-T, SA-F, SAFLOW-SP, damper cmd/stat, CLG-O, HTG-O |
| AHU (RTU-01) | SAT, RAT, MAT, OAT, SAP + SAP-SP (active/BAS), DAT-SP (discharge/leaving air setpoints), OAD-CMD, fan cmds, CLG-STAT |
| Plant | HW temps, pump/boiler analogs, plant request counters |
| Tracer | Facility OAT/OAH, zone avg/min/max temps |

## Site model + validation

```bash
SITE=acme BUILDING=vm-bbartling
PYTHONPATH=workspace/api python3 scripts/gl36_site_model.py --site-id "$SITE" --building-id "$BUILDING"
python3 scripts/setup_gl36_fdd.py --site-id "$SITE" --building-id "$BUILDING" \
  --ahu-system-id rtu-01 --fan-point-id 1100-analog-output-1
python3 scripts/gl36_mechanical_validate.py --site-id "$SITE" --building-id "$BUILDING" \
  --samples /path/to/samples.csv
```

Reference: [GL36 Trim & Respond](https://github.com/bbartling/niagara4-vibe-code-addict/blob/develop/README_TRIM_RESPOND.md)
