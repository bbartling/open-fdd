//! Registry-backed FDD API — loads `sql_rules/registry.yaml` via `fdd_rules`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use fdd_rules::{
    effective_param_strings, load_registry, load_tuning_profiles, read_poll_from_cache,
    rule_params, run_all_rules_with_overrides, substitute_sql, RuleRegistry, RuleSpec, RunOptions,
};
use fdd_sql::{register_parquet_tree, register_weather_if_present, run_sql};
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

/// Map cookbook slider keys onto SQL registry parameter keys.
fn alias_ui_param_key<'a>(rule_id: &str, key: &'a str) -> &'a str {
    match (rule_id, key) {
        ("VAV-1", "zone_lo") => "zone_t_lo",
        ("VAV-1", "zone_hi") => "zone_t_hi",
        ("FC1", "duct_static_err") => "eps_dsp",
        (
            "SV-SPIKE",
            "spike_scale_temperature" | "spike_scale_humidity" | "spike_scale_pressure",
        ) => "spike_scale",
        _ => key,
    }
}

/// Persisted Lab / package params bag for one rule (aliases included).
fn session_rule_param_bag(rule: &RuleSpec) -> Option<serde_json::Map<String, Value>> {
    let wrap = crate::fdd::session_config::get_session_config();
    let params = wrap.get("config")?.get("params")?.as_object()?;
    let bag = params
        .get(&rule.rule_id)
        .or_else(|| rule.aliases.iter().find_map(|a| params.get(a)))?
        .as_object()?;
    Some(bag.clone())
}

/// Effective confirm_seconds after session_config confirm_min / confirm_seconds.
fn confirm_seconds_from_session_bag(rule: &RuleSpec, bag: &serde_json::Map<String, Value>) -> u32 {
    let mut confirm = rule.confirm_seconds;
    if let Some(cm) = bag.get("confirm_min").and_then(|v| v.as_f64()) {
        confirm = (cm * 60.0).round() as u32;
    }
    if let Some(cs) = bag.get("confirm_seconds").and_then(|v| v.as_f64()) {
        confirm = cs.round() as u32;
    }
    confirm
}

/// True when session bag carries confirm or other numeric overrides for this rule.
fn session_bag_has_overrides(bag: &serde_json::Map<String, Value>) -> bool {
    bag.iter().any(|(k, v)| {
        if k == "_ui" {
            return false;
        }
        v.as_f64().is_some()
    })
}

/// Fold session bag numbers into SQL placeholder map (same mapping as /api/fdd/run).
fn apply_session_bag_to_sql_params(
    rule: &RuleSpec,
    bag: &serde_json::Map<String, Value>,
    params: &mut HashMap<String, String>,
) {
    for (key, value) in bag {
        if key == "confirm_min" || key == "_ui" {
            continue;
        }
        let Some(mut number) = value.as_f64() else {
            continue;
        };
        let mut mapped = alias_ui_param_key(&rule.rule_id, key).to_string();
        if rule.rule_id == "FC1" && key == "fan_hi" {
            if bag.get("eps_vfd_spd").and_then(|v| v.as_f64()).is_some() {
                continue;
            }
            mapped = "eps_vfd_spd".into();
            number = (1.0 - number).clamp(0.0, 1.0);
        }
        if let Some(def) = rule.parameters.get(&mapped) {
            params.insert(def.sql_placeholder.clone(), number.to_string());
        } else if let Some(def) = rule.parameters.get(key) {
            params.insert(def.sql_placeholder.clone(), number.to_string());
        } else if let Some((_, def)) = rule
            .parameters
            .iter()
            .find(|(_, def)| def.sql_placeholder == *key || def.sql_placeholder == mapped)
        {
            params.insert(def.sql_placeholder.clone(), number.to_string());
        }
    }
}

fn parquet_root() -> PathBuf {
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

/// Results directory, optionally scoped to a building so per-site runs do not
/// overwrite each other. `None` → `.cache/rule_results`; `Some(id)` →
/// `.cache/rule_results/building={id}/`.
fn results_dir(building_id: Option<&str>) -> PathBuf {
    let base = match std::env::var("OPENFDD_RULE_RESULTS_DIR") {
        Ok(p) => PathBuf::from(p),
        Err(_) => PathBuf::from(".cache/rule_results"),
    };
    match building_id.map(str::trim).filter(|s| !s.is_empty()) {
        Some(bid) => base.join(format!("building={bid}")),
        None => base,
    }
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

/// `GET /api/fdd/rules` — full registry catalog.
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

/// `GET /api/fdd/rules/{id}/params` — tuning schema for one rule.
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

/// `GET /api/fdd/cache/status` — parquet ingest / results status.
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

fn infer_equipment_type(equipment_id: &str) -> &'static str {
    match infer_equipment_kind(equipment_id) {
        "vav" => "VAV",
        "ahu" => "AHU",
        "chiller" | "boiler" | "cooling_tower" => "PLANT",
        "heatpump" => "HEAT_PUMP",
        "weather" => "WEATHER",
        _ => "GENERAL",
    }
}

fn infer_equipment_kind(equipment_id: &str) -> &'static str {
    let id = equipment_id.to_ascii_uppercase();
    if id.contains("WEATHER") {
        "weather"
    } else if id.contains("VAV") || id.contains("ZONE") {
        "vav"
    } else if id.contains("AHU") || id.contains("RTU") || id.contains("MAU") {
        "ahu"
    } else if id.contains("CHILL") {
        "chiller"
    } else if id.contains("BOILER") {
        "boiler"
    } else if id.contains("TOWER") {
        "cooling_tower"
    } else if id.contains("HP") || id.contains("HEAT_PUMP") || id.contains("HEATPUMP") {
        "heatpump"
    } else {
        "unknown"
    }
}

