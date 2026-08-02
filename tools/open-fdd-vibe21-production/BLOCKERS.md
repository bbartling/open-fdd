# Vibe 21 oracle — PRESENT

**Status:** PRESENT on this host (2026-08-02).

```text
VIBE21_ORACLE=/home/ben/py-bacnet-stacks-playground/vibe_code_apps_21
```

Linux checks:

```bash
test -d "${VIBE21_ORACLE:-/home/ben/py-bacnet-stacks-playground/vibe_code_apps_21}"
```

Windows/`/mnt/c` paths from the Master Loop are not required when the Linux playground copy is present.

Phase 2+ inventory / frozen Flask/joblib conformance / Rust inference may proceed under the Master Loop (still offline-only for Python train/farm; no Flask/joblib in production images).

## Publish / BAS

- `PUBLISH_AUTHORITY` / `BAS_WRITE_AUTHORITY` remain human-gated per Master Loop.
