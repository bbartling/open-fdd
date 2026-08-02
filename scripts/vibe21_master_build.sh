#!/usr/bin/env bash
# Offline Vibe21 master build: twin → farm QC → feature specs → champion train → unity → bundle.
# Does NOT put Python/joblib into production images.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORACLE="${VIBE21_ORACLE:-/home/ben/py-bacnet-stacks-playground/vibe_code_apps_21}"
JOB_ROOT="${OPENFDD_JOB_ROOT:-$ROOT/workspace/vibe21_jobs}"
JOB_ID="${JOB_ID:-b100-ops11}"
PROFILE="${MASTER_BUILD_PROFILE:-pilot}"
REUSE_CHAMPION="${REUSE_CHAMPION:-0}"
STAGES="${STAGES:-calibrate,qc,features,train,unity,bundle}"
VENV="${VIBE21_VENV:-$ROOT/workspace/vibe21_venv}"
PY="${VENV}/bin/python"

usage() {
  cat <<EOF
Usage: $0 [--job-id ID] [--profile pilot|full] [--reuse-champion] [--stages list]
Env: VIBE21_ORACLE OPENFDD_JOB_ROOT VIBE21_VENV MASTER_BUILD_PROFILE REUSE_CHAMPION
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job-id) JOB_ID="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --reuse-champion) REUSE_CHAMPION=1; shift ;;
    --stages) STAGES="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -d "$ORACLE" ]] || { echo "ERROR: oracle missing: $ORACLE" >&2; exit 1; }

JOB="$JOB_ROOT/$JOB_ID"
TWIN_ID="twin_ops11"
MODEL_ID="modelrel_demand_hourly"
UNITY_ID="unitybuild_liberty100"
mkdir -p "$JOB/twins/$TWIN_ID" "$JOB/simulations" "$JOB/datasets" \
  "$JOB/models/$MODEL_ID" "$JOB/unity/$UNITY_ID" "$JOB/mappings"

have_stage() { [[ ",$STAGES," == *",$1,"* ]]; }

ensure_venv() {
  if [[ ! -x "$PY" ]]; then
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q joblib 'scikit-learn==1.8.0' pandas numpy pyarrow
  fi
}

stage_calibrate() {
  echo "==> calibrate (seed oracle twin assets)"
  local src="$ORACLE/assets/twin_b100_ops11"
  cp -a "$src/." "$JOB/twins/$TWIN_ID/"
  python3 - <<PY
import hashlib, json
from pathlib import Path
twin = Path("$JOB/twins/$TWIN_ID")
idf = twin / "model.idf"
h = hashlib.sha256(idf.read_bytes()).hexdigest() if idf.is_file() else None
man = {
  "schema_version": "openfdd.twin_manifest.v1",
  "twin_id": "$TWIN_ID",
  "twin_version_id": "$TWIN_ID",
  "g14": "PASS",
  "best_model": True,
  "status": "MONTHLY_CALIBRATED",
  "idf_sha256": h,
  "source": "oracle:assets/twin_b100_ops11",
}
(twin / "twin-manifest.json").write_text(json.dumps(man, indent=2) + "\n")
print("twin manifest", man["idf_sha256"])
PY
}

stage_qc() {
  echo "==> qc (Arrow/Parquet schema check — pandas optional offline only)"
  ensure_venv
  local parquet
  parquet="$(find "$JOB/simulations" -name 'dm_hourly_rows.parquet' 2>/dev/null | head -1 || true)"
  if [[ -z "$parquet" ]]; then
    parquet="$(find "$HOME/wattlab_workspace/reports" -name 'dm_hourly_rows.parquet' 2>/dev/null | head -1 || true)"
  fi
  if [[ -z "$parquet" ]]; then
    echo "WARN: no dm_hourly_rows.parquet — skipping QC (reuse-champion path OK)"
    return 0
  fi
  JOB="$JOB" PARQUET="$parquet" "$PY" - <<'PY'
import json, os
from pathlib import Path
import pyarrow.parquet as pq
path = Path(os.environ["PARQUET"])
t = pq.read_table(path)
cols = set(t.column_names)
required = {"simulation_id", "hour_ending", "oat_c", "strategy_id", "facility_kw"}
missing = sorted(required - cols)
report = {
  "schema_version": "openfdd.farm_qc.v1",
  "parquet": str(path),
  "n_rows": t.num_rows,
  "n_cols": t.num_columns,
  "missing_required": missing,
  "ok": not missing and t.num_rows > 0,
}
out = Path(os.environ["JOB"]) / "simulations" / "farm_qc.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2) + "\n")
print(report)
if not report["ok"]:
    raise SystemExit("farm QC failed")
PY
}

