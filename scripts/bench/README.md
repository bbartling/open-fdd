# Bench-only validation scripts

These scripts are **not** required for production edge deploy. They live under `scripts/bench/` so upstream `rsync` from product source does not delete bench orchestrators on the Linux edge tester.

| Script | Purpose |
|--------|---------|
| `openfdd_bacnet_poll_daemon.sh` | Persistent OT poll loop (BACnet + Modbus + FDD status) |
| `openfdd_stores_fdd_soak.sh` | Short FDD historian soak wrapper |
| `run_bacnet_pcap_capture.sh` | 5-min BACnet/IP PCAP for regression vs vibe16 baseline |

Run from bench root (`~/open-fdd`):

```bash
./scripts/bench/openfdd_bacnet_poll_daemon.sh start
OPENFDD_SOAK_MINUTES=10 ./scripts/bench/openfdd_stores_fdd_soak.sh
OPENFDD_EDGE_SHA=abc1234 ./scripts/bench/run_bacnet_pcap_capture.sh 300
```

Symlink or copy into `scripts/` on the bench if older prompts reference top-level paths.

Fixes #470.
