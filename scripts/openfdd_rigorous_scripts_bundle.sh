#!/usr/bin/env bash
# Pack sanitized rigorous validation scripts for backup (Google Drive, git-style allowlist).
#
# SANITIZATION: copies ONLY explicit paths below — never whole workspace/ or scripts/.
# Excludes secrets, logs, data, .venv (same intent as .gitignore at repo root).
#
#   cd /home/ben/open-fdd
#   ./scripts/openfdd_rigorous_scripts_bundle.sh
#
# Output:
#   workspace/backups/open-fdd-rigorous-scripts_<UTC>.tar.gz
#   workspace/backups/open-fdd-rigorous-scripts_<UTC>.manifest.txt
#   workspace/backups/open-fdd-rigorous-scripts_<UTC>.sanitize.txt
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$ROOT/workspace/backups"
ARCHIVE="$OUT_DIR/open-fdd-rigorous-scripts_${TS}.tar.gz"
MANIFEST="$OUT_DIR/open-fdd-rigorous-scripts_${TS}.manifest.txt"
SANITIZE_LOG="$OUT_DIR/open-fdd-rigorous-scripts_${TS}.sanitize.txt"
STAGE="$OUT_DIR/.rigorous_scripts_stage_${TS}"

# Paths that must NEVER appear in the archive (gitignore-equivalent blocklist).
NEVER_INCLUDE=(
  "workspace/auth.env.local"
  "workspace/data.env.local"
  "workspace/bootstrap_credentials.once.txt"
  "workspace/bench/bench_profile.toml"
  "workspace/data"
  "workspace/logs"
  "tests/selenium/.venv"
  ".env"
)

mkdir -p "$OUT_DIR" "$STAGE/open-fdd"

{
  echo "# Open-FDD rigorous scripts backup — sanitization log"
  echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# Method: explicit allowlist only (not a directory tree copy)"
  echo
  echo "## Excluded by design (same as .gitignore intent)"
  for x in "${NEVER_INCLUDE[@]}"; do
    echo "  - $x"
  done
  echo
  echo "## Files included"
} >"$SANITIZE_LOG"

copy() {
  local src="$1"
  local rel="$2"
  local dest="$STAGE/open-fdd/$rel"

  for blocked in "${NEVER_INCLUDE[@]}"; do
    if [[ "$rel" == "$blocked" || "$rel" == "$blocked/"* ]]; then
      echo "BLOCKED (never include): $rel" >>"$SANITIZE_LOG"
      echo "ERROR: refuse to pack blocked path: $rel" >&2
      exit 1
    fi
  done

  if [[ ! -e "$src" ]]; then
    echo "# MISSING: $rel" >>"$SANITIZE_LOG"
    echo "# MISSING: $rel" >&2
    return 1
  fi

  mkdir -p "$(dirname "$dest")"
  cp -a "$src" "$dest"
  echo "  + $rel" >>"$SANITIZE_LOG"
  echo "$rel"
}

{
  echo "# Open-FDD rigorous validation scripts backup"
  echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# Sanitized: allowlist only — see .sanitize.txt"
  echo "# Archive: $ARCHIVE"
  echo
} >"$MANIFEST"

add() {
  local path
  path=$(copy "$ROOT/$1" "$1") || return 0
  echo "$path" >>"$MANIFEST"
}

# --- Master orchestrators ---
add scripts/openfdd_rev325_rigorous_report.sh
add scripts/openfdd_rigorous_full_run.sh
add scripts/openfdd_patch_cycle_validate.sh
add scripts/openfdd_rigorous_scripts_bundle.sh

# --- Phase scripts ---
for s in \
  openfdd_drivers_validate.sh \
  openfdd_drivers_rigorous_validate.sh \
  openfdd_polling_feather_validate.sh \
  openfdd_api_semantic_eval.sh \
  openfdd_auth_rbac_validate.sh \
  openfdd_mcp_eval.sh \
  openfdd_bacnet_poll_daemon.sh \
  openfdd_driver_poll_1m.sh \
  openfdd_hour_driver_fault_test.sh \
  openfdd_stores_fdd_soak.sh \
  openfdd_soak_pcap_zap_finalize.sh \
  openfdd_ot_pcap_capture.sh \
  openfdd_ot_pcap_analyze.sh \
  openfdd_pcap_minute_validate.sh \
  openfdd_zap_scan.sh \
  openfdd_zap_caddy_matrix.sh \
  openfdd_caddy_test_recipe.sh \
  openfdd_caddy_validate.sh \
  openfdd_docker_health_audit.sh \
  openfdd_bench_consolidated_report.sh \
  openfdd_test_failure_triage.sh \
  openfdd_env_bootstrap_validate.sh \
  openfdd_readme_agent_prompts_validate.sh \
  openfdd_bench_cleanup.sh \
  openfdd_bench_pull_latest.sh \
  openfdd_bench_safe_restart.sh \
  openfdd_rust_site_update.sh \
  openfdd_rust_site_lib.sh \
  openfdd_rust_site_backup.sh \
  openfdd_rust_site_restore.sh \
  openfdd_post_update_data_recovery.sh \
  openfdd_rust_historian_staging.sh \
  openfdd_rust_edge_validate.sh \
  openfdd_rust_check_ghcr_platform.sh \
  openfdd_gh_scope_fetch.sh \
  openfdd_gh_scope_lib.sh; do
  add "scripts/$s"
