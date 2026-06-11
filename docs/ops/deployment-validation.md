---
title: Deployment validation
parent: Operations
nav_order: 4
---

# Deployment validation

For the **live Acme site** after GHCR updates, use the dedicated harness documented in [Acme live validation]({% link ops/acme-live-validation.md %}) (`acme_post_deploy_validate.sh`).

Non-destructive checks after deploy or image upgrade. Run from the **edge host** (smoke) or from a **control machine** with the full repo (insurance suite).

## Edge host smoke (5 minutes)

```bash
cd ~/open-fdd

docker compose ps
curl -sf http://127.0.0.1:8765/health | jq . || curl -sf http://127.0.0.1:8765/health

tail -1 workspace/bacnet/polls/samples.csv
du -sh workspace/data/feather_store/

docker compose logs --since 20m | grep -Ei "error|exception|traceback|critical" | tail -20 || true
```

Via Caddy (building LAN):

```bash
curl -sf http://<edge-ip>/health
curl -sf http://<edge-ip>/ | grep -o 'index-[^"]*\.js' | head -1
```

## Browser checklist

1. Open `http://<edge-ip>/` (Caddy `:80`, not only loopback `:8765`)
2. Integrator login (`workspace/auth.env.local` on the edge host)
3. **Host stats** — container image tag / git SHA
4. **BACnet** — driver tree shows devices; last poll timestamp recent
5. **Model & assignments** — commissioning export returns JSON
6. **Rule Lab** — quick-test a saved rule (`backend: arrow`)

## Control-machine insurance check

From a machine with the full `open-fdd` repo and Ansible inventory:

```bash
cd infra/ansible/scripts
./post_deploy_check.sh --limit <inventory_host> --full
```

Or by IP:

```bash
./post_deploy_check.sh --host <edge-ip> --ssh-user <deploy-user> --full
```

Checks include: Caddy → React dashboard, `/health/stack`, MCP RAG, BACnet tree, BRICK/SPARQL, Docker log scan.

{: .warning }
> **Do not run on live commissioned sites without approval:** `acme_operational_verify.sh` with BACnet rediscover — use `--skip-discover` for smoke only. See [Examples — GL36 lab]({% link examples/acme-gl36-lab.md %}).

## LAN security smoke (optional)

From a workstation on the same LAN as the edge:

- Windows: `scripts/security/Run-OpenFddSecurityScan.ps1`
- macOS/Linux: `scripts/security/run_openfdd_security_scan.sh`

Expected findings: [ZAP baseline]({% link security/zap-baseline.md %}).

## Arrow / FDD rules (3.0+)

On control machine:

```bash
./scripts/validate_fdd_backends.sh --docker
```

On edge after upgrade:

```bash
grep -R "apply_faults_arrow" workspace/data/rules_py | wc -l
```

## Related

- [Health check]({% link quick-start/health-check.md %})
- [Security testing cycle]({% link developer/security-testing.md %}) (maintainers)
