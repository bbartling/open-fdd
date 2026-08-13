# WattLab / Agent AFDD exporter (cookbook oracle path)

Headless export used by `openfdd-central` job WattLab dumps.
Not a product UI. No product UI.

```bash
python3 tools/wattlab_export/agent_afdd.py \
  --package /path/to/building.zip \
  --out /tmp/out \
  --run-all \
  --no-bootstrap
```

Central resolves the script via `OPENFDD_AGENT_AFDD_SCRIPT` (image default:
`/app/tools/wattlab_export/agent_afdd.py`).
