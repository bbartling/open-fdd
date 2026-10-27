//! Wave-X Timescale registry API — no DataFusion SessionContext.
//! Registry-backed FDD API - loads `sql_rules/registry.yaml` via `fdd_rules`.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use fdd_rules::{load_registry, RuleRegistry, RuleSpec};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

fn sql_rules_dir() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_SQL_RULES_DIR") {
        return PathBuf::from(p);
    }
    for c in [
        PathBuf::from("sql_rules"),
        PathBuf::from("/app/sql_rules"),
        PathBuf::from("../sql_rules"),
    ] {
        if c.join("registry.yaml").is_file() {
            return c;
        }
    }
    PathBuf::from("sql_rules")
}

pub(crate) fn parquet_root() -> PathBuf {
    // Match CSV ingest + historian: OPENFDD_STORAGE_URL file root first (#528).
    if let Some(p) = fdd_store::local_file_root_from_env() {
        return p;
    }
    if let Ok(p) = std::env::var("OPENFDD_PARQUET_ROOT") {
        return PathBuf::from(p);
    }
    // Prefer workspace-relative cache so CSV ingest and /api/fdd/run agree when
    // only OPENFDD_WORKSPACE is set (standalone recipe parity with csv recipe).
    if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE") {
        let under_ws = PathBuf::from(&ws).join(".cache/parquet");
        if under_ws.is_dir() || PathBuf::from(&ws).is_dir() {
            return under_ws;
        }
    }
    for c in [
        PathBuf::from(".cache/parquet"),
        PathBuf::from("/var/openfdd/workspace/.cache/parquet"),
        PathBuf::from("workspace/.cache/parquet"),
    ] {
        if c.is_dir() {
            return c;
        }
    }
    PathBuf::from(".cache/parquet")
}

fn preferred_tenant_from_env() -> Option<String> {
    std::env::var("OPENFDD_TENANT_ID")
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

/// Storage root for a building-scoped FDD/analytics read (tenant partition or hub).
fn storage_root_for_building(pq: &Path, bid: &str, preferred_tenant: Option<&str>) -> PathBuf {
    fdd_store::resolve_building_read_root(pq, preferred_tenant, bid)
        .map(|r| r.root)
        .unwrap_or_else(|_| pq.to_path_buf())
}

fn collect_equipment_prefix(root: &Path, prefix: &str, ids: &mut Vec<String>) {
    if !root.is_dir() {
        return;
    }
    for entry in walkdir::WalkDir::new(root)
        .min_depth(1)
        .max_depth(4)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|e| e.file_type().is_dir())
    {
        if let Some(id) = entry
            .file_name()
            .to_str()
            .and_then(|name| name.strip_prefix(prefix))
        {
            if !id.is_empty() {
                ids.push(id.to_string());
            }
        }
    }
}

/// Wave M D2 - authoritative rule results live under parquet/workspace volume
/// by default (not WORKDIR `.cache`). Override with `OPENFDD_RULE_RESULTS_DIR`.
fn rule_results_base() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_RULE_RESULTS_DIR") {
        let trimmed = p.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    if let Ok(root) = std::env::var("OPENFDD_PARQUET_ROOT") {
        let trimmed = root.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed).join("rule_results");
        }
    }
    if let Ok(url) = std::env::var("OPENFDD_STORAGE_URL") {
        if let Some(path) = url.strip_prefix("file://") {
            let trimmed = path.trim();
            if !trimmed.is_empty() {
                return PathBuf::from(trimmed).join("rule_results");
            }
        }
    }
    if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE") {
        let trimmed = ws.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed).join("openfdd").join("rule_results");
        }
    }
    // Local/dev fallback only - central readiness fails this path in prod.
    PathBuf::from(".cache/rule_results")
}

/// Results directory, optionally scoped to a building so per-site runs do not
/// overwrite each other. `None` -> `<base>`; `Some(id)` -> `<base>/building={id}/`.
fn results_dir(building_id: Option<&str>) -> PathBuf {
    let base = rule_results_base();
    match building_id.map(str::trim).filter(|s| !s.is_empty()) {
        Some(bid) => base.join(format!("building={bid}")),
        None => base,
    }
}

const DIRTY_FILE: &str = "_dirty.json";
const ACTIVE_FILE: &str = "_active.json";
const MANIFEST_NAME: &str = "manifest.json";
const GENERATIONS_DIR: &str = "generations";
const MANIFEST_SCHEMA: &str = "openfdd-fdd-run-manifest-v1";

static RUN_SEQ: AtomicU64 = AtomicU64::new(1);

/// Mark a building's FDD results dirty so Overview re-enables Run all rules.
pub fn mark_building_results_dirty(building_id: &str, reason: &str) {
    let bid = building_id.trim();
    if bid.is_empty() {
        return;
    }
    let dir = results_dir(Some(bid));
    let _ = std::fs::create_dir_all(&dir);
    let body = json!({
        "dirty": true,
        "reason": reason,
        "at": chrono::Utc::now().to_rfc3339(),
    });
    let path = dir.join(DIRTY_FILE);
    let _ = std::fs::write(path, body.to_string());
}

/// Directory whose `registry.yaml` is the rule set a Timescale run actually executes.
///
/// The lab catalog may still load `sql_rules`. The manifest hash follows the
/// product pack (`sql/fdd`, or `OPENFDD_SQL_ROOT` when set) so a catalog-only
/// file cannot mark a finished run stale.
fn manifest_registry_dir() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_SQL_ROOT") {
        let path = PathBuf::from(p.trim());
        if path.join("registry.yaml").is_file() {
            return path;
        }
    }
    if let Ok(p) = std::env::var("OPENFDD_SQL_RULES_DIR") {
        let path = PathBuf::from(p.trim());
        if path.join("registry.yaml").is_file() {
            return path;
        }
    }
    for candidate in [
        "sql/fdd",
        "/app/sql/fdd",
        "../sql/fdd",
        "../../sql/fdd",
        "sql_rules",
        "/app/sql_rules",
        "../sql_rules",
    ] {
        let path = PathBuf::from(candidate);
        if path.join("registry.yaml").is_file() {
            return path;
        }
    }
    sql_rules_dir()
}

pub fn rule_set_hash_for_readiness() -> String {
    rule_set_hash()
}

fn rule_set_hash() -> String {
    let mut ids: Vec<String> = load_registry(&manifest_registry_dir())
        .map(|reg| reg.rules.into_iter().map(|rule| rule.rule_id).collect())
        .unwrap_or_default();
    ids.sort();
    let mut hasher = Sha256::new();
    hasher.update(ids.join("|").as_bytes());
    format!("{:x}", hasher.finalize())
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

pub fn new_run_id() -> String {
    let seq = RUN_SEQ.fetch_add(1, Ordering::Relaxed);
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_nanos())
        .unwrap_or(0);
    format!("run-{nanos:x}-{seq:x}")
}

fn safe_run_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 80
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

fn safe_rule_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 80
        && !id.starts_with('_')
        && !id.starts_with('.')
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

