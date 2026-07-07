# Bench-only validation scripts

These scripts are **not** required for production edge deploy. They live under `scripts/bench/` so upstream `rsync` from product source does not delete bench orchestrators on the Linux edge tester.

| Script | Purpose |
|--------|---------|
| `openfdd_bacnet_poll_daemon.sh` | Persistent OT poll loop (BACnet + Modbus + FDD status) |
| `openfdd_stores_fdd_soak.sh` | Short FDD historian soak wrapper |

Run from bench root (`~/open-fdd`):

```bash
./scripts/bench/openfdd_bacnet_poll_daemon.sh start
OPENFDD_SOAK_MINUTES=10 ./scripts/bench/openfdd_stores_fdd_soak.sh
```

Symlink or copy into `scripts/` on the bench if older prompts reference top-level paths.

Fixes #470.
