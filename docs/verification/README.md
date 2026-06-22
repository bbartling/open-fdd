# Verification checklists

These documents describe **how to confirm** Open-FDD Rust edge behavior on a real or lab host. They replace the old root-level `VERIFY_*.md` files.

## When to use

- After `openfdd_rust_edge_bootstrap.sh --start`
- After driver or UI changes
- Before promoting a release tag to GHCR
- When validating live OT paths (BACnet/Modbus) on your LAN

## Principles

- **Simulated mode** is the CI default — honest labels, no fake live data.
- **Live mode** requires your site IP/bind settings and an OT network.
- Replace example IPs, interfaces, and device instances with your site values.

## Index

- [CI and GitHub Actions](ci-github-actions.md)
- [BACnet NIC setup](bacnet-nic-setup.md)
- [BACnet override scanner](bacnet-overrides.md)
- [Modbus live reads](modbus-live.md)
- [UI smoke](ui-smoke.md)
- [Auth and login](auth-and-login.md)