fn read_json_file(path: &Path) -> Option<Value> {
    let text = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

fn row_status_token(row: &Value) -> String {
    row.get("status")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_ascii_uppercase()
}

fn row_equipment_id(row: &Value) -> Option<&str> {
    row.get("equipment_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|id| !id.is_empty())
}

const METRIC_FIELDS: [&str; 4] = [
    "avg_zone_temp",
    "comfort_pct",
    "fan_runtime_hours",
    "total_hours",
];

fn object_has_metric_field(obj: &serde_json::Map<String, Value>) -> bool {
    METRIC_FIELDS.iter().any(|key| obj.contains_key(*key))
}

fn is_metric_row(row: &Value) -> bool {
    if row.get("output_kind").and_then(Value::as_str) == Some("metric") {
        return true;
    }
    if row_status_token(row) == "METRIC" || row.get("metric").is_some() {
        return true;
    }
    if row.as_object().is_some_and(object_has_metric_field) {
        return true;
    }
    row.get("values")
        .and_then(Value::as_object)
        .is_some_and(object_has_metric_field)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuleOutcome {
    Succeeded,
    Skipped,
    Failed,
}

/// Runtime `ERROR` and `SCHEMA_INCOMPATIBLE` are failures.
/// `SKIP_*` rows (missing input, unsupported capability, short history,
/// no targets) are not failures. A detected `FAULT` or a `METRIC` row is an
/// evaluation, not an error.
fn rule_outcome(rows: &[Value]) -> RuleOutcome {
    if rows.is_empty() {
        return RuleOutcome::Skipped;
    }
    let mut error = false;
    let mut evaluated = false;
    for row in rows {
        let status = row_status_token(row);
        if status == "ERROR" || status == "SCHEMA_INCOMPATIBLE" || status == "RUNTIME_FAILURE" {
            error = true;
        } else if status.starts_with("SKIP") {
            continue;
        } else if is_metric_row(row)
            || status.is_empty()
            || status == "PASS"
            || status == "FAULT"
            || status == "METRIC"
            || !status.contains("NOT_APPLICABLE")
        {
            evaluated = true;
        }
    }
    if error {
        RuleOutcome::Failed
    } else if evaluated {
        RuleOutcome::Succeeded
    } else {
        RuleOutcome::Skipped
    }
}

fn run_status_label(succeeded: u32, failed: u32) -> &'static str {
    if failed == 0 {
        "complete"
    } else if succeeded > 0 {
        "partial"
    } else {
        "failed"
    }
}

fn retain_model_rows(body: &mut Value, model: &BTreeSet<String>) {
    let Some(rows) = body.get_mut("rows").and_then(Value::as_array_mut) else {
        return;
    };
    rows.retain(|row| match row_equipment_id(row) {
        None => true,
        Some(id) => model.contains(id),
    });
}

fn merge_scoped_rows(parent: &Value, fresh: &Value) -> Vec<Value> {
    let fresh_rows = fresh.get("rows").and_then(Value::as_array);
    let replace_rule = fresh_rows.is_some_and(|rows| {
        rows.iter().any(|row| {
            let status = row_status_token(row);
            status == "SKIP_NO_TARGETS"
                || status == "SCHEMA_INCOMPATIBLE"
                || ((status == "ERROR" || status == "RUNTIME_FAILURE")
                    && row_equipment_id(row).is_none())
        })
    });
    if replace_rule {
        return fresh_rows.cloned().unwrap_or_default();
    }
    let replaced: BTreeSet<String> = fresh_rows
        .into_iter()
        .flatten()
        .filter_map(row_equipment_id)
        .map(str::to_string)
        .collect();
    let mut rows: Vec<Value> = parent
        .get("rows")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|row| match row_equipment_id(row) {
            Some(id) => !replaced.contains(id),
            None => false,
        })
        .cloned()
        .collect();
    if let Some(fresh_rows) = fresh_rows {
        rows.extend(fresh_rows.iter().cloned());
    }
    rows
}

fn sync_file(path: &Path) -> Result<(), String> {
    let file = std::fs::File::open(path).map_err(|err| err.to_string())?;
    file.sync_all().map_err(|err| err.to_string())
}

fn write_json_file(path: &Path, body: &Value) -> Result<(), String> {
    let bytes = serde_json::to_vec_pretty(body).map_err(|err| err.to_string())?;
    std::fs::write(path, bytes).map_err(|err| err.to_string())?;
    sync_file(path)
}

/// One rule file inside a run generation. `body.rows` is the persisted cohort.
pub struct RunRuleFile {
    pub rule_id: String,
    pub body: Value,
}

/// Equipment stamp captured with the run. Absence from this list drops a row
/// from the active generation.
pub struct RunModelEquipment {
    pub equipment_id: String,
    pub equip_type: Option<String>,
}

/// Immutable generation to publish. `full_cohort` replaces the active rule
/// set. A scoped run keeps the parent generation's other rules and records
/// `parent_run_id`.
pub struct RunGenerationCommit {
    pub building_id: String,
    pub full_cohort: bool,
    pub equipment: Vec<RunModelEquipment>,
    pub rules: Vec<RunRuleFile>,
    pub config_fingerprint: String,
    pub window_start: Option<String>,
    pub window_end: Option<String>,
    pub watermark: Option<String>,
    pub poll_seconds: f64,
    /// Pack contract recorded on this generation. One manifest per run.
    pub pack: Value,
}

#[derive(Debug, Clone)]
pub struct PreparedRule {
    pub rule_id: String,
    pub body: Value,
    pub outcome: RuleOutcome,
}

/// In-memory generation before persistence (Timescale or manifest files).
#[derive(Debug, Clone)]
pub struct RunGenerationPrepared {
    pub run_id: String,
    pub parent_run_id: Option<String>,
    pub cohort: String,
    pub prepared: Vec<PreparedRule>,
    pub manifest: Value,
    pub flat_results: Vec<Value>,
    pub dirty_reason: Option<String>,
}

fn model_set(equipment: &[RunModelEquipment]) -> BTreeSet<String> {
    equipment
        .iter()
        .map(|item| item.equipment_id.trim().to_string())
        .filter(|id| !id.is_empty())
        .collect()
}

fn model_hash(equipment: &[RunModelEquipment]) -> String {
    let mut lines: Vec<String> = equipment
        .iter()
        .filter(|item| !item.equipment_id.trim().is_empty())
        .map(|item| {
            format!(
                "{}\t{}",
                item.equipment_id.trim(),
                item.equip_type.as_deref().unwrap_or("").trim()
            )
        })
        .collect();
    lines.sort();
    sha256_hex(lines.join("\n").as_bytes())
}

fn model_json(equipment: &[RunModelEquipment], hash: &str) -> Value {
    let mut rows: Vec<Value> = equipment
        .iter()
        .filter(|item| !item.equipment_id.trim().is_empty())
        .map(|item| {
            json!({
                "equipment_id": item.equipment_id.trim(),
                "equip_type": item.equip_type.as_deref().map(str::trim).filter(|s| !s.is_empty()),
            })
        })
        .collect();
    rows.sort_by(|left, right| {
        left["equipment_id"]
            .as_str()
            .unwrap_or("")
            .cmp(right["equipment_id"].as_str().unwrap_or(""))
    });
    json!({
        "equipment": rows,
        "model_hash": hash,
    })
}

fn parent_rule_body(gen: &Path, rule_id: &str) -> Option<Value> {
    if !safe_rule_id(rule_id) {
        return None;
    }
    read_json_file(&gen.join(format!("{rule_id}.json")))
}

fn prepare_rule_file(
    rule_id: &str,
    fresh: &Value,
    parent: Option<&Value>,
    full_cohort: bool,
    model: &BTreeSet<String>,
    run_id: &str,
    building_id: &str,
) -> Result<PreparedRule, String> {
    if !safe_rule_id(rule_id) {
        return Err("unsafe rule id".into());
    }
    let mut body = fresh.clone();
    if !full_cohort {
        if let Some(parent) = parent {
            let rows = merge_scoped_rows(parent, fresh);
            if let Some(obj) = body.as_object_mut() {
                obj.insert("rows".into(), Value::Array(rows));
            }
        }
    }
    retain_model_rows(&mut body, model);
    let rows = body
        .get("rows")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let outcome = rule_outcome(&rows);
    if let Some(obj) = body.as_object_mut() {
        obj.insert("rule_id".into(), json!(rule_id));
        obj.insert("run_id".into(), json!(run_id));
        obj.insert("building_id".into(), json!(building_id));
        obj.insert(
            "generated_at".into(),
            json!(chrono::Utc::now().to_rfc3339()),
        );
        obj.insert("rows".into(), Value::Array(rows));
    }
    Ok(PreparedRule {
        rule_id: rule_id.to_string(),
        body,
        outcome,
    })
}

fn parent_body_from_rows(rule_id: &str, rows: &[(String, Value)]) -> Option<Value> {
    let rule_rows: Vec<Value> = rows
        .iter()
        .filter(|(id, _)| id == rule_id)
        .map(|(_, row)| row.clone())
        .collect();
    if rule_rows.is_empty() {
        return None;
    }
    Some(json!({
        "rule_id": rule_id,
        "rows": rule_rows,
    }))
}

/// Build one run generation in memory (manifest + flat rows). Does not write disk.
pub fn prepare_run_generation(
    commit: &RunGenerationCommit,
) -> Result<RunGenerationPrepared, String> {
    prepare_run_generation_with_parent(commit, None, &[])
}

/// Same as [`prepare_run_generation`], but the parent generation may come from
/// Timescale (`parent_manifest` + `parent_rows`) instead of on-disk manifests.
pub fn prepare_run_generation_with_parent(
    commit: &RunGenerationCommit,
    parent_manifest: Option<&Value>,
    parent_rows: &[(String, Value)],
) -> Result<RunGenerationPrepared, String> {
    let building_id = commit.building_id.trim();
    if building_id.is_empty() {
        return Err("building_id required".into());
    }
    let parent_files = if commit.full_cohort {
        None
    } else {
        active_manifest(Some(building_id))
    };
    let parent_run_id = parent_manifest
        .and_then(|m| m.get("run_id").and_then(Value::as_str))
        .map(str::to_string)
        .or_else(|| {
            parent_files
                .as_ref()
                .and_then(|(_, manifest)| manifest.get("run_id").and_then(Value::as_str))
                .map(str::to_string)
        });
    let cohort = if commit.full_cohort {
        "full".to_string()
    } else if parent_run_id.is_some() {
        "derived".to_string()
    } else {
        "scoped".to_string()
    };
    let run_id = new_run_id();
    let model = model_set(&commit.equipment);
    let mut prepared: Vec<PreparedRule> = Vec::new();
    let mut seen = BTreeSet::new();
    for rule in &commit.rules {
        let parent_body = parent_body_from_rows(&rule.rule_id, parent_rows).or_else(|| {
            parent_files
                .as_ref()
                .and_then(|(parent_gen, _)| parent_rule_body(parent_gen, &rule.rule_id))
        });
        let item = prepare_rule_file(
            &rule.rule_id,
            &rule.body,
            parent_body.as_ref(),
            commit.full_cohort,
            &model,
            &run_id,
            building_id,
        )?;
        seen.insert(item.rule_id.clone());
        prepared.push(item);
    }
    let parent_rule_list = parent_manifest
        .and_then(|m| m.get("rules").and_then(Value::as_array))
        .or_else(|| {
            parent_files
                .as_ref()
                .and_then(|(_, m)| m.get("rules").and_then(Value::as_array))
        });
    if let Some(rules) = parent_rule_list {
        for rule in rules {
            let Some(rule_id) = rule.as_str() else {
                continue;
            };
            if seen.contains(rule_id) || !safe_rule_id(rule_id) {
                continue;
            }
            let parent_body = parent_body_from_rows(rule_id, parent_rows).or_else(|| {
                parent_files
                    .as_ref()
                    .and_then(|(parent_gen, _)| parent_rule_body(parent_gen, rule_id))
            });
            let Some(parent_body) = parent_body else {
                continue;
            };
            let item = prepare_rule_file(
                rule_id,
                &parent_body,
                None,
                true,
                &model,
                &run_id,
                building_id,
            )?;
            seen.insert(item.rule_id.clone());
            prepared.push(item);
        }
    }
    prepared.sort_by(|left, right| left.rule_id.cmp(&right.rule_id));
    let mut rules_succeeded = 0u32;
    let mut rules_failed = 0u32;
    let mut rules_skipped = 0u32;
    let mut result_count = 0usize;
    let mut flat_results = Vec::new();
    for item in &prepared {
        match item.outcome {
            RuleOutcome::Succeeded => rules_succeeded += 1,
            RuleOutcome::Failed => rules_failed += 1,
            RuleOutcome::Skipped => rules_skipped += 1,
        }
        if let Some(rows) = item.body.get("rows").and_then(Value::as_array) {
            result_count += rows.len();
            for row in rows {
                let mut cloned = row.clone();
                if let Some(obj) = cloned.as_object_mut() {
                    obj.insert("rule_id".into(), json!(item.rule_id));
                }
                flat_results.push(cloned);
            }
        }
    }
    let run_status = run_status_label(rules_succeeded, rules_failed);
    let hash = model_hash(&commit.equipment);
    let rule_ids: Vec<&str> = prepared.iter().map(|item| item.rule_id.as_str()).collect();
    let manifest = json!({
        "schema": MANIFEST_SCHEMA,
        "run_id": run_id,
        "building_id": building_id,
        "parent_run_id": parent_run_id,
        "cohort": cohort,
        "mode": if commit.full_cohort { "registry" } else { "single_rule" },
        "run_status": run_status,
        "ok": true,
        "model": model_json(&commit.equipment, &hash),
        "rules": rule_ids,
        "config_hash": sha256_hex(commit.config_fingerprint.as_bytes()),
        "rule_set_hash": rule_set_hash(),
        "window": {
            "start": commit.window_start,
            "end": commit.window_end,
        },
        "watermark": commit.watermark,
        "poll_seconds": commit.poll_seconds,
        "pack": commit.pack,
        "completed_at": chrono::Utc::now().to_rfc3339(),
        "result_count": result_count,
        "rules_run": prepared.len(),
        "rules_succeeded": rules_succeeded,
        "rules_failed": rules_failed,
        "rules_skipped": rules_skipped,
    });
    let dirty_reason = if run_status == "complete" && cohort != "scoped" {
        None
    } else if run_status == "partial" {
        Some("run_partial".into())
    } else if run_status == "failed" {
        Some("run_failed".into())
    } else {
        Some("scoped_run".into())
    };
    Ok(RunGenerationPrepared {
        run_id,
        parent_run_id,
        cohort,
        prepared,
        manifest,
        flat_results,
        dirty_reason,
    })
}

/// Write one immutable generation to disk, then switch `_active.json` with a rename.
///
/// **Historical:** product Timescale runs persist to PostgreSQL instead. This
/// path remains for on-demand export only.
pub fn commit_run_generation(commit: &RunGenerationCommit) -> Result<Value, String> {
    let building_id = commit.building_id.trim();
    if building_id.is_empty() {
        return Err("building_id required".into());
    }
    let prepared = prepare_run_generation(commit)?;
    let dir = results_dir(Some(building_id));
    std::fs::create_dir_all(&dir).map_err(|err| err.to_string())?;
    let gen = dir.join(GENERATIONS_DIR).join(&prepared.run_id);
    std::fs::create_dir_all(&gen).map_err(|err| err.to_string())?;
    for item in &prepared.prepared {
        write_json_file(&gen.join(format!("{}.json", item.rule_id)), &item.body)?;
    }
    write_json_file(&gen.join(MANIFEST_NAME), &prepared.manifest)?;
    let gen_dir = std::fs::File::open(&gen).map_err(|err| err.to_string())?;
    gen_dir.sync_all().map_err(|err| err.to_string())?;
    let pointer = json!({
        "run_id": prepared.run_id,
        "schema": MANIFEST_SCHEMA,
    });
    let pointer_bytes = serde_json::to_vec_pretty(&pointer).map_err(|err| err.to_string())?;
    let tmp = dir.join(".active.json.tmp");
    std::fs::write(&tmp, &pointer_bytes).map_err(|err| err.to_string())?;
    sync_file(&tmp)?;
    std::fs::rename(&tmp, dir.join(ACTIVE_FILE)).map_err(|err| err.to_string())?;
    if prepared.dirty_reason.is_none() {
        let _ = std::fs::remove_file(dir.join(DIRTY_FILE));
    } else if let Some(reason) = &prepared.dirty_reason {
        mark_building_results_dirty(building_id, reason);
    }
    let mut summary = prepared.manifest;
    if let Some(obj) = summary.as_object_mut() {
        obj.insert("results".into(), Value::Array(prepared.flat_results));
    }
    Ok(summary)
}

fn active_manifest(building_id: Option<&str>) -> Option<(PathBuf, Value)> {
    let dir = results_dir(building_id);
    let pointer = read_json_file(&dir.join(ACTIVE_FILE))?;
    let run_id = pointer.get("run_id").and_then(Value::as_str)?;
    if !safe_run_id(run_id) {
        return None;
    }
    let gen = dir.join(GENERATIONS_DIR).join(run_id);
    let manifest = read_json_file(&gen.join(MANIFEST_NAME))?;
    if manifest.get("run_id").and_then(Value::as_str) != Some(run_id) {
        return None;
    }
    Some((gen, manifest))
}

/// Active generation's rule file, addressed by exact rule id.
pub fn active_rule_result_body(building_id: &str, rule_id: &str) -> Option<Value> {
    if !safe_rule_id(rule_id) {
        return None;
    }
    let (gen, manifest) = active_manifest(Some(building_id))?;
    let listed = manifest
        .get("rules")
        .and_then(Value::as_array)
        .is_some_and(|rules| rules.iter().any(|rule| rule.as_str() == Some(rule_id)));
    if !listed {
        return None;
    }
    read_json_file(&gen.join(format!("{rule_id}.json")))
}

fn loose_rule_file_count(dir: &Path) -> usize {
    let Ok(rd) = std::fs::read_dir(dir) else {
        return 0;
    };
    rd.flatten()
        .filter(|entry| {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            entry.path().is_file() && name.ends_with(".json") && !name.starts_with('_')
        })
        .count()
}

fn generation_history(dir: &Path, active_id: Option<&str>) -> Vec<Value> {
    let gens = dir.join(GENERATIONS_DIR);
    let Ok(rd) = std::fs::read_dir(&gens) else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for entry in rd.flatten() {
        if !entry.path().is_dir() {
            continue;
        }
        let Some(manifest) = read_json_file(&entry.path().join(MANIFEST_NAME)) else {
            continue;
        };
        let run_id = manifest
            .get("run_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let active = active_id == Some(run_id.as_str());
        out.push(json!({
            "run_id": run_id,
            "run_status": manifest.get("run_status").cloned().unwrap_or(Value::Null),
            "result_count": manifest.get("result_count").cloned().unwrap_or(Value::Null),
            "completed_at": manifest.get("completed_at").cloned().unwrap_or(Value::Null),
            "cohort": manifest.get("cohort").cloned().unwrap_or(Value::Null),
            "active": active,
        }));
    }
    out.sort_by(|left, right| {
        left["completed_at"]
            .as_str()
            .unwrap_or("")
            .cmp(right["completed_at"].as_str().unwrap_or(""))
    });
    out
}

struct ActiveGeneration {
    gen: PathBuf,
    manifest: Value,
}

fn load_active(building_id: Option<&str>) -> Option<ActiveGeneration> {
    let (gen, manifest) = active_manifest(building_id)?;
    Some(ActiveGeneration { gen, manifest })
}

/// Prior complete full (or derived) run that still matches the rule pack and
/// has no dirty marker. Anything else must run again.
pub fn reusable_complete_run(building_id: &str) -> Option<Value> {
    let active = load_active(Some(building_id))?;
    if active.manifest.get("run_status").and_then(Value::as_str) != Some("complete") {
        return None;
    }
    let cohort = active
        .manifest
        .get("cohort")
        .and_then(Value::as_str)
        .unwrap_or("");
    if cohort == "scoped" {
        return None;
    }
    let stored = active
        .manifest
        .get("rule_set_hash")
        .and_then(Value::as_str)
        .unwrap_or("");
    if stored.is_empty() || stored != rule_set_hash() {
        return None;
    }
    if results_dir(Some(building_id)).join(DIRTY_FILE).is_file() {
        return None;
    }
    let rows = collect_generation_rows(&active);
    let stored_count = active
        .manifest
        .get("result_count")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    if stored_count != rows.len() as u64 {
        return None;
    }
    let mut summary = active.manifest;
    if let Some(obj) = summary.as_object_mut() {
        obj.insert("result_count".into(), json!(rows.len()));
    }
    Some(summary)
}

fn listed_rule_ids(manifest: &Value) -> Vec<String> {
    manifest
        .get("rules")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|rule| rule.as_str().map(str::to_string))
        .filter(|rule| safe_rule_id(rule))
        .collect()
}

fn manifest_type_map(manifest: &Value) -> BTreeMap<String, String> {
    let mut map = BTreeMap::new();
    let Some(equipment) = manifest
        .get("model")
        .and_then(|model| model.get("equipment"))
        .and_then(Value::as_array)
    else {
        return map;
    };
    for item in equipment {
        let Some(id) = item
            .get("equipment_id")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|id| !id.is_empty())
        else {
            continue;
        };
        let Some(kind) = item
            .get("equip_type")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|kind| !kind.is_empty())
        else {
            continue;
        };
        map.insert(id.to_string(), kind.to_string());
    }
    map
}

