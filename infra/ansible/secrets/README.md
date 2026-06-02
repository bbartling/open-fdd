# Edge deploy secrets (local only)

**Do not commit** files matching `*.env.local` or any file without `.example` in this directory.

Agents and operators: read the matching `*.env.local` here **before** Ansible deploy or SSH to a real building. GitHub only has `*.example` placeholders.

## Setup (once per machine)

```bash
cd infra/ansible

# Inventory + host vars (gitignored at repo root)
cp inventory.example.yml inventory.yml
cp host_vars/acme_vm_bbartling.yml.example host_vars/acme_vm_bbartling.yml

# SSH / site facts for agents + deploy.sh auto-load
cp secrets/acme.env.example secrets/acme.env.local
# Edit secrets/acme.env.local — set SSHPASS, ansible_host, URLs
chmod 600 secrets/*.env.local
```

`deploy.sh` automatically sources `secrets/<host>.env.local` when you pass `--limit <inventory_host>` (e.g. `acme_vm_bbartling` → `acme.env.local`).

Manual override still works: `export SSHPASS='…' ./deploy.sh ui --limit acme_vm_bbartling`

## Files

| File | Tracked | Purpose |
|------|---------|---------|
| `acme.env.example` | yes | Template for Acme VM (Tailscale SSH, OT BACnet NIC, site ids) |
| `acme.env.local` | **no** | Real Acme SSH password, IPs, dashboard URL |
| `bacnet_pi.env.example` | yes | Template for bench Pi |
| `bacnet_pi.env.local` | **no** | Real bench SSH if used |

## Related gitignored paths

| Path | Contents |
|------|----------|
| `infra/ansible/inventory.yml` | `ansible_host`, `ansible_user` per host |
| `infra/ansible/host_vars/acme_vm_bbartling.yml` | BACnet bind, feather caps, feature flags |
| `workspace/auth.env.local` | Bridge login (integrator/operator/agent) — **not** SSH |
| `edge_backup/local/<site>/<building>/` | Commissioned `points.csv`, discovery CSVs |

## Agent policy

- Use **`secrets/acme.env.local`** + **`inventory.yml`** for Acme deploys — do not guess IPs or passwords.
- Never paste `SSHPASS` or `ofdd_*` secrets into commits, PRs, issues, or tracked Markdown.
- Public docs: [docs/edge_deploy.md](../../docs/edge_deploy.md) and `inventory.example.yml` use RFC 5737 / placeholder addresses only.