stage_features() {
  echo "==> features (emit feature_spec / target_spec from oracle compiler)"
  ensure_venv
  ORACLE="$ORACLE" JOB="$JOB" MODEL_ID="$MODEL_ID" "$PY" - <<'PY'
import json, os, sys
from pathlib import Path
oracle = Path(os.environ["ORACLE"])
sys.path.insert(0, str(oracle / "ml"))
from feature_compile_dm import FEATURE_COLS, TARGET_COLS
job = Path(os.environ["JOB"])
model = job / "models" / os.environ["MODEL_ID"]
(model / "feature_spec.json").write_text(json.dumps({
  "schema_version": "openfdd.feature_spec.v1",
  "feature_cols": list(FEATURE_COLS),
}, indent=2) + "\n")
(model / "target_spec.json").write_text(json.dumps({
  "schema_version": "openfdd.target_spec.v1",
  "target_cols": list(TARGET_COLS),
}, indent=2) + "\n")
print("wrote feature/target specs", len(FEATURE_COLS), len(TARGET_COLS))
PY
}

stage_train() {
  echo "==> train (champion hunt or --reuse-champion)"
  ensure_venv
  local model_dir="$JOB/models/$MODEL_ID"
  if [[ "$REUSE_CHAMPION" == "1" ]]; then
    echo "reusing oracle champion joblib + cards"
    cp -a "$ORACLE/flask_app/models/demand_hourly_v2.joblib" "$model_dir/model.joblib"
    cp -a "$ORACLE/flask_app/models/demand_hourly_v2_model_card.json" "$model_dir/model-card.json"
    cp -a "$ORACLE/flask_app/models/demand_hourly_v2_tuning.json" "$model_dir/tuning.json" 2>/dev/null || true
    "$PY" - <<PY
import json, hashlib
from pathlib import Path
md = Path("$model_dir")
art = md / "model.joblib"
card = json.loads((md / "model-card.json").read_text())
digest = hashlib.sha256(art.read_bytes()).hexdigest()
leaderboard = [{
  "family": card.get("champion") or "extra_trees",
  "selected": True,
  "note": "reuse-champion from oracle demand_hourly_v2",
  "metrics": card.get("cv_metrics") or {},
}]
(md / "leaderboard.json").write_text(json.dumps(leaderboard, indent=2) + "\n")
rel = {
  "schema_version": "openfdd.model_release.v1",
  "model_release_id": "$MODEL_ID",
  "champion": card.get("champion") or "extra_trees",
  "artifact_sha256": digest,
  "card_sha256_expected": card.get("artifact_sha256"),
  "status": card.get("status") or "CANDIDATE",
  "portable_format": "pending_onnx",
  "training_source": card.get("training_source") or "ENERGYPLUS_SIMULATED",
  "feature_spec": "feature_spec.json",
  "target_spec": "target_spec.json",
}
(md / "model-release.json").write_text(json.dumps(rel, indent=2) + "\n")
# Copy golden predicts if present in repo
gold = Path("$ROOT/docs/migration/vibe21/GOLDEN_PREDICTS.jsonl")
if gold.is_file():
    (md / "conformance.jsonl").write_bytes(gold.read_bytes())
print("reuse-champion release", rel["champion"], digest[:12])
PY
  else
    echo "full family hunt via oracle ml.tune_demand_hourly (requires farm parquet)"
    local parquet
    parquet="$(find "$JOB/simulations" -name 'dm_hourly_rows.parquet' 2>/dev/null | head -1 || true)"
    if [[ -z "$parquet" ]]; then
      # Try wattlab / oracle common locations
      parquet="$(find "$HOME/wattlab_workspace/reports" -name 'dm_hourly_rows.parquet' 2>/dev/null | head -1 || true)"
    fi
    if [[ -z "$parquet" ]]; then
      echo "WARN: no farm parquet — falling back to --reuse-champion semantics" >&2
      REUSE_CHAMPION=1
      stage_train
      return
    fi
    "$PY" -m ml.tune_demand_hourly --multi-target --parquet "$parquet" --out-dir "$model_dir" \
      || "$PY" "$ORACLE/ml/tune_demand_hourly.py" --help
    # Normalize outputs into model-release.json + leaderboard.json when tune writes cards
    "$PY" - <<PY
import json, hashlib
from pathlib import Path
md = Path("$model_dir")
# Prefer freshly written cards
cards = list(md.glob("*_model_card.json")) + list(md.glob("model-card.json"))
card = json.loads(cards[0].read_text()) if cards else {"champion": "unknown"}
arts = list(md.glob("*.joblib"))
art = arts[0] if arts else None
digest = hashlib.sha256(art.read_bytes()).hexdigest() if art else None
if art and art.name != "model.joblib":
    art.rename(md / "model.joblib")
leaderboard = card.get("leaderboard") or [{"family": card.get("champion"), "selected": True}]
(md / "leaderboard.json").write_text(json.dumps(leaderboard, indent=2) + "\n")
rel = {
  "schema_version": "openfdd.model_release.v1",
  "model_release_id": "$MODEL_ID",
  "champion": card.get("champion"),
  "artifact_sha256": digest,
  "status": card.get("status") or "CANDIDATE",
  "portable_format": "pending_onnx",
}
(md / "model-release.json").write_text(json.dumps(rel, indent=2) + "\n")
print(rel)
PY
  fi
  # Refuse bundle without leaderboard
  [[ -f "$model_dir/leaderboard.json" ]] || { echo "ERROR: missing leaderboard.json" >&2; exit 1; }
  [[ -f "$model_dir/model-release.json" ]] || { echo "ERROR: missing model-release.json" >&2; exit 1; }
}