fn manifest_model_ids(manifest: &Value) -> Option<BTreeSet<String>> {
    let equipment = manifest
        .get("model")
        .and_then(|model| model.get("equipment"))
        .and_then(Value::as_array)?;
    let mut ids = BTreeSet::new();
    for item in equipment {
        if let Some(id) = item
            .get("equipment_id")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|id| !id.is_empty())
        {
            ids.insert(id.to_string());
        }
    }
    Some(ids)
}

fn collect_generation_rows(active: &ActiveGeneration) -> Vec<(String, Value)> {
    let model = manifest_model_ids(&active.manifest);
    let mut out = Vec::new();
    for rule_id in listed_rule_ids(&active.manifest) {
        let Some(body) = read_json_file(&active.gen.join(format!("{rule_id}.json"))) else {
            continue;
        };
        let Some(rows) = body.get("rows").and_then(Value::as_array) else {
            continue;
        };
        for row in rows {
            if let Some(model) = &model {
                if let Some(id) = row_equipment_id(row) {
                    if !model.contains(id) {
                        continue;
                    }
                }
            }
            out.push((rule_id.clone(), row.clone()));
        }
    }
    out
}

fn loose_legacy_count(building_id: Option<&str>) -> usize {
    loose_rule_file_count(&results_dir(building_id))
}

/// `GET /api/fdd/results/readiness` — clean only for one complete active generation.
///
/// `result_count` is the validated row count of that generation. Loose rule
/// files from older layouts are withheld and do not count as current.
pub fn readiness_response(building_id: Option<&str>) -> Value {
    let dir = results_dir(building_id);
    let dirty_body = read_json_file(&dir.join(DIRTY_FILE));
    let mut dirty_reasons: Vec<String> = Vec::new();
    if let Some(reason) = dirty_body
        .as_ref()
        .and_then(|body| body.get("reason"))
        .and_then(Value::as_str)
    {
        dirty_reasons.push(reason.to_string());
    }
    let active = load_active(building_id);
    let legacy_files = loose_legacy_count(building_id);
    let Some(active) = active else {
        if legacy_files > 0 {
            dirty_reasons.push("legacy_unmanifested".into());
        } else {
            dirty_reasons.push("never_run".into());
        }
        return json!({
            "ok": true,
            "has_results": false,
            "clean": false,
            "dirty_reasons": dirty_reasons,
            "completed_at": Value::Null,
            "result_count": 0,
            "run_id": Value::Null,
            "run_status": Value::Null,
            "mode": Value::Null,
            "legacy_file_count": legacy_files,
            "history": generation_history(&dir, None),
        });
    };
    let rows = collect_generation_rows(&active);
    let result_count = rows.len() as u64;
    let stored_count = active
        .manifest
        .get("result_count")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    if stored_count != result_count {
        dirty_reasons.push("result_count_mismatch".into());
    }
    let stored_hash = active
        .manifest
        .get("rule_set_hash")
        .and_then(Value::as_str)
        .unwrap_or("");
    if !stored_hash.is_empty() && stored_hash != rule_set_hash() {
        dirty_reasons.push("rule_set_changed".into());
    }
    let run_status = active
        .manifest
        .get("run_status")
        .and_then(Value::as_str)
        .unwrap_or("");
    let cohort = active
        .manifest
        .get("cohort")
        .and_then(Value::as_str)
        .unwrap_or("");
    if run_status == "partial" && !dirty_reasons.iter().any(|reason| reason == "run_partial") {
        dirty_reasons.push("run_partial".into());
    }
    if run_status == "failed" && !dirty_reasons.iter().any(|reason| reason == "run_failed") {
        dirty_reasons.push("run_failed".into());
    }
    if cohort == "scoped" && !dirty_reasons.iter().any(|reason| reason == "scoped_run") {
        dirty_reasons.push("scoped_run".into());
    }
    let run_id = active
        .manifest
        .get("run_id")
        .and_then(Value::as_str)
        .unwrap_or("");
    let clean = result_count > 0
        && run_status == "complete"
        && cohort != "scoped"
        && dirty_reasons.is_empty();
    json!({
        "ok": true,
        "has_results": result_count > 0,
        "clean": clean,
        "dirty_reasons": dirty_reasons,
        "completed_at": active.manifest.get("completed_at").cloned().unwrap_or(Value::Null),
        "result_count": result_count,
        "run_id": run_id,
        "run_status": run_status,
        "parent_run_id": active.manifest.get("parent_run_id").cloned().unwrap_or(Value::Null),
        "cohort": cohort,
        "mode": active.manifest.get("mode").cloned().unwrap_or(Value::Null),
        "rules_succeeded": active.manifest.get("rules_succeeded").cloned().unwrap_or(Value::Null),
        "rules_failed": active.manifest.get("rules_failed").cloned().unwrap_or(Value::Null),
        "rules_skipped": active.manifest.get("rules_skipped").cloned().unwrap_or(Value::Null),
        "legacy_file_count": legacy_files,
        "history": generation_history(&dir, Some(run_id)),
    })
}

fn load_reg() -> Result<RuleRegistry, String> {
    let dir = manifest_registry_dir();
    load_registry(&dir).map_err(|e| format!("rule catalogue unavailable: {e}"))
}

/// Registry rules keyed by rule_id and aliases (empty map when registry is unavailable).
pub fn load_registry_rules_map() -> HashMap<String, RuleSpec> {
    let mut out = HashMap::new();
    if let Ok(reg) = load_reg() {
        for rule in reg.rules {
            for alias in &rule.aliases {
                out.insert(alias.clone(), rule.clone());
            }
            out.insert(rule.rule_id.clone(), rule);
        }
    }
    out
}

fn param_to_json(rule: &RuleSpec) -> Value {
    let mut params = serde_json::Map::new();
    for (key, def) in &rule.parameters {
        // confirm_seconds is exposed only as confirm_min (minutes) below so Lab /
        // Overview sliders match Vibe19 session_config + fault_settings units.
        if key == "confirm_seconds" {
            continue;
        }
        params.insert(
            key.clone(),
            json!({
                "key": key,
                "label": def.label,
                "default": def.default,
                "min": def.min,
                "max": def.max,
                "step": def.step,
                "unit": def.unit,
                "control": def.frontend_control,
                "sql_placeholder": def.sql_placeholder,
            }),
        );
    }
    // Always expose confirm as confirm_min (minutes) for vibe19 UI parity.
    if !params.contains_key("confirm_min") {
        let default_min = rule
            .parameters
            .get("confirm_seconds")
            .map(|def| def.default / 60.0)
            .unwrap_or((rule.confirm_seconds as f64) / 60.0);
        let (min_m, max_m, step_m) = rule
            .parameters
            .get("confirm_seconds")
            .map(|def| (def.min / 60.0, def.max / 60.0, (def.step / 60.0).max(0.05)))
            .unwrap_or((0.0, 120.0, 1.0));
        params.insert(
            "confirm_min".into(),
            json!({
                "key": "confirm_min",
                "label": "Fault confirm delay",
                "default": default_min,
                "min": min_m,
                "max": max_m,
                "step": step_m,
                "unit": "min",
                "control": "slider",
                "sql_placeholder": "CONFIRM_SECONDS",
            }),
        );
    }
    Value::Object(params)
}

fn rule_summary(rule: &RuleSpec) -> Value {
    json!({
        "rule_id": rule.rule_id,
        "sql_file": rule.sql_file,
        "description": rule.description,
        "equipment_kinds": rule.equipment_kinds,
        "required_roles": rule.required_roles,
        "optional_roles": rule.optional_roles,
        "output_columns": rule.output_columns,
        "confirm_seconds": rule.confirm_seconds,
        "confirm_min": (rule.confirm_seconds as f64) / 60.0,
        "parity_status": rule.parity_status,
        "dashboard_wired": rule.dashboard_wired,
        "parameter_count": rule.parameters.len(),
        "aliases": rule.aliases,
        "pack_version": rule_pack_version(rule),
        "enabled": true,
        "removed": false,
        "overrides": {},
    })
}

/// Plot role budget shared with the Timescale FDD series response.
pub const SERIES_ROLE_CAP: usize = 6;

/// One catalogue row already stored. `enabled` and `overrides` belong to the
/// operator. Reconcile copies `overrides` forward and does not write `enabled`.
#[derive(Debug, Clone, PartialEq)]
pub struct CatalogueExisting {
    pub rule_id: String,
    pub enabled: bool,
    pub catalogue_source: Option<String>,
    pub pack_version: Option<String>,
    pub removed: bool,
    pub overrides: Map<String, Value>,
}