fn rule_applies_to_kind(kinds: &[String], kind: &str) -> bool {
    if kinds.is_empty() || kind == "unknown" {
        return true;
    }
    kinds.iter().any(|k| k.eq_ignore_ascii_case(kind))
}

/// `GET /api/fdd/equipment` — equipment present in the parquet cache.
///
/// When `building_id` is set, only `building={id}/` is walked so a site's
/// equipment list is not polluted by other buildings (or `bench_*`) in the
/// shared cache.
pub fn equipment_response(building_id: Option<&str>) -> Value {
    let pq = parquet_root();
    let root = match building_id.map(str::trim).filter(|s| !s.is_empty()) {
        Some(bid) => pq.join(format!("building={bid}")),
        None => pq,
    };
    let mut ids = Vec::new();
    if root.is_dir() {
        for entry in walkdir::WalkDir::new(&root)
            .min_depth(1)
            .max_depth(3)
            .into_iter()
            .filter_map(Result::ok)
            .filter(|e| e.file_type().is_dir())
        {
            if let Some(id) = entry
                .file_name()
                .to_str()
                .and_then(|name| name.strip_prefix("equipment="))
            {
                ids.push(id.to_string());
            }
        }
    }
    ids.sort();
    ids.dedup();
    let stamped_types = crate::equipment_types::load_type_map(&parquet_root(), building_id);
    let equipment: Vec<Value> = ids
        .iter()
        .map(|id| {
            let stamped = stamped_types.get(id).map(String::as_str);
            crate::equipment_types::type_report(id, stamped)
        })
        .collect();
    json!({"ok": true, "count": equipment.len(), "equipment": equipment})
}

/// `GET /api/fdd/results` — normalized rows from the most recent registry run.
///
/// `building_id` reads from the site-scoped results dir so two buildings' runs
/// do not clobber one another.
pub fn results_response(building_id: Option<&str>) -> Value {
    let dir = results_dir(building_id);
    let stamped_types = crate::equipment_types::load_type_map(&parquet_root(), building_id);
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
            .filter(|p| p.extension().and_then(|x| x.to_str()) == Some("json"))
            .collect();
        files.sort();
        for path in files {
            let Some(rule_id) = path.file_stem().and_then(|x| x.to_str()) else {
                continue;
            };
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
                let applies = kinds_by_rule
                    .get(rule_id)
                    .map(|k| rule_applies_to_kind(k, kind))
                    .unwrap_or(true);
                let status = if !applies {
                    "NOT_APPLICABLE_EQUIPMENT_TYPE".to_string()
                } else {
                    row.get("status")
                        .and_then(Value::as_str)
                        .map(str::to_string)
                        .unwrap_or_else(|| {
                            if fault_hours > 0.0 { "FAULT" } else { "PASS" }.to_string()
                        })
                };
                let fault_hours = if applies { fault_hours } else { 0.0 };
                let missing_roles = row
                    .get("missing_roles")
                    .cloned()
                    .unwrap_or_else(|| json!([]));
                rows.push(json!({
                    "rule_id": rule_id,
                    "title": metadata.get(rule_id).cloned().unwrap_or_default(),
                    "equipment_id": equipment_id,
                    "equipment_type": crate::equipment_types::api_equipment_type_for(equipment_id, stamped),
                    "equipment_type_raw": stamped,
                    "equipment_type_source": if stamped.and_then(crate::equipment_types::canonical_kind).is_some() { "package" } else { "id" },
                    "status": status,
                    "fault_hours": fault_hours,
                    "fault_pct": row.get("fault_pct").and_then(Value::as_f64),
                    "missing_roles": missing_roles,
                    "notes": row.get("notes").cloned().unwrap_or(Value::Null),
                }));
            }
        }
    }
    json!({"ok": true, "count": rows.len(), "results": rows})
}

