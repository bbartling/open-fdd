#!/usr/bin/env bash
# Wave N — host-side commit + push + PR (uses your keyring gh).
# Run: ./scripts/ops/wave_n_push_pr_host.sh
# Does NOT enable Railway MT (that waits for GHCR sha after merge).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

gh auth status
git status -sb
git branch --show-current | grep -q 'feature/wave-n-mt-security' \
  || { echo "expected branch feature/wave-n-mt-security"; exit 1; }

# Use last commit author for this repo only — do NOT write git config.
AUTHOR_NAME="$(git log -1 --format='%an' 2>/dev/null || true)"
AUTHOR_EMAIL="$(git log -1 --format='%ae' 2>/dev/null || true)"
if [[ -z "$AUTHOR_NAME" || -z "$AUTHOR_EMAIL" ]]; then
  AUTHOR_NAME="${GIT_AUTHOR_NAME:-Ben Bartling}"
  AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-ben.bartling@gmail.com}"
fi
export GIT_AUTHOR_NAME="$AUTHOR_NAME" GIT_AUTHOR_EMAIL="$AUTHOR_EMAIL"
export GIT_COMMITTER_NAME="$AUTHOR_NAME" GIT_COMMITTER_EMAIL="$AUTHOR_EMAIL"

# Stage product + docs (never .secrets, never workspace/exports ACME private)
git add \
  AGENTS.md VERSION Cargo.toml Cargo.lock \
  crates/openfdd_contracts/Cargo.toml crates/openfdd_mqtt/Cargo.toml edge/Cargo.toml \
  services/central services/fieldbus \
  docs/architecture/ADR_stage_c_idp_mfa_sku.md \
  docs/operations/BACNET_OT_POLICY.md \
  docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md \
  docs/operations/BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md \
  docs/operations/WAVE_M_LAB_MULTI_TENANT_CHECKLIST.md \
  docs/operations/WAVE_N_CONTROL_PLANE_EXAMPLE.md \
  docs/operations/WAVE_N_METRIC_FDD.md \
  docs/operations/FIELDBUS_EDGE_MQTTS_HUB.md \
  docs/operations/ECM_ENGINEERING_MATH.md \
  docs/operations/github-pages.md \
  docs/_includes/head_custom.html \
  docs/mcp-agents/agent-skills-ecm-bacnet.md \
  scripts/nightly-ot-bench/22_wave_l_tenant_mode.sh \
  scripts/nightly-ot-bench/31_wave_n_tenant_acl.sh \
  scripts/nightly-ot-bench/32_wave_n_mqtts_continuity.sh \
  scripts/nightly-ot-bench/run_railway_hub_stress.sh \
  scripts/qualification/README.md \
  scripts/qualification/run_isolated_zap_af.sh \
  scripts/ops/wave_n_auth_validate_host.sh \
  scripts/ops/wave_n_agent_bridge_tokens.sh \
  scripts/ops/wave_n_push_pr_host.sh

git status -sb
git commit -m "$(cat <<'EOF'
Wave N: multi-tenant users, fixed 300s fieldbus, ACL/continuity stress

Ship per-tenant control-plane logins, harden security audit events, lock
fieldbus poll/publish at 300s for OT/MS/TP safety, and add Railway hub
gates for ACME↔B100↔lakeside_sd isolation plus MQTTS continuity.
EOF
)"

git push -u origin HEAD

gh pr create --title "Wave N: MT users + fixed 300s fieldbus + ACL/continuity stress" --body "$(cat <<'EOF'
## Summary
- Per-tenant `users.json` password logins mint JWT `tenant_ids`; hub admin stays empty membership
- Fieldbus poll/MQTT publish hard-coded to **300 s** (no adjustable burst)
- Audit events for tenant select/deny, ingest reject, package import; filter `/api/tenants` list
- Hub stress gates 20 (ACL) + 21 (MQTTS continuity); ZAP AF can seed MT-ON disposable volume
- Docs: Wave N bug report, OT never-cloud policy, ECM MathJax, control-plane examples

## Test plan
- [ ] `cargo test -p openfdd-central user_store`
- [ ] `cargo test -p openfdd-fieldbus poll_interval`
- [ ] Disposable ZAP AF with `OPENFDD_MULTI_TENANT=1`
- [ ] After GHCR: Railway backup → tenants/users → `OPENFDD_MULTI_TENANT=1` → ACL + continuity gates
- [ ] ACME fieldbus refresh (private) → ingest_ok advances

EOF
)"

echo "PR URL above — wait for GHCR Publish then run Railway MT enable"
