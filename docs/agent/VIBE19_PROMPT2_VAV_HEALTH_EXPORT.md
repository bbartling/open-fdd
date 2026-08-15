# Vibe19 Prompt 2 — pin PyPI analytics + export `vav_health_matrix.csv`

Run on the **vibe19 / playground machine only**. bensbench pulls `ghcr.io/bbartling/vibe19`; it does not rebuild this image.

## Pin

```text
open-fdd[reporting]==4.4.1
```

(Use **4.4.1** once tagged on PyPI; 4.4.0 already has `vav_health_matrix_v1`.)

## Shim (do not reimplement)

```python
from open_fdd.analytics import dump_tables, vav_health_matrix

# Diagnostic WattLab dump MUST write:
#   vav_health_matrix.csv
#   mech_cooling_oat_bins.csv
#   motor_hours.csv
#   motor_weekly.csv
# Prefer dump_tables(out_dir, frames=..., role_map=..., rule_results=...)
# Overview matrix is presentation only.
```

Rebuild `ghcr.io/bbartling/vibe19` there; on bensbench:

```bash
docker pull ghcr.io/bbartling/vibe19:latest
```
