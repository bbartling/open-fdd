# Edge deploy (Ansible)

Public reference for deploying Open-FDD to field VMs and bench hardware. **Real IPs, SSH passwords, and BACnet OT addresses live only in gitignored files** on your control machine — never in this doc or on GitHub.

## What is safe on GitHub

| Tracked | Gitignored |
|---------|------------|
| `infra/ansible/deploy.sh`, playbooks, `*.example` inventory/host_vars | `inventory.yml`, `host_vars/acme_vm_bbartling.yml` |
| `infra/ansible/secrets/*.example`, `secrets/README.md` | `infra/ansible/secrets/*.env.local` |
| `inventory.example.yml` (placeholder IPs) | `edge_backup/local/**` |
| `docs/edge_deploy.md` (this file) | `workspace/auth.env.local` |

## One-time setup

```bash
cd infra/ansible

cp inventory.example.yml inventory.yml
cp host_vars/acme_vm_bbartling.yml.example host_vars/acme_vm_bbartling.yml
cp secrets/acme.env.example secrets/acme.env.local

# Edit inventory.yml: set ansible_host + ansible_user for each host
# Edit secrets/acme.env.local: SSHPASS, ACME_SSH_HOST, BACnet bind, dashboard URL
chmod 600 secrets/*.env.local
```

## Deploy commands (examples)

Build UI first when deploying `ui` or `all`:

```bash
../../scripts/build_operator_dashboard.sh prod
./deploy.sh ui --limit acme_vm_bbartling
./deploy.sh backend --limit acme_vm_bbartling
./deploy.sh commission --limit acme_vm_bbartling
./deploy.sh drivers --limit acme_vm_bbartling -e enable_bacnet_poll_driver=true
```

`deploy.sh` sources `secrets/acme.env.local` when `--limit acme_vm_bbartling` is set, so you do not need to re-export `SSHPASS` every session if the file exists.

## Inventory hosts

| Host key | Role | Example placeholder in repo |
|----------|------|-----------------------------|
| `acme_vm_bbartling` | Real building (x86 VM, OT BACnet) | `198.51.100.55` in `inventory.example.yml` |
| `bacnet_pi` | Boss Pi bench (armv7l) | `198.51.100.12` |

Set real addresses in private `inventory.yml`. Use [RFC 5737 documentation addresses](https://datatracker.ietf.org/doc/html/rfc5737) in examples only.

## Acme commissioning layout

Commissioning CSVs are pushed from:

```text
edge_backup/local/<site_id>/<building_id>/points.csv
edge_backup/local/<site_id>/<building_id>/device_poll_profiles.csv
```

Example site/building ids: `acme` / `vm-bbartling` (set in host_vars, not secrets).

## Auth vs SSH

- **SSH** (`SSHPASS`, `acme.env.local`): VM login for Ansible — field IT credential.
- **Dashboard** (`workspace/auth.env.local`): integrator/operator/agent web login — deployed via `config` tag, separate from SSH.

Do not put web passwords in `secrets/*.env.local` or SSH passwords in `auth.env.local`.

## Agent / Cursor context

- Read `infra/ansible/secrets/README.md` and the host’s `secrets/<site>.env.local` before deploy.
- Read `AGENTS.md` § Security.
- Rule: never commit or quote real secrets in tracked files.

Full playbook reference: [infra/ansible/README.md](../infra/ansible/README.md).