/// Roles used for FDD Plots series SELECT (required ∪ optional, SQL-safe).
///
/// Portable rules keep `required_roles` empty and put sensors in
/// `optional_roles`; Plots still need those columns or the UI shows
/// "No plottable series".
fn series_plot_columns(rule: &RuleSpec) -> Vec<&str> {
    let mut columns: Vec<&str> = rule
        .required_roles
        .iter()
        .chain(rule.optional_roles.iter())
        .map(String::as_str)
        .filter(|name| name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_'))
        .collect();
    columns.sort_unstable();
    columns.dedup();
    columns
}

/// Downsampled history series for one equipment/rule. Rule math continues to
/// use full-resolution parquet; only this display response is capped.
pub fn series_response(equipment_id: &str, rule_id: &str, building_id: Option<&str>) -> Value {
    let reg = match load_reg() {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let Some(rule) = reg
        .rules
        .iter()
        .find(|r| r.rule_id == rule_id || r.aliases.iter().any(|a| a == rule_id))
    else {
        return json!({"ok": false, "error": format!("unknown rule_id {rule_id}")});
    };
    let columns = series_plot_columns(rule);
    if columns.is_empty() {
        return json!({"ok": true, "equipment_id": equipment_id, "rule_id": rule.rule_id, "rows": [], "roles": []});
    }
    let escaped_equipment = equipment_id.replace('\'', "''");
    let root = parquet_root();
    let rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => return json!({"ok": false, "error": format!("runtime: {e}")}),
    };
    rt.block_on(async {
        let mut columns = columns;
        let ctx = datafusion::prelude::SessionContext::new();
        if let Err(e) = register_parquet_tree(&ctx, &root).await {
            return json!({"ok": false, "error": e.to_string()});
        }
        let _ = register_weather_if_present(&ctx, &root).await;
        // Prefer columns present on this equipment's history schema. Required
        // roles still hard-fail when missing; optional roles are skipped so
        // portable SV/PID rules can plot whatever is mapped.
        let history_columns: std::collections::HashSet<String> = match ctx.table("history").await {
            Ok(df) => df
                .schema()
                .fields()
                .iter()
                .map(|f| f.name().to_ascii_lowercase())
                .collect(),
            Err(_) => std::collections::HashSet::new(),
        };
        if !history_columns.is_empty() {
            let missing_required: Vec<String> = rule
                .required_roles
                .iter()
                .filter(|role| {
                    role.chars()
                        .all(|c| c.is_ascii_alphanumeric() || c == '_')
                        && !history_columns.contains(&role.to_ascii_lowercase())
                })
                .cloned()
                .collect();
            if !missing_required.is_empty() {
                return json!({
                    "ok": false,
                    "error": format!(
                        "missing roles for rule {}: {}",
                        rule.rule_id,
                        missing_required.join(", ")
                    ),
                    "missing_roles": missing_required,
                    "equipment_id": equipment_id,
                    "rule_id": rule.rule_id,
                    "rows": [],
                });
            }
            columns.retain(|c| history_columns.contains(&c.to_ascii_lowercase()));
        }
        if columns.is_empty() {
            return json!({
                "ok": true,
                "equipment_id": equipment_id,
                "rule_id": rule.rule_id,
                "rows": [],
                "roles": [],
            });
        }
        let sql = format!(
            "SELECT timestamp_utc, equipment_id, {} FROM history WHERE equipment_id = '{}' ORDER BY timestamp_utc LIMIT 5000",
            columns.join(", "),
            escaped_equipment
        );
        match run_sql(&ctx, &sql).await {
            Ok(mut result) => {
                // Overlay confirmed_fault for the FDD Plots swim lane (vibe19).
                // Registry JSON is equipment-level fault_hours only — when that
                // index is empty, re-run the rule SQL rewritten to a per-timestamp
                // confirmed series and join onto history rows.
                // When Lab session_config has overrides (e.g. confirm_min), always
                // recompute sql_detail with those params so Plots match Update rule.
                let session_bag = session_rule_param_bag(rule);
                let prefer_session_detail = session_bag
                    .as_ref()
                    .map(session_bag_has_overrides)
                    .unwrap_or(false);
                let mut fault_by_ts = if prefer_session_detail {
                    HashMap::new()
                } else {
                    load_confirmed_fault_index(equipment_id, &rule.rule_id, building_id)
                };
                let mut overlay_source = if fault_by_ts.is_empty() {
                    "none"
                } else {
                    "results"
                };
                if fault_by_ts.is_empty() {
                    if let Some(detail) = compute_confirmed_fault_series(
                        &ctx,
                        &reg,
                        rule,
                        equipment_id,
                        &root,
                        &history_columns,
                        session_bag.as_ref(),
                    )
                    .await
                    {
                        fault_by_ts = detail;
                        if !fault_by_ts.is_empty() {
                            overlay_source = if prefer_session_detail {
                                "sql_detail_session"
                            } else {
                                "sql_detail"
                            };
                        }
                    }
                }
                let mut overlay_hits = 0usize;
                if !fault_by_ts.is_empty() {
                    for row in &mut result.rows {
                        if let Some(obj) = row.as_object_mut() {
                            let ts = obj
                                .get("timestamp_utc")
                                .or_else(|| obj.get("timestamp"))
                                .and_then(|v| v.as_str())
                                .unwrap_or("");
                            if let Some(flag) = lookup_fault_flag(&fault_by_ts, ts) {
                                obj.insert("confirmed_fault".into(), json!(flag));
                                overlay_hits += 1;
                            }
                        }
                    }
                }
                json!({
                    "ok": true,
                    "equipment_id": equipment_id,
                    "equipment_type": infer_equipment_type(equipment_id),
                    "rule_id": rule.rule_id,
                    "roles": columns,
                    "rows": result.rows,
                    "downsampled": result.row_count >= 5000,
                    "max_points": 5000,
                    "has_confirmed_fault": overlay_hits > 0,
                    "fault_overlay_source": overlay_source,
                    "fault_overlay_hits": overlay_hits,
                    "building_id": building_id,
                })
            }
            Err(e) => {
                let msg = e.to_string();
                let lower = msg.to_ascii_lowercase();
                if lower.contains("no field named") || lower.contains("schema error") {
                    json!({
                        "ok": false,
                        "error": format!("missing roles for rule {}: {msg}", rule.rule_id),
                        "missing_roles": rule.required_roles,
                        "equipment_id": equipment_id,
                        "rule_id": rule.rule_id,
                        "rows": [],
                    })
                } else {
                    json!({"ok": false, "error": msg})
                }
            }
        }
    })
}

/// Normalize timestamp keys so series rows join fault overlays across slight
/// format drift (trim; `timestamp` vs `timestamp_utc`; fractional seconds;
/// `Z` vs `+00:00`).
fn normalize_ts_keys(raw: &str) -> Vec<String> {
    let s = raw.trim().to_string();
    if s.is_empty() {
        return Vec::new();
    }
    let mut keys: Vec<String> = Vec::new();
    fn push_unique(keys: &mut Vec<String>, k: String) {
        if !k.is_empty() && !keys.iter().any(|x| x == &k) {
            keys.push(k);
        }
    }
    push_unique(&mut keys, s.clone());
    // `T` vs space between date and time.
    if s.len() > 10 {
        let sep = s.as_bytes()[10];
        if sep == b'T' {
            push_unique(&mut keys, format!("{} {}", &s[..10], &s[11..]));
        } else if sep == b' ' {
            push_unique(&mut keys, format!("{}T{}", &s[..10], &s[11..]));
        }
    }
    // Optional trailing Z / +00:00 / -00:00.
    let snapshot = keys.clone();
    for k in snapshot {
        if k.ends_with('Z') {
            push_unique(&mut keys, k[..k.len() - 1].to_string());
            push_unique(&mut keys, format!("{}+00:00", &k[..k.len() - 1]));
        } else if let Some(stripped) = k
            .strip_suffix("+00:00")
            .or_else(|| k.strip_suffix("-00:00"))
        {
            push_unique(&mut keys, stripped.to_string());
            push_unique(&mut keys, format!("{stripped}Z"));
        } else if k.len() >= 19 && !k.contains('Z') && !k.contains('+') {
            // No zone suffix — add Z (date dashes are fine; `+` marks offsets).
            push_unique(&mut keys, format!("{k}Z"));
        }
    }
    // Strip fractional seconds (keep timezone suffix).
    let snapshot = keys.clone();
    for k in snapshot {
        if let Some(dot) = k.find('.') {
            let rest = &k[dot..];
            if let Some(rel) = rest.find(['Z', '+', '-']) {
                push_unique(&mut keys, format!("{}{}", &k[..dot], &rest[rel..]));
            } else {
                push_unique(&mut keys, k[..dot].to_string());
            }
        }
    }
    keys
}

/// Rewrite aggregated cookbook SQL (`final` ← `ranked` → `fault_hours`) into a
/// per-timestamp `confirmed_fault` series for one equipment (FDD Plots overlay).
///
/// Registry runs persist equipment-level `fault_hours` only; Plots need the
/// swim-lane bool joined onto history timestamps. Returns `None` for analytics
/// rollups / non-confirm SQL shapes.
fn rewrite_rule_sql_to_fault_series(sql: &str, equipment_id: &str) -> Option<String> {
    let sql = sql.trim().trim_end_matches(';');
    let lower = sql.to_ascii_lowercase();
    if !lower.contains("final as") || !lower.contains("from ranked") {
        return None;
    }
    if !lower.contains("fault_hours") {
        return None;
    }
    let final_at = lower.find("final as (")?;
    let select_at = lower.rfind("select")?;
    if select_at <= final_at {
        return None;
    }
    // Outer aggregate SELECT must be the trailing one after `final`.
    if !lower[select_at..].contains("fault_hours") {
        return None;
    }

    let mut head = sql[..select_at].to_string();
    // Inject timestamp_utc into the `final` CTE select list when missing.
    let head_lower = head.to_ascii_lowercase();
    if let Some(rel_final) = head_lower[final_at..].find("final as (") {
        let body_start = final_at + rel_final + "final as (".len();
        let body_slice = &head_lower[body_start..];
        // Only the final CTE body (until FROM ranked).
        let from_ranked = body_slice.find("from ranked")?;
        let final_body = &head_lower[body_start..body_start + from_ranked];
        if !final_body.contains("timestamp_utc") {
            // Insert after first `equipment_id,` inside final.
            if let Some(eq_rel) = final_body.find("equipment_id") {
                let abs = body_start + eq_rel;
                // Find comma after equipment_id (allow whitespace/newlines).
                let after = &head[abs..];
                if let Some(comma_rel) = after.find(',') {
                    let insert_at = abs + comma_rel + 1;
                    head.insert_str(insert_at, "\n    timestamp_utc,");
                }
            }
        }
    }

    let escaped = equipment_id.replace('\'', "''");
    Some(format!(
        "{head}SELECT equipment_id, timestamp_utc, confirmed AS confirmed_fault\n\
         FROM final\n\
         WHERE equipment_id = '{escaped}'\n\
         ORDER BY timestamp_utc"
    ))
}

/// Inject NULL columns for optional roles missing from history (CTE form).
fn sql_with_optional_null_roles_series(
    sql: &str,
    optional_roles: &[String],
    history_columns: &std::collections::HashSet<String>,
) -> String {
    let missing: Vec<String> = optional_roles
        .iter()
        .filter(|role| !history_columns.contains(&role.to_ascii_lowercase()))
        .cloned()
        .collect();
    if missing.is_empty() {
        return sql.to_string();
    }
    let null_cols: String = missing
        .iter()
        .map(|r| {
            let ty = if r.eq_ignore_ascii_case("occ_mode") {
                "VARCHAR"
            } else {
                "DOUBLE"
            };
            format!("CAST(NULL AS {ty}) AS \"{r}\"")
        })
        .collect::<Vec<_>>()
        .join(", ");
    let cte = format!("history_opt AS (SELECT history.*, {null_cols} FROM history)");
    let rewritten = sql
        .replace(" FROM history", " FROM history_opt")
        .replace(" from history", " from history_opt")
        .replace("\nFROM history", "\nFROM history_opt")
        .replace("\nfrom history", "\nfrom history_opt");
    if let Some(idx) = rewritten.find("WITH ") {
        let (pre, rest) = rewritten.split_at(idx);
        let rest = rest.trim_start_matches("WITH ");
        format!("{pre}WITH {cte}, {rest}")
    } else if let Some(idx) = rewritten.find("with ") {
        let (pre, rest) = rewritten.split_at(idx);
        let rest = rest.trim_start_matches("with ");
        format!("{pre}WITH {cte}, {rest}")
    } else {
        format!("WITH {cte} {rewritten}")
    }
}

/// Compute per-timestamp confirmed_fault by rewriting + running cookbook SQL.
async fn compute_confirmed_fault_series(
    ctx: &datafusion::prelude::SessionContext,
    reg: &RuleRegistry,
    rule: &RuleSpec,
    equipment_id: &str,
    parquet_root: &Path,
    history_columns: &std::collections::HashSet<String>,
    session_bag: Option<&serde_json::Map<String, Value>>,
) -> Option<HashMap<String, bool>> {
    let sql_path = Path::new(&reg.rules_dir).join(&rule.sql_file);
    let raw_sql = std::fs::read_to_string(&sql_path).ok()?;
    let detail = rewrite_rule_sql_to_fault_series(&raw_sql, equipment_id)?;
    let poll = read_poll_from_cache(parquet_root).unwrap_or(300.0);
    let confirm = session_bag
        .map(|bag| confirm_seconds_from_session_bag(rule, bag))
        .unwrap_or(rule.confirm_seconds);
    let mut params = rule_params(poll, confirm);
    if let Ok(tuning) = load_tuning_profiles(Path::new(&reg.rules_dir)) {
        if let Ok(tuned) = effective_param_strings(rule, &tuning, None, None, None) {
            for (k, v) in tuned {
                if k == "CONFIRM_SECONDS" || k == "CONFIRM_ROWS" {
                    continue;
                }
                params.insert(k, v);
            }
        }
    }
    // Catalog confirm defaults must not wipe session confirm_min.
    let confirm_params = rule_params(poll, confirm);
    for (k, v) in confirm_params {
        params.insert(k, v);
    }
    if let Some(bag) = session_bag {
        apply_session_bag_to_sql_params(rule, bag, &mut params);
        // Re-assert confirm after bag fold (confirm_seconds key may also be present).
        let confirm_params = rule_params(poll, confirm);
        for (k, v) in confirm_params {
            params.insert(k, v);
        }
    }
    let mut sql = substitute_sql(&detail, &params);
    sql = sql_with_optional_null_roles_series(&sql, &rule.optional_roles, history_columns);
    let result = run_sql(ctx, &sql).await.ok()?;
    let mut out = HashMap::new();
    for row in result.rows {
        let ts = row
            .get("timestamp_utc")
            .or_else(|| row.get("timestamp"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if ts.is_empty() {
            continue;
        }
        let flag = row
            .get("confirmed_fault")
            .and_then(|v| v.as_bool())
            .or_else(|| {
                row.get("confirmed_fault")
                    .and_then(|v| v.as_i64())
                    .map(|n| n != 0)
            })
            .or_else(|| {
                row.get("confirmed")
                    .and_then(|v| v.as_i64())
                    .map(|n| n != 0)
            });
        if let Some(f) = flag {
            for key in normalize_ts_keys(ts) {
                out.insert(key, f);
            }
        }
    }
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

fn lookup_fault_flag(map: &HashMap<String, bool>, ts: &str) -> Option<bool> {
    for key in normalize_ts_keys(ts) {
        if let Some(v) = map.get(&key) {
            return Some(*v);
        }
    }
    None
}

/// Map RFC3339 (or raw) timestamp → confirmed_fault bool from last rule result JSON.
fn load_confirmed_fault_index(
    equipment_id: &str,
    rule_id: &str,
    building_id: Option<&str>,
) -> HashMap<String, bool> {
    let mut out = HashMap::new();
    let mut paths: Vec<PathBuf> = Vec::new();
    // Prefer site-scoped results when building id is known.
    if let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) {
        paths.push(results_dir(Some(bid)).join(format!("{rule_id}.json")));
    }
    paths.push(results_dir(None).join(format!("{rule_id}.json")));
    // Scan building=*/{rule_id}.json under the results root.
    if let Ok(rd) = std::fs::read_dir(results_dir(None)) {
        for ent in rd.flatten() {
            let p = ent.path();
            if p.is_dir() {
                let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
                if name.starts_with("building=") {
                    let f = p.join(format!("{rule_id}.json"));
                    if f.is_file() {
                        paths.push(f);
                    }
                }
            }
        }
    }
    // Dedup while preserving order.
    let mut seen = std::collections::HashSet::new();
    paths.retain(|p| seen.insert(p.clone()));

    for path in paths {
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
            let eq = row
                .get("equipment_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if eq != equipment_id {
                continue;
            }
            let ts = row
                .get("timestamp_utc")
                .or_else(|| row.get("timestamp"))
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if ts.is_empty() {
                continue;
            }
            let flag = row
                .get("confirmed_fault")
                .and_then(|v| v.as_bool())
                .or_else(|| {
                    row.get("confirmed_fault")
                        .and_then(|v| v.as_i64())
                        .map(|n| n != 0)
                });
            if let Some(f) = flag {
                for key in normalize_ts_keys(ts) {
                    out.insert(key, f);
                }
            }
        }
        if !out.is_empty() {
            break;
        }
    }
    out
}

/// `GET /api/fdd/roles` — role map file if present.
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

/// `POST /api/fdd/run` body for registry engine (typed params only — no raw SQL).
///
/// ```json
/// { "mode": "registry", "rule_ids": ["FC1","VAV-1"], "params": { "FC1": { "confirm_min": 5 } },
///   "building_id": "BUILDING_100" }
/// ```
/// Omit `rule_ids` to run all. Pass ``building_id`` to scope history to
/// ``building={id}/`` (avoids bench_* bleed from other packages in the same cache).
/// Without parquet cache, returns a clear error.
pub fn run_registry(payload: &Value) -> Value {
    let pq = parquet_root();
    if !pq.is_dir() {
        return json!({
            "ok": false,
            "error": format!(
                "parquet cache missing at {} — set OPENFDD_PARQUET_ROOT or ingest a building package first",
                pq.display()
            ),
            "cache": cache_status(),
        });
    }
    let building_id = payload
        .get("building_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let (history_root, weather_root): (PathBuf, PathBuf) = match building_id {
        Some(bid) => {
            let scoped = pq.join(format!("building={bid}"));
            if !scoped.is_dir() {
                return json!({
                    "ok": false,
                    "error": format!(
                        "no parquet for building_id={bid} under {} — ingest that package first",
                        pq.display()
                    ),
                    "cache": cache_status(),
                    "building_id": bid,
                });
            }
            (scoped, pq.clone())
        }
        None => (pq.clone(), pq.clone()),
    };
    let reg = match load_reg() {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": e}),
    };

    let filter: Option<Vec<String>> = payload.get("rule_ids").and_then(|v| v.as_array()).map(|a| {
        a.iter()
            .filter_map(|x| x.as_str().map(str::to_string))
            .collect()
    });

    let filtered = if let Some(ids) = filter {
        let mut clone = reg.clone();
        clone.rules.retain(|r| {
            ids.iter()
                .any(|id| id == &r.rule_id || r.aliases.iter().any(|a| a == id))
        });
        clone
    } else {
        reg
    };

    if filtered.rules.is_empty() {
        return json!({"ok": false, "error": "no matching rules to run"});
    }

    // Normalize aliases and pass typed request overrides into the runner.
    let mut effective = filtered.clone();
    let mut session_overrides: HashMap<String, HashMap<String, f64>> = HashMap::new();
    if let Some(params_by_rule) = payload.get("params").and_then(|v| v.as_object()) {
        for rule in &mut effective.rules {
            let supplied = params_by_rule.get(&rule.rule_id).or_else(|| {
                rule.aliases
                    .iter()
                    .find_map(|alias| params_by_rule.get(alias))
            });
            if let Some(p) = supplied.and_then(|v| v.as_object()) {
                // UI vibe19 sliders store confirm_min (minutes). Always fold into
                // rule.confirm_seconds AND typed overrides so parameter-default
                // CONFIRM_SECONDS cannot wipe the slider (soak BUG-2).
                let mut confirm_override: Option<f64> = None;
                if let Some(cm) = p.get("confirm_min").and_then(|v| v.as_f64()) {
                    rule.confirm_seconds = (cm * 60.0).round() as u32;
                    confirm_override = Some(rule.confirm_seconds as f64);
                }
                if let Some(cs) = p.get("confirm_seconds").and_then(|v| v.as_f64()) {
                    rule.confirm_seconds = cs.round() as u32;
                    confirm_override = Some(rule.confirm_seconds as f64);
                }
                let mut typed = HashMap::new();
                for (key, value) in p {
                    if key == "confirm_min" {
                        continue;
                    }
                    let Some(mut number) = value.as_f64() else {
                        continue;
                    };
                    // FC1 legacy fan_hi (fan-on frac) → eps_vfd_spd = 1 - fan_hi
                    let mut mapped = alias_ui_param_key(&rule.rule_id, key).to_string();
                    if rule.rule_id == "FC1" && key == "fan_hi" {
                        if p.get("eps_vfd_spd").and_then(|v| v.as_f64()).is_some() {
                            continue;
                        }
                        mapped = "eps_vfd_spd".into();
                        number = (1.0 - number).clamp(0.0, 1.0);
                    }
                    if rule.parameters.contains_key(&mapped) {
                        typed.insert(mapped, number);
                    } else if rule.parameters.contains_key(key) {
                        typed.insert(key.clone(), number);
                    } else if let Some((param_key, _)) = rule.parameters.iter().find(|(_, def)| {
                        def.sql_placeholder == *key || def.sql_placeholder == mapped
                    }) {
                        typed.insert(param_key.clone(), number);
                    }
                }
                if let Some(cs) = confirm_override {
                    if rule.parameters.contains_key("confirm_seconds") {
                        typed.insert("confirm_seconds".into(), cs);
                    }
                }
                if !typed.is_empty() {
                    session_overrides.insert(rule.rule_id.clone(), typed);
                }
            }
        }
    }

    let out = results_dir(building_id);
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build();
    let rt = match rt {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": format!("runtime: {e}")}),
    };
    let session_units = crate::fdd::session_config::unit_system_from_session();
    let unit_system = payload
        .get("unit_system")
        .and_then(Value::as_str)
        .unwrap_or(session_units.as_str());
    // Continuous AFDD lookback (top-level or nested under params for older callers).
    let start_utc = payload
        .get("start_utc")
        .and_then(Value::as_str)
        .or_else(|| {
            payload
                .get("params")
                .and_then(|p| p.get("start_utc"))
                .and_then(Value::as_str)
        })
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let end_utc = payload
        .get("end_utc")
        .and_then(Value::as_str)
        .or_else(|| {
            payload
                .get("params")
                .and_then(|p| p.get("end_utc"))
                .and_then(Value::as_str)
        })
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let time_window = match (start_utc, end_utc) {
        (Some(start), Some(end)) => Some((start, end)),
        (None, None) => None,
        _ => {
            return json!({
                "ok": false,
                "error": "AFDD time window requires both start_utc and end_utc",
            });
        }
    };
    match rt.block_on(run_all_rules_with_overrides(
        &history_root,
        &effective,
        &out,
        &session_overrides,
        RunOptions {
            equipment_filter: payload.get("equipment_id").and_then(Value::as_str),
            weather_root: Some(weather_root.as_path()),
            unit_system: Some(unit_system),
            time_window,
        },
    )) {
        Ok(report) => {
            let normalized = results_response(building_id);
            json!({
                "ok": true,
                "engine": "fdd_rules+DataFusion",
                "mode": "registry",
                "building_id": building_id,
                "history_root": history_root.display().to_string(),
                "start_utc": time_window.map(|(s, _)| s),
                "end_utc": time_window.map(|(_, e)| e),
                "rules_run": report.rules_run,
                "rules_succeeded": report.rules_succeeded,
                "rules_failed": report.rules_failed,
                "rules_skipped": report.rules_skipped,
                "poll_seconds": report.poll_seconds,
                "total_ms": report.total_ms,
                "timings": report.timings,
                "results_dir": out.display().to_string(),
                "results": normalized.get("results").cloned().unwrap_or_else(|| json!([])),
            })
        }
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

/// Preview substituted SQL for a rule (integrator lab only — not operator UI).
pub fn preview_sql(rule_id: &str, overrides: &Value) -> Value {
    let reg = match load_reg() {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let Some(rule) = reg.rules.iter().find(|r| r.rule_id == rule_id) else {
        return json!({"ok": false, "error": format!("unknown rule_id {rule_id}")});
    };
    let sql_path = Path::new(&reg.rules_dir).join(&rule.sql_file);
    let raw = match std::fs::read_to_string(&sql_path) {
        Ok(s) => s,
        Err(e) => return json!({"ok": false, "error": e.to_string()}),
    };
    let poll = overrides
        .get("poll_seconds")
        .and_then(|v| v.as_f64())
        .unwrap_or(300.0);
    let mut confirm = rule.confirm_seconds;
    if let Some(cm) = overrides.get("confirm_min").and_then(|v| v.as_f64()) {
        confirm = (cm * 60.0).round() as u32;
    }
    if let Some(cs) = overrides.get("confirm_seconds").and_then(|v| v.as_u64()) {
        confirm = cs as u32;
    }
    let mut params = rule_params(poll, confirm);
    if let Ok(tuning) = load_tuning_profiles(Path::new(&reg.rules_dir)) {
        if let Ok(tuned) = effective_param_strings(rule, &tuning, None, None, None) {
            for (k, v) in tuned {
                params.insert(k, v);
            }
        }
    }
    if let Some(obj) = overrides.as_object() {
        for (k, v) in obj {
            if let Some(n) = v.as_f64() {
                // Map param keys to SQL placeholders when present on the rule.
                if let Some(def) = rule.parameters.get(k) {
                    params.insert(def.sql_placeholder.clone(), n.to_string());
                }
            }
        }
    }
    let sql = substitute_sql(&raw, &params);
    json!({
        "ok": true,
        "rule_id": rule_id,
        "params": params.into_iter().collect::<HashMap<_,_>>(),
        "sql": sql,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn series_plot_columns_unions_optional_roles_for_portable_rules() {
        let reg = load_reg().expect("registry");
        let pid = reg
            .rules
            .iter()
            .find(|r| r.rule_id == "PID-HUNT-1")
            .expect("PID-HUNT-1");
        assert!(
            pid.required_roles.is_empty(),
            "PID-HUNT-1 should keep required_roles empty"
        );
        let cols = series_plot_columns(pid);
        assert!(
            cols.iter()
                .any(|c| *c == "oa_damper_pct" || *c == "damper_pct"),
            "expected optional AO roles in plot columns, got {cols:?}"
        );
        let sv = reg
            .rules
            .iter()
            .find(|r| r.rule_id == "SV-FLATLINE")
            .expect("SV-FLATLINE");
        let sv_cols = series_plot_columns(sv);
        assert!(
            !sv_cols.is_empty(),
            "SV-FLATLINE must expose optional sensor roles for Plots"
        );
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
    fn confirmed_fault_index_reads_building_scoped_results() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!(
            "openfdd-fault-idx-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&tmp);
        let building_dir = tmp.join("building=BUILDING_100");
        std::fs::create_dir_all(&building_dir).unwrap();
        let payload = json!({
            "rows": [{
                "equipment_id": "AHU_1",
                "timestamp": " 2024-01-01T00:00:00.000Z ",
                "confirmed_fault": true
            }]
        });
        std::fs::write(
            building_dir.join("FC1.json"),
            serde_json::to_string(&payload).unwrap(),
        )
        .unwrap();
        let prev = std::env::var("OPENFDD_RULE_RESULTS_DIR").ok();
        std::env::set_var("OPENFDD_RULE_RESULTS_DIR", &tmp);
        let idx = load_confirmed_fault_index("AHU_1", "FC1", Some("BUILDING_100"));
        match prev {
            Some(v) => std::env::set_var("OPENFDD_RULE_RESULTS_DIR", v),
            None => std::env::remove_var("OPENFDD_RULE_RESULTS_DIR"),
        }
        let _ = std::fs::remove_dir_all(&tmp);
        assert!(
            idx.values().any(|v| *v),
            "expected confirmed_fault true in index, got {idx:?}"
        );
    }

    #[test]
    fn rewrite_fc1_sql_emits_confirmed_fault_series() {
        let raw = std::fs::read_to_string("sql_rules/fc1_duct_static_low.sql")
            .or_else(|_| std::fs::read_to_string("../sql_rules/fc1_duct_static_low.sql"))
            .expect("fc1 sql");
        let out = rewrite_rule_sql_to_fault_series(&raw, "AHU_1").expect("rewrite");
        let lower = out.to_ascii_lowercase();
        assert!(lower.contains("confirmed as confirmed_fault"), "{out}");
        assert!(lower.contains("timestamp_utc"), "{out}");
        assert!(
            lower.contains("where equipment_id = 'ahu_1'")
                || lower.contains("where equipment_id = 'AHU_1'"),
            "{out}"
        );
        assert!(!lower.contains("fault_hours"), "{out}");
        assert!(lower.contains("from final"), "{out}");
    }

    #[test]
    fn rewrite_skips_analytics_rollups() {
        let raw =
            "SELECT equipment_id, AVG(zone_t) AS avg_zone_temp FROM history GROUP BY equipment_id";
        assert!(rewrite_rule_sql_to_fault_series(raw, "VAV_1").is_none());
    }

    #[test]
    fn normalize_ts_keys_strips_fractional_seconds() {
        let keys = normalize_ts_keys("2024-01-01T00:00:00.123Z");
        assert!(keys.contains(&"2024-01-01T00:00:00.123Z".to_string()));
        assert!(keys.contains(&"2024-01-01T00:00:00Z".to_string()));
    }

    #[test]
    fn normalize_ts_keys_joins_t_vs_space() {
        let from_space = normalize_ts_keys("2024-01-01 00:00:00");
        assert!(from_space.iter().any(|k| k.starts_with("2024-01-01T")));
        let idx = {
            let mut m = HashMap::new();
            for k in normalize_ts_keys("2024-01-01T00:00:00.000Z") {
                m.insert(k, true);
            }
            m
        };
        assert_eq!(
            lookup_fault_flag(&idx, "2024-01-01 00:00:00"),
            Some(true),
            "T vs space + fractional seconds must join"
        );
    }

    #[test]
    fn normalize_ts_keys_joins_plus_zero_offset() {
        let idx = {
            let mut m = HashMap::new();
            for k in normalize_ts_keys("2024-01-01T00:00:00+00:00") {
                m.insert(k, true);
            }
            m
        };
        assert_eq!(
            lookup_fault_flag(&idx, "2024-01-01T00:00:00Z"),
            Some(true),
            "+00:00 must join to Z"
        );
    }
}
