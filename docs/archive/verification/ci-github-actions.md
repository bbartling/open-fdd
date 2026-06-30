# CI and GitHub Actions

## Primary workflows (Rust edge)

| Workflow | Purpose |
| --- | --- |
| `.github/workflows/ci.yml` | Rust fmt/check/test, frontend syntax, Docker build, compose API smoke |
| `.github/workflows/rust-ci.yml` | Extended Rust CI, secret scan, lifecycle script syntax |
| `.github/workflows/rust-ghcr.yml` | Multi-arch publish to `ghcr.io/bbartling/openfdd-edge-rust` |
| `.github/workflows/security.yml` | Deny legacy Python project shape on `master` |

## Compose smoke (automated)

On every PR, CI typically validates:

- `GET /api/health` and JWT login
- BACnet driver tree and override scan → CSV under `workspace/overrides/`
- Modbus simulated scan/read
- Frontend guards (no legacy Rule Lab routes)

## Manual field-bus validation

Use the verification guides when you have OT hardware:

- [BACnet NIC setup](bacnet-nic-setup.md)
- [BACnet overrides](bacnet-overrides.md)
- [Modbus live](modbus-live.md)

Live BACnet compose overlay: `docker-compose.bacnet-live.yml`

## Branch flow (developers)

```bash
git fetch origin
git checkout master
git pull origin master
git checkout -b feature/your-change
# … work …
git push -u origin feature/your-change
gh pr create --base master
```

Legacy Python publish workflows remain for historical tags only. The Rust rewrite line does not ship a PyPI runtime.
