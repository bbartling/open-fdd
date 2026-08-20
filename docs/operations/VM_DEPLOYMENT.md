---
title: VM deployment
parent: Operations
nav_order: 5
---

# VM deployment behind a firewall

This is the recommended self-hosted dashboard recipe for an IT department that wants Open-FDD on a Linux VM inside a private network. It uses the same public GHCR images as the Railway cloud-lab recipe, but keeps the application entirely on the organization's LAN/VPN.

## Recommended topology

For CSV/package analytics, deploy only:

| Service | Image | Host port | Purpose |
| --- | --- | ---: | --- |
| central | `ghcr.io/bbartling/openfdd-central:<tag>` | `8080` | API, package ingest, historian, DataFusion FDD |
| web | `ghcr.io/bbartling/openfdd-web:<tag>` | `3000` | React dashboard; proxies `/api` to central |

Use the repository's `csv` Compose recipe. MQTT and fieldbus are not required for a dashboard that consumes uploaded CSV/package data.

For live BACnet/Modbus/Haystack integrations, add the OT recipe only after the VM/network design deliberately provides the required OT connectivity.

## VM prerequisites

A practical baseline is:

- current Ubuntu/Debian/RHEL-family Linux VM;
- Docker Engine with Compose v2;
- outbound HTTPS to `ghcr.io` for image pulls;
- persistent local disk for the repository `workspace/` directory;
- inbound TCP `3000` from approved LAN/VPN clients;
- TCP `8080` restricted to administrators or the VM itself when possible.

If the GHCR packages are public, no GitHub login or PAT is required to pull the images.

## Install

```bash
sudo mkdir -p /opt/open-fdd
sudo chown "$USER":"$USER" /opt/open-fdd
cd /opt/open-fdd

git clone https://github.com/bbartling/open-fdd.git .
```

Create a local secrets file outside version control:

```bash
cat > .env.local <<'EOF'
OPENFDD_IMAGE_TAG=nightly
OPENFDD_JWT_SECRET=replace-with-a-long-random-secret
OPENFDD_ADMIN_PASSWORD=replace-with-a-strong-password
OPENFDD_CENTRAL_BIND=127.0.0.1
OPENFDD_WEB_BIND=0.0.0.0
EOF
chmod 600 .env.local
```

For a controlled deployment, replace `nightly` with the immutable `sha-<7>` tag qualified for the release.

Load the variables and start the CSV/dashboard stack:

```bash
set -a
. ./.env.local
set +a

./scripts/openfdd_stack_up.sh csv
```

The default Compose recipe persists application data in `/opt/open-fdd/workspace` on the VM.

## Access

From an approved LAN/VPN client:

```text
http://<vm-hostname-or-ip>:3000
```

The React web container proxies browser API traffic to central over the Compose network. Users normally need access only to port `3000`.

Central liveness on the VM:

```bash
curl -fsS http://127.0.0.1:8080/api/health
```

If IT wants HTTPS and a friendly hostname such as `https://openfdd.example.internal`, put the web service behind the organization's existing reverse proxy/load balancer and TLS policy. Keep central private; proxy the browser to the web container rather than publishing central directly to users.

## Firewall recommendation

For a dashboard-only VM:

- allow inbound TCP `3000` only from trusted LAN/VPN networks, or expose only the organization's reverse proxy on `443`;
- keep central `8080` bound to `127.0.0.1` unless administrators genuinely need direct API access;
- do not expose BACnet, MQTT, or fieldbus ports merely because those images exist;
- never expose Open-FDD directly to the public internet without an independent security review.

## Updating

To move to a newly qualified image set:

```bash
cd /opt/open-fdd
git pull --ff-only

export OPENFDD_IMAGE_TAG=sha-abc1234
./scripts/openfdd_maint_update_resume.sh csv "$OPENFDD_IMAGE_TAG"
```

Use the same `sha-*` tag for central and web. `nightly` is convenient for labs; immutable SHA tags are preferred for an IT-managed VM.

Verify after update:

```bash
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:3000/api/health
```

The UI sidebar should show the running central release as `<semver>+<shortsha>`.

## Backups

Back up the VM's `/opt/open-fdd/workspace` directory using the organization's normal backup system. That directory contains imported package/historian state and should be treated as application data rather than disposable container state.

Before destructive maintenance, stop the stack without deleting volumes or workspace data. Never use `docker compose down -v` or `docker volume prune` as a routine Open-FDD update step.

## Optional live OT expansion

The dashboard VM recipe intentionally excludes fieldbus and MQTT. If the organization later wants live BAS connectivity, choose one of these patterns:

1. run `react-ot`/fieldbus on an OT-connected host with explicit BACnet/Modbus/Haystack access; or
2. keep the central dashboard VM separated and attach remote fieldbus edges over the project's MQTTS topology.

Do not assume a generic server VLAN can perform BACnet broadcast discovery.

## Security reporting

Suspected vulnerabilities belong in GitHub Private Vulnerability Reporting, not public issues:

https://github.com/bbartling/open-fdd/security/advisories/new

See [`SECURITY.md`](../../SECURITY.md).
