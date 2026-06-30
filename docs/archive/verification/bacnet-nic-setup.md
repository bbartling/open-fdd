# BACnet OT NIC setup

Configure the host NIC and bind address before live BACnet commissioning.

## Detect your interface

```bash
ip -4 addr show
ip -4 route get 1.1.1.1
```

Note your OT-LAN interface (example: `enp3s0`) and host IP (example: `192.168.204.55/24`).

## Generate `.env` safely

```bash
cd ~/open-fdd
./scripts/openfdd_bacnet_nic_setup.sh
cat .env
```

By default the script **does not** change NIC configuration — it writes suggested values only.

To apply a static CIDR when you intentionally want the script to configure the NIC:

```bash
OPENFDD_BACNET_CONFIGURE_NIC=1 ./scripts/openfdd_bacnet_nic_setup.sh --apply
```

## Simulated Docker test (CI default)

```bash
docker compose --env-file .env down
docker compose --env-file .env build --no-cache
docker compose --env-file .env up
```

## Live BACnet overlay

```bash
docker compose -f docker-compose.yml -f docker-compose.bacnet-live.yml --env-file .env up --build
```

Set in `.env` or `workspace/data.env.local`:

```text
OPENFDD_BACNET_MODE=live
OPENFDD_BACNET_IFACE=<your-iface>
OPENFDD_BACNET_BIND=<your-ip>/24:47808
```

## API check

```bash
TOKEN="$(curl -fsS -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"sub":"lab","role":"integrator"}' | jq -r .access_token)"

curl -fsS http://127.0.0.1:8080/api/bacnet/commission/status \
  -H "Authorization: Bearer $TOKEN" | jq .

curl -fsS http://127.0.0.1:8080/api/bacnet/driver/tree \
  -H "Authorization: Bearer $TOKEN" | jq '.bacnet_config'
```

Pass: `iface` and `bind` match your site configuration.
