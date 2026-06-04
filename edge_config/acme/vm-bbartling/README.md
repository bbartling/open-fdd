# Acme site pack (template)

Do **not** commit bench `model.json` or `rules_store.json` here. Real Acme payloads live under `edge_backup/local/acme/vm-bbartling/` (gitignored on field machines).

Generate and apply:

```bash
python3 scripts/gl36_site_model.py --site-id acme --building-id vm-bbartling
python3 scripts/setup_gl36_fdd.py --site-id acme --building-id vm-bbartling --ahu-system-id rtu-01 --fan-point-id <fan-point-id>
./scripts/edge_site_backup.sh acme vm-bbartling
```

Tracked files in this folder: `commission.env`, `pack_meta.json`, and optional `points.csv` reference only.
