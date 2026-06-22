# BACnet OT NIC setup

Ben's Linux test box currently shows:

```text
enp3s0 = 192.168.204.55/24
```

Generate `.env` safely without changing the NIC:

```bash
cd ~/open-fdd
./scripts/openfdd_bacnet_nic_setup.sh
cat .env
```

Apply a static CIDR only when you intentionally want the script to touch the NIC:

```bash
OPENFDD_BACNET_CONFIGURE_NIC=1 ./scripts/openfdd_bacnet_nic_setup.sh --apply
```

Normal simulated Docker test:

```bash
docker compose --env-file .env down
docker compose --env-file .env build --no-cache
docker compose --env-file .env up
```

Live BACnet Linux OT LAN shape:

```bash
docker compose -f docker-compose.yml -f docker-compose.bacnet-live.yml --env-file .env down
docker compose -f docker-compose.yml -f docker-compose.bacnet-live.yml --env-file .env build --no-cache
docker compose -f docker-compose.yml -f docker-compose.bacnet-live.yml --env-file .env up
```

Check that the config is visible through the API:

```bash
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"sub":"linux-test","role":"agent"}' | jq -r .access_token)"

curl -s http://127.0.0.1:8080/api/bacnet/commission/status \
  -H "Authorization: Bearer $TOKEN" | jq .

curl -s http://127.0.0.1:8080/api/bacnet/driver/tree \
  -H "Authorization: Bearer $TOKEN" | jq .bacnet_config
```
