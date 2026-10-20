//! Wave-X Timescale registry API — no DataFusion SessionContext.
//! Registry-backed FDD API - loads `sql_rules/registry.yaml` via `fdd_rules`.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};

use fdd_rules::{load_registry, RuleRegistry, RuleSpec};
use serde_json::{json, Value};

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

const RUN_META_FILE: &str = "_run_meta.json";
const DIRTY_FILE: &str = "_dirty.json";

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

#[cfg(test)]
fn clear_building_dirty(building_id: Option<&str>) {
    let path = results_dir(building_id).join(DIRTY_FILE);
    let _ = std::fs::remove_file(path);
}

fn rule_set_hash() -> String {
    use sha2::{Digest, Sha256};
    let mut ids: Vec<String> = load_reg()
        .map(|r| r.rules.into_iter().map(|x| x.rule_id).collect())
        .unwrap_or_default();
    ids.sort();
    let mut hasher = Sha256::new();
    hasher.update(ids.join("|").as_bytes());
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
fn write_run_meta(building_id: Option<&str>, mode: &str, result_count: usize) {
    let dir = results_dir(building_id);
    let _ = std::fs::create_dir_all(&dir);
    let body = json!({
        "completed_at": chrono::Utc::now().to_rfc3339(),
        "mode": mode,
        "rule_set_hash": rule_set_hash(),
        "result_count": result_count,
    });
    let _ = std::fs::write(dir.join(RUN_META_FILE), body.to_string());
    if mode == "registry" || mode == "afdd" {
        clear_building_dirty(building_id);
    }
}

/// `GET /api/fdd/results/readiness` — clean/dirty for Overview one-shot grey-out.
pub fn readiness_response(building_id: Option<&str>) -> Value {
    let dir = results_dir(building_id);
    let meta_path = dir.join(RUN_META_FILE);
    let dirty_path = dir.join(DIRTY_FILE);
    let mut result_count = 0usize;
    if dir.is_dir() {
        if let Ok(rd) = std::fs::read_dir(&dir) {
            for ent in rd.flatten() {
                let path = ent.path();
                let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
                if !name.ends_with(".json") || name.starts_with('_') {
                    continue;
                }
                result_count += 1;
            }
        }
    }
    let meta: Option<Value> = std::fs::read_to_string(&meta_path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok());
    let dirty_body: Option<Value> = std::fs::read_to_string(&dirty_path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok());
    let mut dirty_reasons: Vec<String> = Vec::new();
    if let Some(d) = &dirty_body {
        if let Some(r) = d.get("reason").and_then(Value::as_str) {
            dirty_reasons.push(r.to_string());
        }
    }
    if meta.is_none() && result_count == 0 {
        dirty_reasons.push("never_run".into());
    } else if meta.is_none() && result_count > 0 {
        dirty_reasons.push("missing_meta".into());
    }
    if let Some(m) = &meta {
        let stored = m.get("rule_set_hash").and_then(Value::as_str).unwrap_or("");
        if !stored.is_empty() && stored != rule_set_hash() {
            dirty_reasons.push("rule_set_changed".into());
        }
    }
    let has_results = result_count > 0;
    let clean = has_results && meta.is_some() && dirty_reasons.is_empty();
    json!({
        "ok": true,
        "has_results": has_results,
        "clean": clean,
        "dirty_reasons": dirty_reasons,
        "completed_at": meta.as_ref().and_then(|m| m.get("completed_at").cloned()),
        "result_count": meta
            .as_ref()
            .and_then(|m| m.get("result_count").and_then(Value::as_u64))
            .unwrap_or(result_count as u64),
        "mode": meta.as_ref().and_then(|m| m.get("mode").cloned()),
    })
}

fn load_reg() -> Result<RuleRegistry, String> {
    let dir = sql_rules_dir();
    load_registry(&dir).map_err(|e| format!("load registry {}: {e}", dir.display()))
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
        "required_roles": rule.required_roles,
        "optional_roles": rule.optional_roles,
        "output_columns": rule.output_columns,
        "confirm_seconds": rule.confirm_seconds,
        "confirm_min": (rule.confirm_seconds as f64) / 60.0,
        "parity_status": rule.parity_status,
        "dashboard_wired": rule.dashboard_wired,
        "parameter_count": rule.parameters.len(),
        "aliases": rule.aliases,
    })
}

