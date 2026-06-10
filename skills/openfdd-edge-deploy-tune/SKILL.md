---
name: openfdd-edge-deploy-tune
description: "Turnkey Open-FDD edge deploy, Acme patch cycles, GHCR Docker upgrades, and FDD tuning via Tailscale/API. Use when deploying to acme_vm_bbartling, running setup_gl36_fdd, tuning rules, validating poll health, JSON API weather, or BACnet override scans."
---

# Open-FDD edge deploy and FDD tuning

## When to use

Use for **production edge VMs** (Acme lab: Tailscale `100.122.106.124`) — not local bensserver dev unless explicitly asked.

Triggers: patch cycle, GHCR upgrade, `setup_gl36_fdd.py`, tuning brief, operational verify, poll health, OpenWeather, override scans.

## Turnkey patch cycle (required order)

1. **Branch** from `master`: `fix/3.0.N-<topic>`
2. **Bump** `open_fdd/__init__.py` + `pyproject.toml` version
3. **Tests**: `pytest open_fdd/tests/arrow_runtime tests/workspace_bridge/test_acme_* -q`
4. **PR** → CI green → merge
5. **GHCR**: `gh workflow run "Publish Docker addons" --ref master` (retry if commission push `unknown blob` — see [#260](https://github.com/bbartling/open-fdd/issues/260))
6. **Deploy** (image-only; preserves feather/model on edge):

```bash
source infra/ansible/secrets/acme.env.local
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
```

7. **Push rules + model aliases** (HTTPS API, not rsync):

```bash
source workspace/auth.env.local  # integrator password
TOKEN=$(curl -fsS -X POST "http://${ACME_SSH_HOST}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"${ACME_INTEGRATOR_USER}\",\"password\":\"${ACME_INTEGRATOR_PASSWORD}\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')

python3 scripts/acme_patch_oat_column.py --host "$ACME_SSH_HOST" --token "$TOKEN"
python3 scripts/setup_gl36_fdd.py --site-id acme --building-id vm-bbartling \
  --host "$ACME_SSH_HOST" --token "$TOKEN" \
  --ahu-equipment-id acme-vm-bbartling-rtu-01 --fan-point-id 1100-analog-output-1
```

8. **Verify**:

```bash
./infra/ansible/scripts/acme_operational_verify.sh --host "${ACME_SSH_HOST}"
python3 scripts/acme_validate_fdd_bundle.py
```

9. **Halt rule:** If deploy or CI blocked, open a GitHub issue with exact state — do not leave branch ambiguous. Do not add internal patch-cycle notes under `docs/` (they publish to GitHub Pages and the PDF bundle).

## FDD tuning via API (Tailscale)

Auth: integrator role. `window_minutes` max **180** on check-in/tuning endpoints.

```bash
BASE="http://${ACME_SSH_HOST}"
# TOKEN from login above

# 1) Poll + FDD batch (3 h window)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  "$BASE/api/building-agent/checkin" \
  -d '{"site_id":"acme","run_fdd_batch":true,"write_memory":false,"window_minutes":180}'

# 2) Tuning brief (errors first; threshold proposals only if keepup >= 85%)
curl -fsS -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/building-agent/tuning-brief?site_id=acme&window_minutes=180"

# 3) Dry-run bounds patches (default)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  "$BASE/api/building-agent/apply-tuning" \
  -d '{"site_id":"acme","apply":false,"run_fdd_batch":false}'

# 4) Apply patches (only when brief recommends and operator approves)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  "$BASE/api/building-agent/apply-tuning" \
  -d '{"site_id":"acme","apply":true,"run_fdd_batch":true}'
```

**Interpretation:**

| Signal | Action |
|--------|--------|
| `keepup_ratio` < 0.85 | Fix BACnet poll before tuning thresholds |
| `runs_error` > 0 | Fix rule code/bindings; see `GET /api/fdd/results` |
| Rule flag rate > ~70% sustained | Add to **watch**; need analytics for auto bounds (≥85% + Arrow sweep) |
| `acme-zn-t-oob-occupied` noisy | Widen bounds in rule config or disable until occupied schedule validated |

Rule bundle reference: `docs/operations/acme_vav_ahu_rule_guidance.md`

## Acme site facts (do not re-discover)

| Item | Value |
|------|--------|
| Site / building | `acme` / `vm-bbartling` |
| AHU equipment | `acme-vm-bbartling-rtu-01` (BACnet **1100**) |
| Poll interval | **60 s**, ~340 enabled points |
| JCI VAV | instances 1–100, imperial °F |
| Trane VAV | 11000–13000, `metric_temp_f` in `device_poll_profiles.csv` |
| Local OAT column | `oa-t` on point `1100-unknown-2` |
| Web OAT | JSON API `web-oat-t` (OpenWeather, ~20 min) |
| Weather rule | `acme-oat-vs-web-spread` (BLD-B, 8 °F spread) |
| Override scans | 1 device/hour, P8; status `GET /api/bacnet/overrides/status` |

## Validation checklist

```bash
curl -s "$BASE/health" | jq '{v:.openfdd_version,git:.git_sha}'
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/analytics/poll-throughput?site_id=acme" | jq '{status,keepup:.keepup_ratio}'
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/openfdd-agent/operational-brief?force=true" \
  | jq '.device_poll_health | {healthy:.healthy_count,physical:.physical_device_count}'
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/json-api/endpoints" \
  | jq '.endpoints[]|select(.label=="web-oat-t")|{last_value,last_read_at}'
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/bacnet/overrides/status" \
  | jq '{devices:.device_count,last:.last_scan_at,next:.next_device_instance}'
```

Expect: version matches merged tag, keepup ≥ 0.85, poll health 33/33, fresh `web-oat-t`.

## Related skills

- [rules-crud-and-batch-run](../rules-crud-and-batch-run/SKILL.md) — Rule Lab API
- [driver-bacnet-ingest](../driver-bacnet-ingest/SKILL.md) — poll → feather
- [bacnet-single-stack](../bacnet-single-stack/SKILL.md) — one UDP 47808 stack
- [ansible-linux-bench-deploy](../ansible-linux-bench-deploy/SKILL.md) — Ansible entry (legacy bench)

## Future: central agent on benserver (not edge)

MCP RAG stays on edge today for doc retrieval. Long-term: a **benserver** agent (OpenClaw / Claude CLI) calls the same bridge APIs (`checkin`, `tuning-brief`, `operational-brief`, portfolio rollup) over Tailscale and feeds the dashboard — no Ollama on edge by default (`enable_ollama: false`).

## Known bugs (check issues before next cycle)

- [#260](https://github.com/bbartling/open-fdd/issues/260) — intermittent GHCR commission push `unknown blob`
- Override `last_scan_at` may lag if MSTP device scan slow — use async `scan-once` (3.0.27+) and poll status hourly
- `acme-zn-t-oob-occupied` may flag high until bounds auto-tune has Arrow sweep analytics
