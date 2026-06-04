# Edge site packs (tracked templates)

Canonical per-site configs pushed to `workspace/` or field VMs — **not** mixed across buildings.

| Path | Site |
|------|------|
| `demo/bens-office/` | Bensserver MSTP test bench (FEC 5007) — **default dev template** |
| Site GL36 model | `workspace/data/<site>_<building>_gl36_model.json` from `scripts/gl36_site_model.py`; pack under `edge_backup/local/<site>/<building>/` |

```bash
./scripts/edge_site_apply.sh demo bens-office      # dev bench
./scripts/edge_site_backup.sh demo bens-office     # snapshot workspace → edge_backup/local/
./scripts/edge_site_apply.sh acme vm-bbartling --from-backup   # restore Acme from backup
```

Deploy (`deploy.sh docker`) copies **site-specific** `model.json`, `points.csv`, and `rules_store.json` from `edge_backup/local/<site_id>/<building_id>/` — not the whole dev `workspace/data` tree.
