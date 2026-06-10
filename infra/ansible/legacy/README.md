# Legacy Ansible playbooks (workstation file deploy)

**Obsolete for production edges.** Open-FDD deploys via **GHCR containers** only.

These playbooks remain for lab Pi hosts without Docker or historical reference.

| File | Was used for |
|------|----------------|
| `deploy.yml` | rsync `open_fdd/`, `workspace/api/`, UI static, systemd units |
| `bench_edge_data_sync.yml` | Push bench model + rules from control machine |

## Supported deploy path

```bash
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
# or on edge: OPENFDD_IMAGE_TAG=latest ./scripts/update-open-fdd-edge.sh
```

Models, rules, and commissioning payloads: **HTTPS API** (`/api/model/commissioning-import`, `/api/rules/save`) over VPN/Tailscale — not Ansible file copy.

To run legacy playbooks (lab only):

```bash
export OPENFDD_ALLOW_LEGACY_DEPLOY=1
ansible-playbook -i inventory.yml legacy/deploy.yml --limit bacnet_pi
```