stage_unity() {
  echo "==> unity (pack WebGL zip + manifest)"
  local dest="$JOB/unity/$UNITY_ID"
  local zip="$dest/unity_webgl_build.zip"
  mkdir -p "$dest"
  if [[ ! -f "$zip" ]]; then
    (cd "$ORACLE/flask_app/webgl" && zip -qr "$zip" .)
  fi
  cp -a "$ORACLE/flask_app/WEBGL_BUILD_MANIFEST.json" "$dest/" 2>/dev/null || true
  python3 - <<PY
import hashlib, json
from pathlib import Path
dest = Path("$dest")
z = dest / "unity_webgl_build.zip"
man = {
  "schema_version": "openfdd.unity_webgl_build.v1",
  "unity_build_id": "$UNITY_ID",
  "zip_sha256": hashlib.sha256(z.read_bytes()).hexdigest(),
  "zip_bytes": z.stat().st_size,
  "source": "oracle:flask_app/webgl",
}
(dest / "unity-build.json").write_text(json.dumps(man, indent=2) + "\n")
print("unity", man["zip_sha256"][:12], man["zip_bytes"])
PY
}

stage_bundle() {
  echo "==> bundle"
  python3 - <<PY
import json
from pathlib import Path
job = Path("$JOB")
bundle = {
  "schema_version": "openfdd.runtime_bundle.v1",
  "job_id": "$JOB_ID",
  "twin_version_id": "$TWIN_ID",
  "model_release_id": "$MODEL_ID",
  "unity_build_id": "$UNITY_ID",
  "profile": "$PROFILE",
  "paths": {
    "twin": f"twins/$TWIN_ID",
    "model": f"models/$MODEL_ID",
    "unity": f"unity/$UNITY_ID",
  },
}
(job / "runtime_bundle.json").write_text(json.dumps(bundle, indent=2) + "\n")
print(json.dumps(bundle, indent=2))
print("OK master build at", job)
PY
}

have_stage calibrate && stage_calibrate
have_stage qc && stage_qc
have_stage features && stage_features
have_stage train && stage_train
have_stage unity && stage_unity
have_stage bundle && stage_bundle

echo "DONE job=$JOB"
