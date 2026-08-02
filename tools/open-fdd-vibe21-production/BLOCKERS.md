# Program blockers (living)

## Vibe 21 oracle (blocks Phase 2+)

**Status:** ABSENT on this host (2026-08-02).

Expected path from Master Loop:

```text
VIBE21_ORACLE = C:\Users\ben\Documents\py-bacnet-stacks-playground\vibe_code_apps_21
```

Linux/WSL checks:

```bash
test -d "$VIBE21_ORACLE" || test -d /mnt/c/Users/ben/Documents/py-bacnet-stacks-playground/vibe_code_apps_21
```

Until the oracle tree is mounted/cloned here, **do not start P2-M0** inventory,
frozen Flask/joblib conformance, or Rust inference work. Phase 1 recovery
(P1-M2-B onward) may continue.

## Publish / BAS

- `PUBLISH_AUTHORITY` / `BAS_WRITE_AUTHORITY` remain human-gated per Master Loop.