/// Pack fields to insert or refresh. `enabled` is insert-only and is absent here
/// so an operator disable survives an upgrade.
#[derive(Debug, Clone, PartialEq)]
pub struct CatalogueUpsert {
    pub rule_id: String,
    pub sql_file: String,
    pub title: String,
    pub equipment_kinds: Vec<String>,
    pub required_roles: Vec<String>,
    pub optional_roles: Vec<String>,
    pub parity_status: String,
    pub pack_version: String,
    pub overrides: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CatalogueDetail {
    pub catalogue_source: Option<String>,
    pub pack_version: Option<String>,
    pub removed: bool,
    pub overrides: Map<String, Value>,
}

/// Idempotent diff of the shipped pack against catalogue rows.
#[derive(Debug, Clone, PartialEq)]
pub struct CatalogueReconcilePlan {
    pub catalogue_version: String,
    pub upserts: Vec<CatalogueUpsert>,
    /// Pack-sourced ids that are no longer in the pack and are not yet marked removed.
    pub removed_rule_ids: Vec<String>,
}

fn sorted_join(mut values: Vec<String>) -> String {
    values.sort();
    values.join(",")
}

/// Content hash of one pack rule. A description, role, or default change bumps it.
pub fn rule_pack_version(rule: &RuleSpec) -> String {
    let mut params: Vec<String> = rule
        .parameters
        .iter()
        .map(|(key, def)| format!("{key}={}", def.default))
        .collect();
    params.sort();
    let body = format!(
        "{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}",
        rule.rule_id,
        rule.sql_file,
        rule.description,
        rule.parity_status,
        rule.confirm_seconds,
        rule.dashboard_wired,
        sorted_join(rule.aliases.clone()),
        sorted_join(rule.equipment_kinds.clone()),
        sorted_join(rule.required_roles.clone()),
        sorted_join(rule.optional_roles.clone()),
        params.join(","),
    );
    sha256_hex(body.as_bytes())
}

pub fn catalogue_detail_from_json(detail: Option<&Value>) -> CatalogueDetail {
    let obj = detail.and_then(Value::as_object);
    let text = |key: &str| {
        obj.and_then(|fields| fields.get(key))
            .and_then(Value::as_str)
            .map(str::to_string)
    };
    let removed = obj
        .and_then(|fields| fields.get("removed"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let overrides = obj
        .and_then(|fields| fields.get("overrides"))
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    CatalogueDetail {
        catalogue_source: text("catalogue_source"),
        pack_version: text("pack_version"),
        removed,
        overrides,
    }
}

/// Plan the catalogue write. Caller applies it. Running the plan twice against
/// the post-state yields the same version and no new removals.
pub fn plan_catalogue_reconcile(
    rules: &[RuleSpec],
    existing: &[CatalogueExisting],
) -> CatalogueReconcilePlan {
    let mut by_id: HashMap<&str, &CatalogueExisting> = HashMap::new();
    for row in existing {
        by_id.insert(row.rule_id.as_str(), row);
    }
    let mut version_lines = Vec::with_capacity(rules.len());
    let mut upserts = Vec::with_capacity(rules.len());
    for rule in rules {
        let pack_version = rule_pack_version(rule);
        version_lines.push(format!("{}\u{1f}{pack_version}", rule.rule_id));
        let overrides = by_id
            .get(rule.rule_id.as_str())
            .map(|row| row.overrides.clone())
            .unwrap_or_default();
        upserts.push(CatalogueUpsert {
            rule_id: rule.rule_id.clone(),
            sql_file: rule.sql_file.clone(),
            title: rule.description.clone(),
            equipment_kinds: rule.equipment_kinds.clone(),
            required_roles: rule.required_roles.clone(),
            optional_roles: rule.optional_roles.clone(),
            parity_status: rule.parity_status.clone(),
            pack_version,
            overrides,
        });
    }
    version_lines.sort();
    let catalogue_version = sha256_hex(version_lines.join("\n").as_bytes());
    let pack_ids: BTreeSet<&str> = rules.iter().map(|rule| rule.rule_id.as_str()).collect();
    let mut removed_rule_ids = Vec::new();
    for row in existing {
        let from_pack = row.catalogue_source.as_deref() == Some("pack");
        if from_pack && !row.removed && !pack_ids.contains(row.rule_id.as_str()) {
            removed_rule_ids.push(row.rule_id.clone());
        }
    }
    removed_rule_ids.sort();
    CatalogueReconcilePlan {
        catalogue_version,
        upserts,
        removed_rule_ids,
    }
}

fn safe_override_key(key: &str) -> bool {
    !key.is_empty() && key.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// Tuner edit. Unknown keys and values outside the pack slider are refused.
pub fn edit_rule_override(
    rule: &RuleSpec,
    overrides: &mut Map<String, Value>,
    key: &str,
    value: f64,
) -> Result<(), String> {
    let key = key.trim();
    if !safe_override_key(key) {
        return Err(format!("unknown catalogue parameter {key}"));
    }
    if !value.is_finite() {
        return Err(format!("override {key} is not a finite number"));
    }
    if key == "confirm_min" {
        if value < 0.0 {
            return Err("override confirm_min is outside 0..".into());
        }
    } else {
        match rule.parameters.get(key) {
            Some(def) if value < def.min || value > def.max => {
                return Err(format!(
                    "override {key} is outside {}..{}",
                    def.min, def.max
                ));
            }
            Some(_) => {}
            None => return Err(format!("unknown catalogue parameter {key}")),
        }
    }
    overrides.insert(key.to_string(), json!(value));
    Ok(())
}

/// Tuner restore. Clears operator overrides and leaves the pack defaults.
pub fn restore_catalogue_overrides(overrides: &mut Map<String, Value>) {
    overrides.clear();
}

fn safe_role(name: &str) -> bool {
    !name.is_empty() && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// Roles for the FDD series plot after a run. No run, or a removed rule, is an error.
pub fn series_roles_after_run(
    run_present: bool,
    removed: bool,
    required: &[String],
    optional: &[String],
) -> Result<Vec<String>, String> {
    if !run_present {
        return Err("rule catalogue series unavailable: no FDD run for this rule".into());
    }
    if removed {
        return Err("rule catalogue series unavailable: rule removed from the catalogue".into());
    }
    let mut roles = Vec::new();
    for role in required.iter().chain(optional.iter()) {
        if !safe_role(role) || roles.iter().any(|existing| existing == role) {
            continue;
        }
        roles.push(role.clone());
        if roles.len() == SERIES_ROLE_CAP {
            break;
        }
    }
    Ok(roles)
}

fn catalogue_list_from_load(loaded: Result<RuleRegistry, String>) -> Value {
    match loaded {
        Ok(reg) if reg.rules.is_empty() => json!({
            "ok": false,
            "error": "rule catalogue unavailable: pack has no rules",
            "rules_dir": reg.rules_dir,
            "count": 0,
            "rules": [],
        }),
        Ok(reg) => {
            let rules: Vec<Value> = reg.rules.iter().map(rule_summary).collect();
            let catalogue_version = plan_catalogue_reconcile(&reg.rules, &[]).catalogue_version;
            json!({
                "ok": true,
                "rules_dir": reg.rules_dir,
                "catalogue_version": catalogue_version,
                "count": rules.len(),
                "rules": rules,
            })
        }
        Err(e) => json!({
            "ok": false,
            "error": e,
            "count": 0,
            "rules": [],
        }),
    }
}

/// `GET /api/fdd/rules` - full registry catalog.
pub fn list_registry_rules() -> Value {
    catalogue_list_from_load(load_reg())
}

/// `GET /api/fdd/rules/{id}/params` - tuning schema for one rule.
pub fn rule_params_response(rule_id: &str) -> Value {
    match load_reg() {
        Ok(reg) => match reg.rules.iter().find(|r| r.rule_id == rule_id) {
            Some(rule) => json!({
                "ok": true,
                "rule_id": rule.rule_id,
                "confirm_seconds": rule.confirm_seconds,
                "required_roles": rule.required_roles,
                "params": param_to_json(rule),
            }),
            None => json!({"ok": false, "error": format!("unknown rule_id {rule_id}")}),
        },
        Err(e) => json!({"ok": false, "error": e}),
    }
}

/// `GET /api/fdd/cache/status` - parquet ingest / results status.
pub fn cache_status() -> Value {
    let pq = parquet_root();
    let results = results_dir(None);
    let history = pq.join("history");
    let parquet_files = walkdir_count(&pq, "parquet");
    let result_files = walkdir_count(&results, "json");
    json!({
        "ok": true,
        "parquet_root": pq.display().to_string(),
        "parquet_exists": pq.is_dir(),
        "history_exists": history.is_dir(),
        "parquet_file_count": parquet_files,
        "results_dir": results.display().to_string(),
        "result_file_count": result_files,
        "sql_rules_dir": sql_rules_dir().display().to_string(),
        "sql_rules_present": sql_rules_dir().join("registry.yaml").is_file(),
    })
}

fn walkdir_count(root: &Path, ext: &str) -> usize {
    if !root.is_dir() {
        return 0;
    }
    walkdir::WalkDir::new(root)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.file_type().is_file()
                && e.path()
                    .extension()
                    .and_then(|x| x.to_str())
                    .is_some_and(|x| x.eq_ignore_ascii_case(ext))
        })
        .count()
}

fn rule_applies_to_kind(kinds: &[String], kind: &str) -> bool {
    if kinds.is_empty() {
        return true;
    }
    let kind_c = crate::equipment_types::canonical_kind(kind).unwrap_or(kind);
    kinds.iter().any(|k| {
        let rule_c = crate::equipment_types::canonical_kind(k).unwrap_or(k.as_str());
        rule_c.eq_ignore_ascii_case(kind_c) || k.eq_ignore_ascii_case(kind)
    })
}

/// Keep a completed PASS/FAULT when the stamp applies. A stored
/// `NOT_APPLICABLE*` label from an empty Parquet type map must not survive
/// once Timescale has a matching equip_type. A missing stamp still matches
/// nothing when the rule names kinds.
fn displayed_result_status(
    stored: Option<&str>,
    fault_hours: f64,
    rule_kinds: Option<&[String]>,
    stamped: Option<&str>,
) -> String {
    let kinds = rule_kinds.unwrap_or(&[]);
    let has_stamp = stamped.map(str::trim).is_some_and(|s| !s.is_empty());
    let kind = crate::equipment_types::kind_for("", stamped);
    let applies = if !has_stamp {
        kinds.is_empty()
    } else {
        kinds.is_empty() || rule_applies_to_kind(kinds, kind)
    };
    if !applies {
        return "NOT_APPLICABLE_EQUIPMENT_TYPE".into();
    }
    let stored = stored.unwrap_or("").trim();
    if stored.is_empty() || stored.to_ascii_uppercase().contains("NOT_APPLICABLE") {
        return if fault_hours > 0.0 {
            "FAULT".into()
        } else {
            "PASS".into()
        };
    }
    stored.to_string()
}

/// `GET /api/fdd/equipment` - equipment present in the parquet cache.
///
/// When `building_id` is set, walk both legacy `building={id}/equipment=*` and
/// canonical MQTT `history/building_id={id}/equipment_id=*` so Overview / AFDD
/// see live sites the same as CSV packages (3.3.33). Wave U V7 dual-reads the
/// newer of `tenants/{tid}/…` and hub-root.
pub fn equipment_response(building_id: Option<&str>) -> Value {
    equipment_response_scoped(building_id, preferred_tenant_from_env().as_deref())
}

/// Same as [`equipment_response`] with an explicit preferred tenant for MT dual-read.
pub fn equipment_response_scoped(building_id: Option<&str>, tenant_id: Option<&str>) -> Value {
    let pq = parquet_root();
    let mut ids = Vec::new();
    match building_id.map(str::trim).filter(|s| !s.is_empty()) {
        Some(bid) => {
            let root = storage_root_for_building(&pq, bid, tenant_id);
            collect_equipment_prefix(
                &root.join(format!("building={bid}")),
                "equipment=",
                &mut ids,
            );
            collect_equipment_prefix(
                &root.join("history").join(format!("building_id={bid}")),
                "equipment_id=",
                &mut ids,
            );
        }
        None => {
            collect_equipment_prefix(&pq, "equipment=", &mut ids);
            collect_equipment_prefix(&pq.join("history"), "equipment_id=", &mut ids);
            // Also surface equipment under tenant partitions (post-migrate).
            let tenants = pq.join("tenants");
            if tenants.is_dir() {
                if let Ok(rd) = std::fs::read_dir(&tenants) {
                    for entry in rd.flatten() {
                        if entry.path().is_dir() {
                            collect_equipment_prefix(&entry.path(), "equipment=", &mut ids);
                            collect_equipment_prefix(
                                &entry.path().join("history"),
                                "equipment_id=",
                                &mut ids,
                            );
                        }
                    }
                }
            }
        }
    }
    ids.sort();
    ids.dedup();
    let type_root = building_id
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|bid| storage_root_for_building(&pq, bid, tenant_id))
        .unwrap_or_else(|| pq.clone());
    let stamped_types = crate::equipment_types::load_type_map(&type_root, building_id);
    let equipment: Vec<Value> = ids
        .iter()
        .map(|id| {
            let stamped = stamped_types.get(id).map(String::as_str);
            crate::equipment_types::type_report(id, stamped)
        })
        .collect();
    json!({"ok": true, "count": equipment.len(), "equipment": equipment})
}

/// Prefer a stored `fault_pct`. Otherwise derive it from fault hours and the
/// sample window (`sample_rows * poll_seconds`) so older result files still
/// show a percent.
pub fn derive_fault_pct(row: &Value) -> Option<f64> {
    if let Some(value) = row.get("fault_pct").and_then(Value::as_f64) {
        if value.is_finite() {
            return Some(value);
        }
    }
    let hours = row.get("fault_hours").and_then(Value::as_f64)?;
    if !hours.is_finite() || hours < 0.0 {
        return None;
    }
    let samples = json_f64(row.get("sample_rows"))?;
    let poll = json_f64(row.get("poll_seconds"))?;
    if samples <= 0.0 || poll <= 0.0 {
        return None;
    }
    let window_hours = samples * poll / 3600.0;
    if window_hours <= 0.0 {
        return None;
    }
    Some(((100.0 * hours) / window_hours).clamp(0.0, 100.0))
}

fn json_f64(value: Option<&Value>) -> Option<f64> {
    let value = value?;
    if let Some(n) = value.as_f64() {
        return n.is_finite().then_some(n);
    }
    value
        .as_i64()
        .map(|n| n as f64)
        .or_else(|| value.as_u64().map(|n| n as f64))
}

fn metric_unit_name(column: &str) -> &'static str {
    match column {
        "avg_zone_temp" | "min_zone_temp" | "max_zone_temp" => "degF",
        "comfort_pct" => "pct",
        "fan_runtime_hours" | "total_hours" => "h",
        _ => "",
    }
}

fn finite_number(value: &Value) -> Option<f64> {
    value.as_f64().filter(|number| number.is_finite())
}

fn first_metric_number(row: &Value) -> Option<(&'static str, f64)> {
    let values = row.get("values").and_then(Value::as_object);
    let stored = row.as_object();
    for key in METRIC_FIELDS {
        if let Some(value) = stored.and_then(|obj| obj.get(key)).and_then(finite_number) {
            return Some((key, value));
        }
        if let Some(value) = values.and_then(|obj| obj.get(key)).and_then(finite_number) {
            return Some((key, value));
        }
    }
    None
}

/// Metric document for one result row. A missing measurement stays null.
/// It is never rewritten into a diagnostic PASS with fault hours of zero.
fn metric_document(row: &Value, manifest: &Value) -> Value {
    if let Some(metric) = row.get("metric").filter(|metric| !metric.is_null()) {
        let mut doc = metric.clone();
        if let Some(obj) = doc.as_object_mut() {
            let window = obj
                .entry("window")
                .or_insert_with(|| manifest.get("window").cloned().unwrap_or(json!({})));
            if let Some(window) = window.as_object_mut() {
                if !window.contains_key("watermark") {
                    window.insert(
                        "watermark".into(),
                        manifest.get("watermark").cloned().unwrap_or(Value::Null),
                    );
                }
            }
            if !obj.contains_key("coverage") {
                obj.insert(
                    "coverage".into(),
                    json!({
                        "sample_rows": row.get("sample_rows").cloned().unwrap_or(Value::Null),
                    }),
                );
            }
        }
        return doc;
    }
    let Some((name, value)) = first_metric_number(row) else {
        return Value::Null;
    };
    json!({
        "name": name,
        "value": value,
        "unit": metric_unit_name(name),
        "window": {
            "start": manifest.get("window").and_then(|window| window.get("start")).cloned().unwrap_or(Value::Null),
            "end": manifest.get("window").and_then(|window| window.get("end")).cloned().unwrap_or(Value::Null),
            "watermark": manifest.get("watermark").cloned().unwrap_or(Value::Null),
        },
        "coverage": {
            "sample_rows": row.get("sample_rows").cloned().unwrap_or(Value::Null),
        },
    })
}

/// `GET /api/fdd/results` - rows from the active run generation only.
///
/// `building_id` reads that site's generation so two buildings do not share a
/// result folder. Loose rule files without a manifest are not current.
///
/// Soft-OPEN P0-2: prefer [`results_response_with_types`] with Timescale
/// `equipment.equip_type` stamps. This Parquet-era fallback stays for
/// non-Timescale lab paths only.
pub fn results_response(building_id: Option<&str>) -> Value {
    let stamped_types = crate::equipment_types::load_type_map(&parquet_root(), building_id);
    results_response_with_types(building_id, &stamped_types, "package_or_parquet")
}

/// Same as [`results_response`], but equipment kinds come from the caller's
/// type map (Timescale `equipment` table on tip).
pub fn results_response_with_types(
    building_id: Option<&str>,
    stamped_types: &BTreeMap<String, String>,
    type_source_label: &str,
) -> Value {
    let reg = load_reg().ok();
    let mut metadata = HashMap::new();
    let mut kinds_by_rule: HashMap<String, Vec<String>> = HashMap::new();
    if let Some(reg) = &reg {
        for rule in &reg.rules {
            metadata.insert(rule.rule_id.clone(), rule.description.clone());
            kinds_by_rule.insert(rule.rule_id.clone(), rule.equipment_kinds.clone());
            for alias in &rule.aliases {
                kinds_by_rule.insert(alias.clone(), rule.equipment_kinds.clone());
            }
        }
    }
    let Some(active) = load_active(building_id) else {
        return json!({
            "ok": true,
            "count": 0,
            "results": [],
            "run_id": Value::Null,
            "run_status": Value::Null,
            "legacy_withheld": loose_legacy_count(building_id) > 0,
        });
    };
    let manifest_types = manifest_type_map(&active.manifest);
    let mut rows = Vec::new();
    for (rule_id, row) in collect_generation_rows(&active) {
        let equipment_id = row_equipment_id(&row).unwrap_or("");
        let rule_level = equipment_id.is_empty();
        let stamped = if rule_level {
            None
        } else {
            stamped_types
                .get(equipment_id)
                .map(String::as_str)
                .or_else(|| manifest_types.get(equipment_id).map(String::as_str))
        };
        let kind = crate::equipment_types::kind_for(equipment_id, stamped);
        let applies = if rule_level {
            true
        } else if stamped
            .map(str::trim)
            .is_some_and(|stamp| !stamp.is_empty())
        {
            kinds_by_rule
                .get(&rule_id)
                .map(|kinds| rule_applies_to_kind(kinds, kind))
                .unwrap_or(true)
        } else {
            kinds_by_rule
                .get(&rule_id)
                .map(|kinds| kinds.is_empty())
                .unwrap_or(true)
        };
        let metric = is_metric_row(&row);
        let stored_status = row_status_token(&row);
        let withheld = stored_status == "ERROR" || stored_status.starts_with("SKIP");
        let stored_fault = row.get("fault_hours").filter(|value| !value.is_null());
        let fault_hours_num = stored_fault.and_then(Value::as_f64).unwrap_or(0.0);
        let status = if rule_level {
            if stored_status.is_empty() {
                "SKIP".to_string()
            } else {
                stored_status.clone()
            }
        } else if withheld {
            stored_status.clone()
        } else if metric {
            if applies {
                "METRIC".to_string()
            } else {
                "NOT_APPLICABLE_EQUIPMENT_TYPE".to_string()
            }
        } else {
            displayed_result_status(
                row.get("status").and_then(Value::as_str),
                fault_hours_num,
                kinds_by_rule.get(&rule_id).map(Vec::as_slice),
                stamped,
            )
        };
        let fault_hours = if metric || withheld {
            Value::Null
        } else if !applies {
            json!(0.0)
        } else if stored_fault.is_some() {
            json!(fault_hours_num)
        } else {
            Value::Null
        };
        let missing_roles = row
            .get("missing_roles")
            .cloned()
            .unwrap_or_else(|| json!([]));
        let type_source = if stamped.is_some() {
            type_source_label
        } else if rule_level {
            "rule"
        } else {
            "missing"
        };
        let metric_doc = if metric {
            metric_document(&row, &active.manifest)
        } else {
            Value::Null
        };
        rows.push(json!({
            "rule_id": rule_id,
            "title": metadata.get(&rule_id).cloned().unwrap_or_default(),
            "equipment_id": equipment_id,
            "equipment_type": if rule_level {
                Value::Null
            } else {
                json!(crate::equipment_types::api_equipment_type_for(equipment_id, stamped))
            },
            "equipment_type_raw": stamped,
            "equipment_type_source": type_source,
            "status": status,
            "output_kind": if metric { "metric" } else { "diagnostic" },
            "fault_hours": fault_hours,
            "fault_pct": if metric || withheld {
                Value::Null
            } else {
                json!(derive_fault_pct(&row))
            },
            "metric": metric_doc,
            "values": row.get("values").cloned().unwrap_or(Value::Null),
            "missing_roles": missing_roles,
            "notes": row.get("notes").cloned().unwrap_or(Value::Null),
            "run_id": active.manifest.get("run_id").cloned().unwrap_or(Value::Null),
        }));
    }
    json!({
        "ok": true,
        "count": rows.len(),
        "results": rows,
        "run_id": active.manifest.get("run_id").cloned().unwrap_or(Value::Null),
        "run_status": active.manifest.get("run_status").cloned().unwrap_or(Value::Null),
        "parent_run_id": active.manifest.get("parent_run_id").cloned().unwrap_or(Value::Null),
        "legacy_withheld": false,
    })
}

pub fn loose_rule_file_count_for_building(building_id: &str) -> usize {
    loose_rule_file_count(&results_dir(Some(building_id)))
}

/// Format API results from a Timescale-stored generation manifest and row list.
pub fn results_response_with_timescale_rows(
    building_id: Option<&str>,
    stamped_types: &BTreeMap<String, String>,
    type_source_label: &str,
    manifest: &Value,
    stored_rows: &[(String, Value)],
) -> Value {
    let reg = load_reg().ok();
    let mut metadata = HashMap::new();
    let mut kinds_by_rule: HashMap<String, Vec<String>> = HashMap::new();
    if let Some(reg) = &reg {
        for rule in &reg.rules {
            metadata.insert(rule.rule_id.clone(), rule.description.clone());
            kinds_by_rule.insert(rule.rule_id.clone(), rule.equipment_kinds.clone());
            for alias in &rule.aliases {
                kinds_by_rule.insert(alias.clone(), rule.equipment_kinds.clone());
            }
        }
    }
    let manifest_types = manifest_type_map(manifest);
    let mut rows = Vec::new();
    for (rule_id, row) in stored_rows {
        let equipment_id = row_equipment_id(row).unwrap_or("");
        let rule_level = equipment_id.is_empty();
        let stamped = if rule_level {
            None
        } else {
            stamped_types
                .get(equipment_id)
                .map(String::as_str)
                .or_else(|| manifest_types.get(equipment_id).map(String::as_str))
        };
        let kind = crate::equipment_types::kind_for(equipment_id, stamped);
        let applies = if rule_level {
            true
        } else if stamped
            .map(str::trim)
            .is_some_and(|stamp| !stamp.is_empty())
        {
            kinds_by_rule
                .get(rule_id)
                .map(|kinds| rule_applies_to_kind(kinds, kind))
                .unwrap_or(true)
        } else {
            kinds_by_rule
                .get(rule_id)
                .map(|kinds| kinds.is_empty())
                .unwrap_or(true)
        };
        let metric = is_metric_row(row);
        let stored_status = row_status_token(row);
        let withheld = stored_status == "ERROR" || stored_status.starts_with("SKIP");
        let stored_fault = row.get("fault_hours").filter(|value| !value.is_null());
        let fault_hours_num = stored_fault.and_then(Value::as_f64).unwrap_or(0.0);
        let status = if rule_level {
            if stored_status.is_empty() {
                "SKIP".to_string()
            } else {
                stored_status.clone()
            }
        } else if withheld {
            stored_status.clone()
        } else if metric {
            if applies {
                "METRIC".to_string()
            } else {
                "NOT_APPLICABLE_EQUIPMENT_TYPE".to_string()
            }
        } else {
            displayed_result_status(
                row.get("status").and_then(Value::as_str),
                fault_hours_num,
                kinds_by_rule.get(rule_id).map(Vec::as_slice),
                stamped,
            )
        };
        let fault_hours = if metric || withheld {
            Value::Null
        } else if !applies {
            json!(0.0)
        } else if stored_fault.is_some() {
            json!(fault_hours_num)
        } else {
            Value::Null
        };
        let missing_roles = row
            .get("missing_roles")
            .cloned()
            .unwrap_or_else(|| json!([]));
        let type_source = if stamped.is_some() {
            type_source_label
        } else if rule_level {
            "rule"
        } else {
            "missing"
        };
        let metric_doc = if metric {
            metric_document(row, manifest)
        } else {
            Value::Null
        };
        rows.push(json!({
            "rule_id": rule_id,
            "title": metadata.get(rule_id).cloned().unwrap_or_default(),
            "equipment_id": equipment_id,
            "equipment_type": if rule_level {
                Value::Null
            } else {
                json!(crate::equipment_types::api_equipment_type_for(equipment_id, stamped))
            },
            "equipment_type_raw": stamped,
            "equipment_type_source": type_source,
            "status": status,
            "output_kind": if metric { "metric" } else { "diagnostic" },
            "fault_hours": fault_hours,
            "fault_pct": if metric || withheld {
                Value::Null
            } else {
                json!(derive_fault_pct(row))
            },
            "metric": metric_doc,
            "values": row.get("values").cloned().unwrap_or(Value::Null),
            "missing_roles": missing_roles,
            "notes": row.get("notes").cloned().unwrap_or(Value::Null),
            "run_id": manifest.get("run_id").cloned().unwrap_or(Value::Null),
        }));
    }
    json!({
        "ok": true,
        "count": rows.len(),
        "results": rows,
        "run_id": manifest.get("run_id").cloned().unwrap_or(Value::Null),
        "run_status": manifest.get("run_status").cloned().unwrap_or(Value::Null),
        "parent_run_id": manifest.get("parent_run_id").cloned().unwrap_or(Value::Null),
        "legacy_withheld": loose_legacy_count(building_id) > 0,
        "source": "timescale",
    })
}

/// Readiness when the active generation lives in Timescale, not manifest files.
pub fn readiness_from_timescale_manifest(
    _building_id: Option<&str>,
    legacy_files: usize,
    manifest: Option<&Value>,
) -> Value {
    let mut dirty_reasons: Vec<String> = Vec::new();
    let Some(manifest) = manifest else {
        if legacy_files > 0 {
            dirty_reasons.push("legacy_unmanifested".into());
        } else {
            dirty_reasons.push("never_run".into());
        }
        return json!({
            "ok": true,
            "has_results": false,
            "clean": false,
            "dirty_reasons": dirty_reasons,
            "completed_at": Value::Null,
            "result_count": 0,
            "run_id": Value::Null,
            "run_status": Value::Null,
            "mode": Value::Null,
            "legacy_file_count": legacy_files,
            "source": "timescale",
        });
    };
    let result_count = manifest
        .get("result_count")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let stored_hash = manifest
        .get("rule_set_hash")
        .and_then(Value::as_str)
        .unwrap_or("");
    if !stored_hash.is_empty() && stored_hash != rule_set_hash() {
        dirty_reasons.push("rule_set_changed".into());
    }
    let run_status = manifest
        .get("run_status")
        .and_then(Value::as_str)
        .unwrap_or("");
    let cohort = manifest.get("cohort").and_then(Value::as_str).unwrap_or("");
    if run_status == "partial" {
        dirty_reasons.push("run_partial".into());
    }
    if run_status == "failed" {
        dirty_reasons.push("run_failed".into());
    }
    if cohort == "scoped" {
        dirty_reasons.push("scoped_run".into());
    }
    let run_id = manifest.get("run_id").and_then(Value::as_str).unwrap_or("");
    let clean = result_count > 0
        && run_status == "complete"
        && cohort != "scoped"
        && dirty_reasons.is_empty();
    json!({
        "ok": true,
        "has_results": result_count > 0,
        "clean": clean,
        "dirty_reasons": dirty_reasons,
        "completed_at": manifest.get("completed_at").cloned().unwrap_or(Value::Null),
        "result_count": result_count,
        "run_id": run_id,
        "run_status": run_status,
        "parent_run_id": manifest.get("parent_run_id").cloned().unwrap_or(Value::Null),
        "cohort": cohort,
        "mode": manifest.get("mode").cloned().unwrap_or(Value::Null),
        "rules_succeeded": manifest.get("rules_succeeded").cloned().unwrap_or(Value::Null),
        "rules_failed": manifest.get("rules_failed").cloned().unwrap_or(Value::Null),
        "rules_skipped": manifest.get("rules_skipped").cloned().unwrap_or(Value::Null),
        "legacy_file_count": legacy_files,
        "source": "timescale",
    })
}

/// `GET /api/afdd/scheduler/result-slices` — per-rule window hashes.
///
/// Stress compares slices that sit outside the cycle window before and after
/// a lookback upsert. The display `rows` array is not this proof: a full-file
/// rewrite would still publish a fresh `rows` list.
pub fn result_slice_report(building_id: Option<&str>) -> Value {
    let mut rules = Vec::new();
    let run_id = if let Some(active) = load_active(building_id) {
        for rule_id in listed_rule_ids(&active.manifest) {
            let Some(body) = read_json_file(&active.gen.join(format!("{rule_id}.json"))) else {
                continue;
            };
            rules.push(json!({
                "rule_id": rule_id,
                "result_scope": body.get("result_scope").cloned().unwrap_or(Value::Null),
                "windows": fdd_store::rule_result_window_fingerprints(&body),
            }));
        }
        active
            .manifest
            .get("run_id")
            .cloned()
            .unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    json!({
        "ok": true,
        "building_id": building_id,
        "run_id": run_id,
        "rules": rules,
    })
}

/// Downsampled history series for one equipment/rule. Rule math continues to
/// use full-resolution parquet; only this display response is capped.
pub fn series_response(equipment_id: &str, rule_id: &str, building_id: Option<&str>) -> Value {
    series_response_scoped(
        equipment_id,
        rule_id,
        building_id,
        preferred_tenant_from_env().as_deref(),
    )
}

/// Same as [`series_response`] with an explicit preferred tenant for MT dual-read.
pub fn series_response_scoped(
    equipment_id: &str,
    rule_id: &str,
    building_id: Option<&str>,
    tenant_id: Option<&str>,
) -> Value {
    let _ = (equipment_id, rule_id, building_id, tenant_id);
    json!({
        "ok": false,
        "engine": "postgres-sql",
        "error": "Wave-X: DataFusion series retired; use Timescale FDD / analytics",
    })
}

/// `GET /api/fdd/roles` - role map file if present.
pub fn roles_response() -> Value {
    let candidates = [
        PathBuf::from("configs/role_map.json"),
        PathBuf::from("workspace/data/role_map.json"),
        PathBuf::from("/app/configs/role_map.json"),
    ];
    for c in candidates {
        if c.is_file() {
            match std::fs::read_to_string(&c) {
                Ok(text) => match serde_json::from_str::<Value>(&text) {
                    Ok(v) => {
                        return json!({
                            "ok": true,
                            "path": c.display().to_string(),
                            "roles": v,
                        })
                    }
                    Err(e) => {
                        return json!({
                            "ok": false,
                            "error": format!("parse {}: {e}", c.display()),
                        })
                    }
                },
                Err(e) => {
                    return json!({"ok": false, "error": e.to_string()});
                }
            }
        }
    }
    json!({
        "ok": true,
        "path": null,
        "roles": {},
        "hint": "no role_map.json found; place under configs/ or workspace/data/"
    })
}

/// `POST /api/fdd/run` body for registry engine (typed params only - no raw SQL).
///
/// ```json
/// { "mode": "registry", "rule_ids": ["FC1","VAV-1"], "params": { "FC1": { "confirm_min": 5 } },
///   "building_id": "BldgA" }
/// ```
/// Omit `rule_ids` to run all. Pass ``building_id`` to scope history via
/// ``register_historian_building`` (canonical ``history/building_id=`` then
/// legacy ``building=``) so MQTT live sites AFDD like CSV packages (3.3.33).
/// Without parquet cache, returns a clear error.
pub fn run_registry(payload: &Value) -> Value {
    run_registry_with_cancel(payload, None)
}

/// Registry run with optional cooperative cancel flag (#1127 P2).
pub fn run_registry_with_cancel(
    payload: &Value,
    cancel: Option<std::sync::Arc<std::sync::atomic::AtomicBool>>,
) -> Value {
    let _ = (payload, cancel);
    json!({
        "ok": false,
        "engine": "postgres-sql",
        "error": "Wave-X: DataFusion run_registry retired; use Timescale sql/fdd postgres-sql",
        "cache": cache_status(),
    })
}

/// Preview substituted SQL for a rule (integrator lab only - not operator UI).
pub fn preview_sql(rule_id: &str, overrides: &Value) -> Value {
    let _ = (rule_id, overrides);
    json!({
        "ok": false,
        "engine": "postgres-sql",
        "error": "Wave-X: DataFusion preview_sql retired",
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fault_pct_falls_back_to_fault_hours_over_sample_window() {
        let row = json!({
            "status": "FAULT",
            "fault_hours": 2.0,
            "sample_rows": 120,
            "poll_seconds": 300
        });
        let pct = derive_fault_pct(&row).expect("derived percent");
        let window_hours = 120.0 * 300.0 / 3600.0;
        assert!((pct - (100.0 * 2.0 / window_hours)).abs() < 1e-9);
        let stored =
            json!({"fault_pct": 4.5, "fault_hours": 9.0, "sample_rows": 10, "poll_seconds": 60});
        assert_eq!(derive_fault_pct(&stored), Some(4.5));
        assert_eq!(
            derive_fault_pct(&json!({"fault_hours": 1.0, "status": "FAULT"})),
            None
        );
    }

    #[test]
    fn oat_meteo_targets_stamped_ahu_not_id_prefix() {
        let reg = load_reg().expect("registry");
        let rule = reg
            .rules
            .iter()
            .find(|r| r.rule_id == "OAT-METEO")
            .expect("OAT-METEO");
        assert_eq!(rule.equipment_kinds, vec!["ahu".to_string()]);
        let sql_path =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../sql_rules/oat_meteo_fault.sql");
        let sql = std::fs::read_to_string(&sql_path).unwrap_or_else(|e| panic!("{e}"));
        let upper = sql.to_ascii_uppercase();
        assert!(
            !upper.contains("EQUIPMENT_ID LIKE") && !upper.contains("ILIKE"),
            "OAT-METEO must not filter equipment_id by text: {sql}"
        );
        assert!(rule_applies_to_kind(
            &rule.equipment_kinds,
            crate::equipment_types::kind_for("AC_1", Some("ahu"))
        ));
        assert!(rule_applies_to_kind(
            &rule.equipment_kinds,
            crate::equipment_types::kind_for("jci_ahu_1", Some("rtu"))
        ));
        assert!(!rule_applies_to_kind(
            &rule.equipment_kinds,
            crate::equipment_types::kind_for("AHU_BOX", Some("vav"))
        ));
        assert!(!rule_applies_to_kind(
            &rule.equipment_kinds,
            crate::equipment_types::kind_for("AHU_1", None)
        ));
        assert!(!rule_applies_to_kind(
            &rule.equipment_kinds,
            crate::equipment_types::kind_for("bldg2-zone-loopback", None)
        ));
    }

    #[test]
    fn typed_rules_do_not_run_against_unknown_equipment() {
        let kinds = vec!["ahu".to_string(), "zone_other".to_string()];
        assert!(rule_applies_to_kind(&kinds, "zone_other"));
        assert!(!rule_applies_to_kind(&kinds, "unknown"));
        assert!(!rule_applies_to_kind(&kinds, "general"));
        assert!(rule_applies_to_kind(&["general".to_string()], "general"));
        assert!(rule_applies_to_kind(&[], "unknown"));
    }

    #[test]
    fn zone_other_registry_contract_covers_zone_rules() {
        let reg = load_reg().expect("registry");
        for id in [
            "VAV-1",
            "VAV-2",
            "SV-RANGE",
            "SV-FLATLINE",
            "SV-SPIKE",
            "SV-STALE",
            "SV-RATE",
            "PID-HUNT-1",
            "SCHED-1",
            "SCHED-247",
        ] {
            let rule = reg
                .rules
                .iter()
                .find(|rule| rule.rule_id == id)
                .unwrap_or_else(|| panic!("missing {id}"));
            assert!(
                rule.equipment_kinds.iter().any(|kind| kind == "zone_other"),
                "{id} must apply to canonical zone_other equipment"
            );
            assert!(
                !rule.equipment_kinds.iter().any(|kind| kind == "zone"),
                "{id} must not use unreachable legacy zone kind"
            );
        }
    }

    #[test]
    fn list_rules_loads_repo_registry() {
        let v = list_registry_rules();
        assert_eq!(v["ok"], true, "{v}");
        let reg = load_reg().expect("registry");
        let listed = v["rules"].as_array().expect("rules");
        assert_eq!(listed.len(), reg.rules.len(), "{v}");
        assert_eq!(
            v["count"].as_u64().unwrap() as usize,
            reg.rules.len(),
            "{v}"
        );
        assert!(
            v["catalogue_version"]
                .as_str()
                .is_some_and(|v| !v.is_empty()),
            "{v}"
        );
    }

    #[test]
    fn catalogue_plan_keeps_override_disable_and_removal_stable() {
        let reg = load_reg().expect("registry");
        assert!(!reg.rules.is_empty(), "pack has rules");
        let fresh = plan_catalogue_reconcile(&reg.rules, &[]);
        assert_eq!(fresh.upserts.len(), reg.rules.len());
        assert!(fresh.removed_rule_ids.is_empty());
        assert!(fresh.upserts.iter().all(|row| row.overrides.is_empty()));

        let tunable = reg
            .rules
            .iter()
            .find(|rule| !rule.parameters.is_empty())
            .expect("tunable rule");
        let mut keys: Vec<&String> = tunable.parameters.keys().collect();
        keys.sort();
        let key = keys[0].as_str();
        let def = &tunable.parameters[key];
        let edited = if (def.min - def.default).abs() > f64::EPSILON {
            def.min
        } else {
            def.max
        };
        let mut overrides = Map::new();
        edit_rule_override(tunable, &mut overrides, key, edited).expect("edit");
        let rejected = edit_rule_override(tunable, &mut overrides, "not_a_param", edited);
        assert!(rejected.is_err(), "{rejected:?}");

        let mut existing = vec![CatalogueExisting {
            rule_id: tunable.rule_id.clone(),
            enabled: false,
            catalogue_source: Some("pack".into()),
            pack_version: Some("stale".into()),
            removed: false,
            overrides: overrides.clone(),
        }];
        existing.push(CatalogueExisting {
            rule_id: "RETIRED-PACK-RULE".into(),
            enabled: true,
            catalogue_source: Some("pack".into()),
            pack_version: Some("old".into()),
            removed: false,
            overrides: Map::new(),
        });
        existing.push(CatalogueExisting {
            rule_id: "OPERATOR-NOTE".into(),
            enabled: true,
            catalogue_source: None,
            pack_version: None,
            removed: false,
            overrides: Map::new(),
        });
        let upgraded = plan_catalogue_reconcile(&reg.rules, &existing);
        assert_eq!(upgraded.upserts.len(), reg.rules.len());
        let kept = upgraded
            .upserts
            .iter()
            .find(|row| row.rule_id == tunable.rule_id)
            .expect("tunable upsert");
        assert_eq!(
            kept.overrides.get(key).and_then(Value::as_f64),
            Some(edited)
        );
        assert_eq!(
            upgraded.removed_rule_ids,
            vec!["RETIRED-PACK-RULE".to_string()]
        );
        assert!(!upgraded
            .removed_rule_ids
            .iter()
            .any(|id| id == "OPERATOR-NOTE"));

        let mut after: Vec<CatalogueExisting> = upgraded
            .upserts
            .iter()
            .map(|row| CatalogueExisting {
                rule_id: row.rule_id.clone(),
                enabled: row.rule_id != tunable.rule_id,
                catalogue_source: Some("pack".into()),
                pack_version: Some(row.pack_version.clone()),
                removed: false,
                overrides: row.overrides.clone(),
            })
            .collect();
        after.push(CatalogueExisting {
            rule_id: "RETIRED-PACK-RULE".into(),
            enabled: true,
            catalogue_source: Some("pack".into()),
            pack_version: Some("old".into()),
            removed: true,
            overrides: Map::new(),
        });
        let repeated = plan_catalogue_reconcile(&reg.rules, &after);
        assert_eq!(repeated.catalogue_version, upgraded.catalogue_version);
        assert!(repeated.removed_rule_ids.is_empty());
        let still = repeated
            .upserts
            .iter()
            .find(|row| row.rule_id == tunable.rule_id)
            .expect("repeat upsert");
        assert_eq!(
            still.overrides.get(key).and_then(Value::as_f64),
            Some(edited)
        );
        let mut restored = still.overrides.clone();
        restore_catalogue_overrides(&mut restored);
        assert!(restored.is_empty());

        let mut changed = tunable.clone();
        changed.description.push_str(" revised");
        let mut rules = reg.rules.clone();
        if let Some(slot) = rules
            .iter_mut()
            .find(|rule| rule.rule_id == tunable.rule_id)
        {
            *slot = changed;
        }
        let bumped = plan_catalogue_reconcile(&rules, &[]);
        assert_ne!(bumped.catalogue_version, fresh.catalogue_version);
    }

    #[test]
    fn series_roles_follow_the_catalogue_only_after_a_run() {
        let missing = series_roles_after_run(false, false, &["zone_t".into()], &[]);
        assert!(missing.is_err(), "{missing:?}");
        let removed = series_roles_after_run(true, true, &["zone_t".into()], &[]);
        assert!(removed.is_err(), "{removed:?}");
        let reg = load_reg().expect("registry");
        let rule = reg
            .rules
            .iter()
            .find(|rule| !rule.required_roles.is_empty() || !rule.optional_roles.is_empty())
            .expect("plotted rule");
        let selected =
            series_roles_after_run(true, false, &rule.required_roles, &rule.optional_roles)
                .expect("series");
        let mut expected = Vec::new();
        for role in rule.required_roles.iter().chain(rule.optional_roles.iter()) {
            if expected.iter().any(|existing| existing == role) {
                continue;
            }
            expected.push(role.clone());
            if expected.len() == SERIES_ROLE_CAP {
                break;
            }
        }
        assert_eq!(selected, expected);
        assert!(selected.len() <= SERIES_ROLE_CAP);
    }

    #[test]
    fn missing_pack_fails_the_catalogue_visibly() {
        let empty = catalogue_list_from_load(Ok(RuleRegistry {
            rules_dir: "pack".into(),
            rules: Vec::new(),
        }));
        assert_eq!(empty["ok"], false, "{empty}");
        assert_eq!(empty["count"], 0, "{empty}");
        assert!(
            empty["error"]
                .as_str()
                .is_some_and(|msg| msg.contains("unavailable")),
            "{empty}"
        );
        let missing = catalogue_list_from_load(Err(
            "rule catalogue unavailable: read pack/registry.yaml".into(),
        ));
        assert_eq!(missing["ok"], false, "{missing}");
        assert!(missing["rules"]
            .as_array()
            .is_some_and(|rows| rows.is_empty()));
    }

    #[test]
    fn vav1_params_include_sliders() {
        let v = rule_params_response("VAV-1");
        assert_eq!(v["ok"], true, "{v}");
        assert!(v["params"]["zone_t_lo"]["control"].as_str().is_some());
    }

    #[test]
    fn cache_status_ok_shape() {
        let _env = crate::test_support::workspace_env_lock();
        let v = cache_status();
        assert_eq!(v["ok"], true);
        assert!(v.get("parquet_root").is_some());
    }

    #[test]
    fn equipment_response_lists_canonical_mqtt_hive() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!(
            "openfdd-equip-mqtt-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&tmp);
        let equip = tmp
            .join("history")
            .join("building_id=bldg2")
            .join("equipment_id=bldg2-zone-loopback")
            .join("year=2026")
            .join("month=09");
        std::fs::create_dir_all(&equip).unwrap();
        std::fs::write(equip.join("part-0.parquet"), b"PAR1").unwrap();
        let prev = std::env::var("OPENFDD_PARQUET_ROOT").ok();
        // Clear storage URL so parquet_root uses OPENFDD_PARQUET_ROOT.
        let prev_storage = std::env::var("OPENFDD_STORAGE_URL").ok();
        std::env::remove_var("OPENFDD_STORAGE_URL");
        std::env::set_var("OPENFDD_PARQUET_ROOT", &tmp);
        let body = equipment_response(Some("bldg2"));
        match prev {
            Some(v) => std::env::set_var("OPENFDD_PARQUET_ROOT", v),
            None => std::env::remove_var("OPENFDD_PARQUET_ROOT"),
        }
        match prev_storage {
            Some(v) => std::env::set_var("OPENFDD_STORAGE_URL", v),
            None => std::env::remove_var("OPENFDD_STORAGE_URL"),
        }
        let _ = std::fs::remove_dir_all(&tmp);
        assert_eq!(body["ok"], true);
        assert_eq!(body["count"], 1);
        assert_eq!(body["equipment"][0]["equipment_id"], "bldg2-zone-loopback");
    }

    struct RuleResultsDirGuard {
        _keep: tempfile::TempDir,
        prev: Option<String>,
    }

    impl RuleResultsDirGuard {
        fn new() -> Self {
            let tmp = tempfile::tempdir().expect("tempdir");
            let prev = std::env::var("OPENFDD_RULE_RESULTS_DIR").ok();
            std::env::set_var("OPENFDD_RULE_RESULTS_DIR", tmp.path());
            Self { _keep: tmp, prev }
        }
    }

    impl Drop for RuleResultsDirGuard {
        fn drop(&mut self) {
            match self.prev.take() {
                Some(v) => std::env::set_var("OPENFDD_RULE_RESULTS_DIR", v),
                None => std::env::remove_var("OPENFDD_RULE_RESULTS_DIR"),
            }
        }
    }

    #[test]
    fn chwplant_stamp_keeps_fault_instead_of_not_applicable() {
        let relabeled = displayed_result_status(
            Some("NOT_APPLICABLE_EQUIPMENT_TYPE"),
            2.0,
            Some(&["chiller".to_string()]),
            Some("chwPlant"),
        );
        assert_eq!(relabeled, "FAULT");
        let pass = displayed_result_status(
            Some("NOT_APPLICABLE"),
            0.0,
            Some(&["ahu".to_string()]),
            Some("ahu"),
        );
        assert_eq!(pass, "PASS");
        let missing = displayed_result_status(Some("FAULT"), 1.0, Some(&["ahu".to_string()]), None);
        assert_eq!(missing, "NOT_APPLICABLE_EQUIPMENT_TYPE");
    }

    fn sample_commit(
        building: &str,
        full_cohort: bool,
        equipment: &[(&str, &str)],
        rules: &[(&str, Value)],
    ) -> Value {
        commit_run_generation(&RunGenerationCommit {
            building_id: building.to_string(),
            full_cohort,
            equipment: equipment
                .iter()
                .map(|(id, kind)| RunModelEquipment {
                    equipment_id: (*id).to_string(),
                    equip_type: Some((*kind).to_string()),
                })
                .collect(),
            rules: rules
                .iter()
                .map(|(id, body)| RunRuleFile {
                    rule_id: (*id).to_string(),
                    body: body.clone(),
                })
                .collect(),
            config_fingerprint: "test-config".into(),
            window_start: Some("2026-07-01T00:00:00Z".into()),
            window_end: Some("2026-07-02T00:00:00Z".into()),
            watermark: Some("2026-07-01T12:00:00Z".into()),
            poll_seconds: 300.0,
            pack: json!({
                "contract_id": "openfdd-postgres-pack",
                "contract_version": "1",
                "compatible": true,
            }),
        })
        .expect("commit generation")
    }

    #[test]
    fn building50_result_files_are_not_all_not_applicable() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "BUILDING_50";
        sample_commit(
            building,
            true,
            &[("AHU_1", "ahu"), ("CHILLER_1", "chwPlant")],
            &[
                (
                    "FC1",
                    json!({"rows":[{"equipment_id":"AHU_1","fault_hours":1.5,"status":"NOT_APPLICABLE"}]}),
                ),
                (
                    "CHW-1",
                    json!({"rows":[{"equipment_id":"CHILLER_1","fault_hours":2.0,"status":"NOT_APPLICABLE_EQUIPMENT_TYPE"}]}),
                ),
                (
                    "AHU-SATDEV",
                    json!({"rows":[{"equipment_id":"AHU_1","fault_hours":0.0,"status":"PASS"}]}),
                ),
            ],
        );
        let mut types = BTreeMap::new();
        types.insert("AHU_1".into(), "ahu".into());
        types.insert("CHILLER_1".into(), "chwPlant".into());
        let body = results_response_with_types(Some(building), &types, "timescale_equipment");
        let results = body["results"].as_array().expect("results");
        assert!(!results.is_empty());
        assert!(
            results.iter().any(|row| {
                let status = row["status"].as_str().unwrap_or("");
                status == "PASS" || status == "FAULT"
            }),
            "{body}"
        );
        assert!(
            results.iter().all(|row| !row["status"]
                .as_str()
                .unwrap_or("")
                .contains("NOT_APPLICABLE")),
            "{body}"
        );
        let fc1 = results
            .iter()
            .find(|row| row["rule_id"] == "FC1" && row["equipment_id"] == "AHU_1")
            .expect("FC1");
        assert_eq!(fc1["status"], "FAULT");
        let chw = results
            .iter()
            .find(|row| row["rule_id"] == "CHW-1")
            .expect("CHW-1");
        assert_eq!(chw["status"], "FAULT");
        let ready = readiness_response(Some(building));
        assert_eq!(ready["result_count"], body["count"], "{ready} {body}");
    }

    #[test]
    fn readiness_never_run_is_not_clean() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "READINESS_NEVER_RUN";
        let v = readiness_response(Some(building));
        assert_eq!(v["ok"], true, "{v}");
        assert_eq!(v["clean"], false, "{v}");
        let reasons: Vec<String> = v["dirty_reasons"]
            .as_array()
            .expect("dirty_reasons array")
            .iter()
            .filter_map(|x| x.as_str().map(str::to_string))
            .collect();
        assert!(
            reasons.iter().any(|r| r == "never_run"),
            "expected never_run in {reasons:?}, full={v}"
        );
    }

    #[test]
    fn readiness_after_committed_generation_is_clean() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "READINESS_CLEAN";
        sample_commit(
            building,
            true,
            &[("AHU_1", "ahu"), ("AHU_2", "ahu")],
            &[(
                "FC1",
                json!({"rows":[
                    {"equipment_id":"AHU_1","fault_hours":0.0,"status":"PASS"},
                    {"equipment_id":"AHU_2","fault_hours":1.0,"status":"FAULT"}
                ]}),
            )],
        );
        let v = readiness_response(Some(building));
        assert_eq!(v["ok"], true, "{v}");
        assert_eq!(v["clean"], true, "{v}");
        assert_eq!(v["run_status"], "complete", "{v}");
        assert_eq!(v["result_count"], 2, "row count, not file count: {v}");
        let body = results_response(Some(building));
        assert_eq!(body["count"], v["result_count"], "{body}");
        assert!(
            v["dirty_reasons"].as_array().is_some_and(|a| a.is_empty()),
            "{v}"
        );
    }

    #[test]
    fn readiness_mark_building_dirty_is_not_clean() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "READINESS_DIRTY";
        sample_commit(
            building,
            true,
            &[("AHU_1", "ahu")],
            &[(
                "FC1",
                json!({"rows":[{"equipment_id":"AHU_1","fault_hours":0.0,"status":"PASS"}]}),
            )],
        );
        mark_building_results_dirty(building, "package_reimport");
        let v = readiness_response(Some(building));
        assert_eq!(v["ok"], true, "{v}");
        assert_eq!(v["clean"], false, "{v}");
        let reasons: Vec<String> = v["dirty_reasons"]
            .as_array()
            .expect("dirty_reasons array")
            .iter()
            .filter_map(|x| x.as_str().map(str::to_string))
            .collect();
        assert!(
            reasons.iter().any(|r| r == "package_reimport"),
            "expected package_reimport in {reasons:?}, full={v}"
        );
    }

