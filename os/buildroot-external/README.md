# Buildroot external (placeholder)

**Not implemented.** Reserved for Phase C of [Open-FDD OS](../README.md): board support packages and defconfigs for x86_64 UEFI and Raspberry Pi ARM64.

When work starts, this tree will follow a Home Assistant OS–style layout:

- Minimal kernel + read-only rootfs
- Docker CE (or containerd + nerdctl) preinstalled
- RAUC hooks for A/B updates
- First-boot mount of `/var/openfdd` for `workspace/`

Until then, use standard Linux + [docker/compose.edge.rust.yml](../../docker/compose.edge.rust.yml).
