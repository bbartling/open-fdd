# Ansible: Linux bench bootstrap (WSL-friendly)

Automates deployment of:

- Open-FDD gateway + MCP + UI (Vite)
- easy-aso supervisor
- diy-bacnet-server
- Caddy ingress/auth (Option A baseline)

on a remote Linux host over SSH.

## Layout

- `ansible.cfg`
- `inventory.example.ini`
- `group_vars/bench.yml`
- `site.yml`
- roles:
  - `common`
  - `openfdd_stack`
  - `easyaso`
  - `diy_bacnet`
  - `caddy_gateway`
  - `systemd_services`
  - `verify`

## Run from WSL

```bash
cd /mnt/c/Users/ben/Documents/open-fdd/infra/ansible
python3 -m venv .venv
source .venv/bin/activate
pip install ansible
cp inventory.example.ini inventory.ini
```

Edit:

- `inventory.ini` for your host IP/user
- `group_vars/bench.yml` for secrets, CIDR, ports, auth hash

Generate Caddy hash:

```bash
caddy hash-password --plaintext 'change-me-now'
```

Paste into `caddy_basic_auth_hash`.

Deploy:

```bash
ansible-playbook -i inventory.ini site.yml
```

## Defaults

- Caddy variant: `cidr`
- CIDR allowlist: `10.0.0.0/8` (tighten later)
- Open-FDD bridge: `8765`
- MCP RAG: `8090`
- UI: `5173`
- easy-aso supervisor: `18090`
- DIY BACnet: `8080`

## Notes

- Backends bind localhost/private ports; Caddy is public ingress on `:80` by default.
- If you want HTTPS internal CA, set `caddy_variant: tls-internal` in `group_vars/bench.yml`.
- Keep all bearer keys distinct in real deployments.
- Linux layout follows common practice:
  - code in `/opt/*`
  - mutable app state in `/var/lib/openfdd` and `/var/lib/easyaso`
  - secrets/env in `/etc/openfdd/bench.env` (`0600`)
- systemd units include baseline hardening (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, limited `ReadWritePaths`).
- `group_vars/bench.yml`: set `ofdd_ui_public_base` and `bench_env_http_host` if the UI/API should not use loopback URLs; set `npm_path` if `npm` is not at `/usr/bin/npm`.
