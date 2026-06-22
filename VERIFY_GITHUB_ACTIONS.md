# GitHub Actions (Open-FDD 3.2.0 Rust edge)

Primary workflow: `.github/workflows/ci.yml`

Runs on every push/PR:

- Rust 1.93 format / check / test
- Frontend syntax + legacy UI guard
- Docker image build
- Docker Compose smoke:
  - health + JWT login
  - BACnet driver tree + override scan + CSV export
  - Modbus simulated scan/read
  - workspace CSV files exist

Live field-bus validation is manual (OT LAN):

- BACnet: `VERIFY_BACNET_NIC.md`, `VERIFY_BACNET_REALDEAL.md`, `docker-compose.bacnet-live.yml`
- Modbus: `VERIFY_MODBUS.md` (RPi `192.168.204.14:1502`)

Legacy Python publish workflows remain for historical tags only; the 3.2.0 line is 100% Rust.

Branch flow:

```bash
git checkout release/3.2.0   # or master after merge
git pull
docker compose up --build
```
