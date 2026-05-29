# Open-FDD edge commissioning backup (mirrors vibe_code_apps_12/edge_backup)

| Path | Git |
|------|-----|
| `local/{site_id}/{building_id}/points.csv` | gitignored — real deploy CSVs |
| `local/{site_id}/{building_id}/points_per_device/` | gitignored |
| `demo/` | optional committed examples |

Ansible pushes `local/{site_id}/{building_id}/points.csv` on deploy when present.

Copy commissioned CSVs from vibe12 backup if reusing the same BACnet point model:

```bash
mkdir -p edge_backup/local/acme/vm-bbartling
cp ../py-bacnet-stacks-playground/vibe_code_apps_12/edge_backup/local/acme/vm-bbartling/points.csv \
   edge_backup/local/acme/vm-bbartling/
```