/// `GET /api/fdd/rules` - full registry catalog.
pub fn list_registry_rules() -> Value {
    match load_reg() {
        Ok(reg) => {
            let rules: Vec<Value> = reg.rules.iter().map(rule_summary).collect();
            json!({
                "ok": true,
                "rules_dir": reg.rules_dir,
                "count": rules.len(),
                "rules": rules,
            })
        }
        Err(e) => json!({"ok": false, "error": e, "count": 0, "rules": []}),
    }
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
            return Some(value.clamp(0.0, 100.0));
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

/// `GET /api/fdd/results` - normalized rows from the most recent registry run.
///
/// `building_id` reads from the site-scoped results dir so two buildings' runs
/// do not clobber one another.
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
    let dir = results_dir(building_id);
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
    let mut rows = Vec::new();
    if dir.is_dir() {
        let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
            .into_iter()
            .flatten()
            .filter_map(Result::ok)
            .map(|e| e.path())
            .filter(|p| {
                p.extension().and_then(|x| x.to_str()) == Some("json")
                    && p.file_name()
                        .and_then(|x| x.to_str())
                        .is_some_and(|n| !n.starts_with('_'))
            })
            .collect();
        files.sort();
        for path in files {
            let Some(rule_id) = path.file_stem().and_then(|x| x.to_str()) else {
                continue;
            };
            if rule_id.starts_with('_') {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(&path) else {
                continue;
            };
            let Ok(body) = serde_json::from_str::<Value>(&text) else {
                continue;
            };
            for row in body
                .get("rows")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                let equipment_id = row
                    .get("equipment_id")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown");
                let fault_hours = row
                    .get("fault_hours")
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0);
                // Emit status directly from the row when present (skip markers),
                // otherwise derive FAULT/PASS from fault_hours (OFDD-066).
                let stamped = stamped_types.get(equipment_id).map(String::as_str);
                let kind = crate::equipment_types::kind_for(equipment_id, stamped);
                let applies = if stamped.map(str::trim).is_some_and(|s| !s.is_empty()) {
                    kinds_by_rule
                        .get(rule_id)
                        .map(|k| rule_applies_to_kind(k, kind))
                        .unwrap_or(true)
                } else {
                    kinds_by_rule
                        .get(rule_id)
                        .map(|k| k.is_empty())
                        .unwrap_or(true)
                };
                let status = displayed_result_status(
                    row.get("status").and_then(Value::as_str),
                    fault_hours,
                    kinds_by_rule.get(rule_id).map(Vec::as_slice),
                    stamped,
                );
                let fault_hours = if applies { fault_hours } else { 0.0 };
                let missing_roles = row
                    .get("missing_roles")
                    .cloned()
                    .unwrap_or_else(|| json!([]));
                let type_source = if stamped.is_some() {
                    type_source_label
                } else {
                    "missing"
                };
                rows.push(json!({
                    "rule_id": rule_id,
                    "title": metadata.get(rule_id).cloned().unwrap_or_default(),
                    "equipment_id": equipment_id,
                    "equipment_type": crate::equipment_types::api_equipment_type_for(equipment_id, stamped),
                    "equipment_type_raw": stamped,
                    "equipment_type_source": type_source,
                    "status": status,
                    "fault_hours": fault_hours,
                    "fault_pct": derive_fault_pct(row),
                    "missing_roles": missing_roles,
                    "notes": row.get("notes").cloned().unwrap_or(Value::Null),
                }));
            }
        }
    }
    json!({"ok": true, "count": rows.len(), "results": rows})
}

/// `GET /api/afdd/scheduler/result-slices` — per-rule window hashes.
///
/// Stress compares slices that sit outside the cycle window before and after
/// a lookback upsert. The display `rows` array is not this proof: a full-file
/// rewrite would still publish a fresh `rows` list.
pub fn result_slice_report(building_id: Option<&str>) -> Value {
    let dir = results_dir(building_id);
    let mut rules = Vec::new();
    if dir.is_dir() {
        let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
            .into_iter()
            .flatten()
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| {
                path.extension().and_then(|ext| ext.to_str()) == Some("json")
                    && path
                        .file_name()
                        .and_then(|name| name.to_str())
                        .is_some_and(|name| !name.starts_with('_'))
            })
            .collect();
        files.sort();
        for path in files {
            let Some(rule_id) = path.file_stem().and_then(|name| name.to_str()) else {
                continue;
            };
            if rule_id.starts_with('_') {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(&path) else {
                continue;
            };
            let Ok(body) = serde_json::from_str::<Value>(&text) else {
                continue;
            };
            rules.push(json!({
                "rule_id": rule_id,
                "result_scope": body.get("result_scope").cloned().unwrap_or(Value::Null),
                "windows": fdd_store::rule_result_window_fingerprints(&body),
            }));
        }
    }
    json!({
        "ok": true,
        "building_id": building_id,
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
        assert!(v["count"].as_u64().unwrap_or(0) >= 19, "{v}");
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

    #[test]
    fn building50_result_files_are_not_all_not_applicable() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "BUILDING_50";
        let dir = results_dir(Some(building));
        std::fs::create_dir_all(&dir).expect("mkdir");
        std::fs::write(
            dir.join("FC1.json"),
            r#"{"rows":[{"equipment_id":"AHU_1","fault_hours":1.5,"status":"NOT_APPLICABLE"}]}"#,
        )
        .unwrap();
        std::fs::write(
            dir.join("CHW-1.json"),
            r#"{"rows":[{"equipment_id":"CHILLER_1","fault_hours":2.0,"status":"NOT_APPLICABLE_EQUIPMENT_TYPE"}]}"#,
        )
        .unwrap();
        std::fs::write(
            dir.join("AHU-SATDEV.json"),
            r#"{"rows":[{"equipment_id":"AHU_1","fault_hours":0.0,"status":"PASS"}]}"#,
        )
        .unwrap();
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
    fn readiness_after_run_meta_and_result_is_clean() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "READINESS_CLEAN";
        let scoped = results_dir(Some(building));
        std::fs::create_dir_all(&scoped).expect("mkdir results");
        std::fs::write(scoped.join("FC1.json"), b"{}").expect("write result");
        write_run_meta(Some(building), "registry", 1);
        let v = readiness_response(Some(building));
        assert_eq!(v["ok"], true, "{v}");
        assert_eq!(v["clean"], true, "{v}");
        assert!(
            v["dirty_reasons"].as_array().is_some_and(|a| a.is_empty()),
            "{v}"
        );
        assert_eq!(v["has_results"], true, "{v}");
    }

    #[test]
    fn readiness_mark_building_dirty_is_not_clean() {
        let _env = crate::test_support::workspace_env_lock();
        let _dir = RuleResultsDirGuard::new();
        let building = "READINESS_DIRTY";
        let scoped = results_dir(Some(building));
        std::fs::create_dir_all(&scoped).expect("mkdir results");
        std::fs::write(scoped.join("FC1.json"), b"{}").expect("write result");
        write_run_meta(Some(building), "registry", 1);
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
}