    #[test]
    fn partial_run_is_not_current_and_skip_is_not_a_failure() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "RUN_PARTIAL";
        let committed = sample_commit(
            building,
            true,
            &[("AHU_1", "ahu")],
            &[
                (
                    "FC1",
                    json!({"rows":[{"equipment_id":"AHU_1","fault_hours":2.0,"status":"FAULT"}]}),
                ),
                (
                    "OAT-METEO",
                    json!({"rows":[{"equipment_id":"AHU_1","status":"ERROR","notes":"sql failed"}]}),
                ),
                (
                    "VAV-1",
                    json!({"rows":[{"status":"SKIP_NO_TARGETS","notes":"no vav in model"}]}),
                ),
            ],
        );
        assert_eq!(committed["run_status"], "partial", "{committed}");
        assert_eq!(committed["rules_succeeded"], 1, "{committed}");
        assert_eq!(committed["rules_failed"], 1, "{committed}");
        assert_eq!(committed["rules_skipped"], 1, "{committed}");
        assert_eq!(
            committed["rules_succeeded"].as_u64().unwrap()
                + committed["rules_failed"].as_u64().unwrap()
                + committed["rules_skipped"].as_u64().unwrap(),
            committed["rules_run"].as_u64().unwrap()
        );
        let ready = readiness_response(Some(building));
        assert_eq!(ready["clean"], false, "{ready}");
        assert_eq!(ready["run_status"], "partial", "{ready}");
        assert_ne!(ready["run_status"], "failed");
        let body = results_response(Some(building));
        assert_eq!(body["count"], ready["result_count"], "{body} {ready}");
        let error = body["results"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["rule_id"] == "OAT-METEO")
            .expect("error row");
        assert_eq!(error["status"], "ERROR");
        assert_ne!(error["status"], "PASS");
    }

    #[test]
    fn pack_states_stay_distinct_and_share_one_manifest() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "PACK_STATES";
        let committed = sample_commit(
            building,
            true,
            &[("EQ_A", "ahu"), ("EQ_V", "vav")],
            &[
                (
                    "ECON-6",
                    json!({"rows":[{
                        "equipment_id": "EQ_A",
                        "fault_hours": 0.5,
                        "status": "FAULT",
                        "failure_class": null
                    }]}),
                ),
                (
                    "ECON-3",
                    json!({"rows":[{
                        "equipment_id": "EQ_A",
                        "status": "SKIP_INPUT_MISSING",
                        "failure_class": "input_missing",
                        "input_condition": "absent",
                        "notes": "weather input missing"
                    }]}),
                ),
                (
                    "UTIL-INTERVAL",
                    json!({"rows":[{
                        "equipment_id": "EQ_A",
                        "status": "SKIP_UNSUPPORTED",
                        "failure_class": "unsupported",
                        "notes": "multiple utility equipment"
                    }]}),
                ),
                (
                    "VAV-1",
                    json!({"rows":[{
                        "status": "SCHEMA_INCOMPATIBLE",
                        "failure_class": "schema_incompatible",
                        "notes": "fdd.try_double is not installed"
                    }]}),
                ),
                (
                    "FC1",
                    json!({"rows":[{
                        "equipment_id": "EQ_A",
                        "status": "ERROR",
                        "failure_class": "runtime_failure",
                        "notes": "division by zero"
                    }]}),
                ),
            ],
        );
        assert_eq!(committed["rules_succeeded"], 1, "{committed}");
        assert_eq!(committed["rules_failed"], 2, "{committed}");
        assert_eq!(committed["rules_skipped"], 2, "{committed}");
        assert_eq!(committed["run_status"], "partial", "{committed}");
        assert_eq!(
            committed["rules_succeeded"].as_u64().unwrap()
                + committed["rules_failed"].as_u64().unwrap()
                + committed["rules_skipped"].as_u64().unwrap(),
            committed["rules_run"].as_u64().unwrap()
        );
        let run_id = committed["run_id"].as_str().expect("run id");
        let base = std::env::var("OPENFDD_RULE_RESULTS_DIR").expect("results dir");
        let manifest_path = PathBuf::from(base)
            .join(format!("building={building}"))
            .join("generations")
            .join(run_id)
            .join("manifest.json");
        assert!(manifest_path.is_file(), "one manifest at {manifest_path:?}");
        let manifest: Value =
            serde_json::from_str(&std::fs::read_to_string(&manifest_path).expect("manifest"))
                .expect("manifest json");
        assert_eq!(manifest["run_id"], committed["run_id"]);
        assert_eq!(manifest["pack"]["contract_id"], "openfdd-postgres-pack");
        let results = committed["results"].as_array().expect("results");
        let status = |rule: &str| {
            results
                .iter()
                .find(|row| row["rule_id"] == rule)
                .expect(rule)["status"]
                .as_str()
                .unwrap()
                .to_string()
        };
        assert_eq!(status("ECON-6"), "FAULT");
        assert_eq!(status("ECON-3"), "SKIP_INPUT_MISSING");
        assert_eq!(status("UTIL-INTERVAL"), "SKIP_UNSUPPORTED");
        assert_eq!(status("VAV-1"), "SCHEMA_INCOMPATIBLE");
        assert_eq!(status("FC1"), "ERROR");
        assert_ne!(status("VAV-1"), "PASS");
        assert_ne!(status("ECON-3"), "PASS");
    }

    #[test]
    fn failed_run_is_distinct_from_partial() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "RUN_FAILED";
        let committed = sample_commit(
            building,
            true,
            &[("AHU_1", "ahu")],
            &[(
                "FC1",
                json!({"rows":[{"equipment_id":"AHU_1","status":"ERROR","notes":"render"}]}),
            )],
        );
        assert_eq!(committed["run_status"], "failed", "{committed}");
        assert_eq!(committed["rules_succeeded"], 0);
        let ready = readiness_response(Some(building));
        assert_eq!(ready["clean"], false, "{ready}");
        assert_eq!(ready["run_status"], "failed", "{ready}");
        assert_eq!(
            ready["result_count"],
            results_response(Some(building))["count"]
        );
    }

    #[test]
    fn legacy_files_are_withheld_and_counts_agree() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "LEGACY_LOOSE";
        let dir = results_dir(Some(building));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(
            dir.join("VAV-1.json"),
            r#"{"rows":[{"equipment_id":"VAV_111","fault_hours":4.0,"status":"FAULT"}]}"#,
        )
        .unwrap();
        std::fs::write(
            dir.join("_run_meta.json"),
            r#"{"ok":true,"result_count":99}"#,
        )
        .unwrap();
        let body = results_response(Some(building));
        let ready = readiness_response(Some(building));
        assert_eq!(body["count"], 0, "{body}");
        assert_eq!(ready["result_count"], 0, "{ready}");
        assert_eq!(body["count"], ready["result_count"]);
        assert_eq!(ready["clean"], false, "{ready}");
        assert!(ready["dirty_reasons"]
            .as_array()
            .unwrap()
            .iter()
            .any(|reason| reason == "legacy_unmanifested"));
        assert!(dir.join("VAV-1.json").is_file(), "history file stays");
    }

    #[test]
    fn model_change_drops_obsolete_equipment_and_keeps_history() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "MODEL_SHIFT";
        let first = sample_commit(
            building,
            true,
            &[("AHU_1", "ahu"), ("VAV_111", "vav")],
            &[
                (
                    "FC1",
                    json!({"rows":[{"equipment_id":"AHU_1","fault_hours":1.0,"status":"FAULT"}]}),
                ),
                (
                    "VAV-1",
                    json!({"rows":[{"equipment_id":"VAV_111","fault_hours":3.0,"status":"FAULT"}]}),
                ),
            ],
        );
        let first_id = first["run_id"].as_str().unwrap().to_string();
        let second = sample_commit(
            building,
            true,
            &[("AHU_1", "ahu")],
            &[
                (
                    "FC1",
                    json!({"rows":[{"equipment_id":"AHU_1","fault_hours":1.0,"status":"PASS"}]}),
                ),
                ("VAV-1", json!({"rows":[{"status":"SKIP_NO_TARGETS"}]})),
            ],
        );
        assert_ne!(second["run_id"], first["run_id"]);
        let body = results_response(Some(building));
        assert!(
            body["results"]
                .as_array()
                .unwrap()
                .iter()
                .all(|row| row["equipment_id"] != "VAV_111"),
            "{body}"
        );
        let skip = body["results"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["rule_id"] == "VAV-1")
            .expect("skip replaces vav");
        assert_eq!(skip["status"], "SKIP_NO_TARGETS");
        let ready = readiness_response(Some(building));
        assert_eq!(ready["result_count"], body["count"], "{ready}");
        let old = results_dir(Some(building))
            .join("generations")
            .join(&first_id)
            .join("VAV-1.json");
        let old_body: Value = serde_json::from_str(&std::fs::read_to_string(old).unwrap()).unwrap();
        assert_eq!(old_body["rows"][0]["equipment_id"], "VAV_111");
        assert!(ready["history"]
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item["run_id"] == first_id && item["active"] == false));
    }

    #[test]
    fn single_rule_keeps_parent_provenance() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "SINGLE_RULE";
        let first = sample_commit(
            building,
            true,
            &[("AHU_1", "ahu"), ("AHU_2", "ahu")],
            &[
                (
                    "FC1",
                    json!({"rows":[
                        {"equipment_id":"AHU_1","fault_hours":1.0,"status":"FAULT"},
                        {"equipment_id":"AHU_2","fault_hours":0.0,"status":"PASS"}
                    ]}),
                ),
                (
                    "AHU-SATDEV",
                    json!({"rows":[{"equipment_id":"AHU_1","fault_hours":0.0,"status":"PASS"}]}),
                ),
            ],
        );
        let tuned = sample_commit(
            building,
            false,
            &[("AHU_1", "ahu"), ("AHU_2", "ahu")],
            &[(
                "FC1",
                json!({"rows":[{"equipment_id":"AHU_1","fault_hours":0.0,"status":"PASS"}]}),
            )],
        );
        assert_eq!(tuned["parent_run_id"], first["run_id"]);
        assert_eq!(tuned["cohort"], "derived");
        let body = results_response(Some(building));
        let rows = body["results"].as_array().unwrap();
        assert!(rows.iter().any(|row| row["rule_id"] == "AHU-SATDEV"));
        assert!(rows.iter().any(|row| {
            row["rule_id"] == "FC1" && row["equipment_id"] == "AHU_2" && row["status"] == "PASS"
        }));
        let ahu1 = rows
            .iter()
            .find(|row| row["rule_id"] == "FC1" && row["equipment_id"] == "AHU_1")
            .unwrap();
        assert_eq!(ahu1["fault_hours"], 0.0);
        let ready = readiness_response(Some(building));
        assert_eq!(ready["result_count"], body["count"]);
        assert_eq!(ready["clean"], true, "{ready}");
    }

    #[test]
    fn sites_do_not_share_a_generation() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        sample_commit(
            "SITE_A",
            true,
            &[("AHU_A", "ahu")],
            &[(
                "FC1",
                json!({"rows":[{"equipment_id":"AHU_A","fault_hours":1.0,"status":"FAULT"}]}),
            )],
        );
        sample_commit(
            "SITE_B",
            true,
            &[("AHU_B", "ahu")],
            &[(
                "FC1",
                json!({"rows":[{"equipment_id":"AHU_B","fault_hours":0.0,"status":"PASS"}]}),
            )],
        );
        let a = results_response(Some("SITE_A"));
        let b = results_response(Some("SITE_B"));
        assert!(a["results"]
            .as_array()
            .unwrap()
            .iter()
            .all(|row| row["equipment_id"] == "AHU_A"));
        assert!(b["results"]
            .as_array()
            .unwrap()
            .iter()
            .all(|row| row["equipment_id"] == "AHU_B"));
        assert_eq!(
            readiness_response(Some("SITE_A"))["result_count"],
            a["count"]
        );
    }

    #[test]
    fn metric_rows_keep_value_and_do_not_become_pass_zero() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "METRIC_ROWS";
        sample_commit(
            building,
            true,
            &[("ZONE_1", "zone_other")],
            &[
                (
                    "AVG-ZONE-TEMP",
                    json!({"rows":[{
                        "equipment_id":"ZONE_1",
                        "status":"METRIC",
                        "output_kind":"metric",
                        "sample_rows": 4,
                        "metric": {
                            "name": "avg_zone_temp",
                            "value": 72.5,
                            "unit": "degF",
                            "window": {"start": "2026-07-01T00:00:00Z", "end": "2026-07-02T00:00:00Z"},
                            "coverage": {"sample_rows": 4}
                        },
                        "values": {"avg_zone_temp": 72.5, "min_zone_temp": 70.0, "max_zone_temp": 75.0}
                    }]}),
                ),
                (
                    "ZONE-COMFORT-PCT",
                    json!({"rows":[{
                        "equipment_id":"ZONE_1",
                        "output_kind":"metric",
                        "comfort_pct": 88.0,
                        "sample_rows": 4
                    }]}),
                ),
            ],
        );
        let body = results_response(Some(building));
        let rows = body["results"].as_array().unwrap();
        let avg = rows
            .iter()
            .find(|row| row["rule_id"] == "AVG-ZONE-TEMP")
            .unwrap();
        assert_eq!(avg["status"], "METRIC");
        assert!(avg["fault_hours"].is_null(), "{avg}");
        assert_eq!(avg["metric"]["value"], 72.5);
        assert_eq!(avg["metric"]["unit"], "degF");
        assert_eq!(avg["metric"]["coverage"]["sample_rows"], 4);
        assert_eq!(avg["values"]["min_zone_temp"], 70.0);
        let comfort = rows
            .iter()
            .find(|row| row["rule_id"] == "ZONE-COMFORT-PCT")
            .unwrap();
        assert_eq!(comfort["status"], "METRIC", "{comfort}");
        assert_ne!(comfort["status"], "PASS");
        assert!(comfort["fault_hours"].is_null());
        assert_eq!(comfort["metric"]["value"], 88.0);
        assert_eq!(comfort["metric"]["unit"], "pct");
        let ready = readiness_response(Some(building));
        assert_eq!(ready["result_count"], 2);
        assert_eq!(ready["result_count"], body["count"]);
    }
}
