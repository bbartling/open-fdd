# Raspberry Pi Rust edge (ARM64)

## Platform check

```bash
./scripts/openfdd_rust_check_ghcr_platform.sh
```

Requires `ghcr.io/bbartling/openfdd-edge-rust` manifest to include `linux/arm64` (published via `.github/workflows/rust-ghcr.yml`).

## Install on Pi

```bash
export OPENFDD_DOCKER_PLATFORM=linux/arm64
bash /tmp/openfdd_rust_edge_bootstrap.sh --start --platform linux/arm64
```

## BACnet live on Pi

Set in `workspace/bacnet/commissioning/commission.env`:

```bash
OPENFDD_BACNET_MODE=live
OPENFDD_BACNET_IFACE=eth0
OPENFDD_BACNET_BIND=<pi-ip>/24:47808
```

Use host networking for commission service (already in `docker/compose.edge.rust.yml`).

## Troubleshooting

If pull fails with platform error, the image may not be multi-arch published yet. Build locally on Pi from source or trigger `rust-ghcr` workflow dispatch.