done

# --- Shared libraries ---
add scripts/openfdd_bench_lib.sh
add scripts/openfdd_auth_lib.sh
add scripts/openfdd_auth_init.sh
add scripts/VERSION

# --- Selenium (source only — no .venv) ---
for f in \
  openfdd_frontend_rigorous.sh \
  openfdd_rigorous_frontend.py \
  openfdd_agent_bootstrap.py \
  openfdd_ui_selenium.py \
  openfdd_tls_bootstrap.py \
  openfdd_test_lib.py \
  openfdd_selenium_up.sh \
  requirements.txt; do
  add "tests/selenium/$f"
done
add tests/selenium/.gitignore

# --- Bench template + docs (never bench_profile.toml or reports with secrets) ---
add workspace/bench/bench_profile.toml.example
add workspace/BENCH_VS_SOURCE.md
add docs/verification/RIGOROUS_BENCH_SCRIPTS.md
add workspace/reports/REV_326_RIGOROUS_TEST_REPORT.md
add workspace/reports/README.md
add .gitignore
add docker-compose.yml
add docker-compose.override.yml

tar -czf "$ARCHIVE" -C "$STAGE" open-fdd
rm -rf "$STAGE"

# Post-pack scan: flag embedded secret *values*, not path names in comments/docs
SCAN_HITS=0
scan_text_file() {
  local entry="$1"
  local body
  body=$(tar -xOzf "$ARCHIVE" "$entry" 2>/dev/null) || return 0

  # Literal password/secret assignments (skip env var refs like ${VAR} and placeholders)
  if printf '%s' "$body" | grep -qE '(^|[^A-Z_])OPENFDD_[A-Z_]*(PASSWORD|SECRET|TOKEN)=[^$"'\''{[:space:]#][^[:space:]#]{7,}'; then
    echo "WARN literal OPENFDD_* password/secret assignment in: $entry" >>"$SANITIZE_LOG"
    SCAN_HITS=$((SCAN_HITS + 1))
  fi
  # JWT bearer tokens (three base64 segments)
  if printf '%s' "$body" | grep -qE 'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'; then
    echo "WARN JWT-like token in: $entry" >>"$SANITIZE_LOG"
    SCAN_HITS=$((SCAN_HITS + 1))
  fi
  # bootstrap credential file contents (username/password pairs from once-file)
  if printf '%s' "$body" | grep -qE '^[a-z_]+=.+$' && printf '%s' "$entry" | grep -q 'bootstrap_credentials'; then
    echo "WARN bootstrap credential content in: $entry" >>"$SANITIZE_LOG"
    SCAN_HITS=$((SCAN_HITS + 1))
  fi
}

while IFS= read -r entry; do
  case "$entry" in
    *.sh|*.py|*.toml|*.yml|*.example)
      scan_text_file "$entry"
      ;;
  esac
done < <(tar -tzf "$ARCHIVE" | grep -v '/$')

{
  echo
  echo "## Post-pack scan"
  if [[ "$SCAN_HITS" -eq 0 ]]; then
    echo "  PASS — no obvious secret patterns in text files"
  else
    echo "  WARN — $SCAN_HITS file(s) matched secret-like patterns (review before upload)"
  fi
  echo
  echo "## Archive"
  echo "  $ARCHIVE"
  echo "  $(du -h "$ARCHIVE" | awk '{print $1}')"
} >>"$SANITIZE_LOG"

echo
echo "Sanitized backup ready:"
echo "  Archive:   $ARCHIVE"
echo "  Manifest:  $MANIFEST"
echo "  Sanitize:  $SANITIZE_LOG"
echo "  Size:      $(du -h "$ARCHIVE" | awk '{print $1}')"
echo
echo "Included: scripts + tests/selenium source + docs + docker-compose + .example configs"
echo "Excluded:  workspace/data, logs, auth.env.local, data.env.local, .venv, .env"
echo
if [[ "$SCAN_HITS" -gt 0 ]]; then
  echo "Review $SANITIZE_LOG before uploading to Google Drive."
  exit 1
fi
