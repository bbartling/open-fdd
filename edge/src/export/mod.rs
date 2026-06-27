//! Spreadsheet-friendly CSV exports for historian, faults, model, rules, and validation runs.

use crate::fdd::execution;
use crate::fdd::rules;
use crate::historian::store;
use chrono::{DateTime, Local, Utc};
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::env;
use std::fs;

const DEFAULT_EQUIPMENT: &str = "equip:validation";
const CONFIRMATION_SECONDS: i64 = 300;

pub const VALIDATION_RUNS_CSV_HEADER: &str = "timestamp_utc,sample_index,api_health_ok,fdd_sql_ok,smoke_device_instance,expected_phase,raw_fault_count,confirmed_fault_count,data_source,demo_only,artifact_dir";

pub const HISTORIAN_CSV_HEADER: &str = "timestamp_utc,timestamp_local,timezone,site_id,building_id,equipment_id,source_protocol,device_id,point_id,point_name,value,units,quality,source_path,data_source_label";

pub const FAULTS_CSV_HEADER: &str = "timestamp_utc,timestamp_local,site_id,building_id,equipment_id,rule_id,rule_name,raw_fault,confirmed_fault,minutes_in_fault,confirmation_required_minutes,clear_state,source_protocol,point_inputs,data_source_label";

pub const MODEL_POINTS_CSV_HEADER: &str = "site_id,building_id,equipment_id,equipment_name,point_id,point_name,source_protocol,source_device,source_object,units,haystack_tags,role,mapped,rule_inputs,data_source_label";

pub const RULES_CSV_HEADER: &str = "rule_id,rule_name,severity,review_status,confirmation_seconds,clear_behavior,required_inputs,optional_inputs,sql,data_source_label";

fn fdd_eval_from_historian() -> Value {
    let sql = "SELECT timestamp, equipment_id, oa_t, CASE WHEN oa_t IS NULL THEN false WHEN oa_t < 40.0 OR oa_t > 110.0 THEN true ELSE false END AS raw_fault FROM telemetry_pivot";
    execution::run_rule_sql_from_historian(sql, CONFIRMATION_SECONDS, &json!({}))
}

fn default_equipment(rows: &[Value]) -> String {
    rows.first()
        .and_then(|r| r.get("equipment_id").and_then(|v| v.as_str()))
        .unwrap_or(DEFAULT_EQUIPMENT)
        .to_string()
}

#[derive(Default, Clone)]
pub struct ExportQuery {
    pub start: Option<String>,
    pub end: Option<String>,
    pub site_id: Option<String>,
    pub building_id: Option<String>,
    pub equipment_id: Option<String>,
    pub source_protocol: Option<String>,
    pub hours: Option<i64>,
}

pub fn parse_query(query: &str) -> ExportQuery {
    let mut q = ExportQuery::default();
    for pair in query.split('&') {
        let Some((k, v)) = pair.split_once('=') else {
            continue;
        };
        let v = url_decode(v);
        match k {
            "start" => q.start = Some(v),
            "end" => q.end = Some(v),
            "site_id" => q.site_id = Some(v),
            "building_id" => q.building_id = Some(v),
            "equipment_id" => q.equipment_id = Some(v),
            "source_protocol" | "protocol" => q.source_protocol = Some(v),
            "hours" => q.hours = v.parse().ok(),
            _ => {}
        }
    }
    q
}

fn url_decode(raw: &str) -> String {
    let mut out = String::new();
    let bytes = raw.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'+' {
            out.push(' ');
            i += 1;
        } else if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(v) =
                u8::from_str_radix(std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap_or(""), 16)
            {
                out.push(v as char);
            }
            i += 3;
        } else {
            out.push(bytes[i] as char);
            i += 1;
        }
    }
    out
}

pub fn export_filename(prefix: &str) -> String {
    let now = Local::now();
    format!("openfdd_{}_{}.csv", prefix, now.format("%Y%m%d_%H%M"))
}

pub fn meta_json() -> Value {
    let historian_rows = store::load_pivot_rows().unwrap_or_default();
    let historian_count = historian_rows.len();
    let data_label = historian_data_label(&historian_rows);
    let validation_logs = store::workspace_dir().join("logs");
    let validation_artifacts = fs::read_dir(&validation_logs)
        .map(|rd| {
            rd.filter_map(|e| e.ok()).any(|e| {
                e.file_name()
                    .to_string_lossy()
                    .starts_with("live_fdd_validation")
            })
        })
        .unwrap_or(false);
    json!({
        "ok": true,
        "exports": [
            {
                "id": "historian",
                "label": "Historian time series",
                "format": "csv",
                "path": "/api/export/historian.csv",
                "row_count": historian_count.saturating_mul(4),
                "available": historian_count > 0,
                "data_source_label": data_label
            },
            {
                "id": "faults",
                "label": "Fault results",
                "format": "csv",
                "path": "/api/export/faults.csv",
                "row_count": fault_row_estimate(&historian_rows),
                "available": historian_count > 0,
                "data_source_label": data_label
            },
            {
                "id": "fault-summary",
                "label": "Fault summary",
                "format": "csv",
                "path": "/api/export/faults.csv?summary=1",
                "row_count": if historian_count > 0 { 1 } else { 0 },
                "available": historian_count > 0,
                "data_source_label": data_label
            },
            {
                "id": "bacnet-overrides",
                "label": "BACnet override report",
                "format": "csv",
                "path": "/api/bacnet/overrides/export",
                "available": true
            },
            {
                "id": "model-points",
                "label": "Data model point list",
                "format": "csv",
                "path": "/api/export/model-points.csv",
                "available": true,
                "data_source_label": "model/assignments"
            },
            {
                "id": "rules",
                "label": "Rule definitions",
                "format": "csv",
                "path": "/api/export/rules.csv",
                "requires_role": "integrator|agent",
                "available": true,
                "data_source_label": "fdd_wires/rules"
            },
            {
                "id": "validation-runs",
                "label": "Live FDD validation summaries",
                "format": "csv",
                "path": "/api/export/validation-runs.csv",
                "available": validation_artifacts,
                "data_source_label": "validation/smoke"
            },
            {
                "id": "import-jobs",
                "label": "Import job reports",
                "format": "csv",
                "path": "/api/export/import-jobs.csv",
                "available": crate::import::jobs_exist(),
                "data_source_label": "import/jobs"
            }
        ],
        "filters": {
            "sites": ["site:demo"],
            "buildings": ["building:main"],
            "protocols": list_protocols(&historian_rows),
            "equipment": list_equipment(&historian_rows)
        },
        "xlsx_supported": false,
        "xlsx_note": "CSV exports are available now; XLSX tracked in GitHub issue #367."
    })
}

fn historian_data_label(rows: &[Value]) -> String {
    if rows.is_empty() {
        return "empty".to_string();
    }
    let mut sim = 0;
    let mut live = 0;
    let mut demo = 0;
    for row in rows {
        match row.get("source").and_then(|v| v.as_str()).unwrap_or("") {
            s if s.starts_with("simulation:") => sim += 1,
            s if s.contains("demo") => demo += 1,
            s if s.starts_with("bacnet:live") => live += 1,
            _ if row.get("is_simulated").and_then(|v| v.as_bool()) == Some(true) => sim += 1,
            _ => live += 1,
        }
    }
    if demo > 0 {
        "DEMO ONLY — not live historian".to_string()
    } else if sim > 0 && live == 0 {
        "simulation:live_fdd_validation".to_string()
    } else if live > 0 {
        "historian/live".to_string()
    } else {
        "historian/mixed".to_string()
    }
}

fn list_protocols(rows: &[Value]) -> Vec<String> {
    let mut set = BTreeSet::new();
    for row in rows {
        if let Some(p) = row.get("source_driver").and_then(|v| v.as_str()) {
            set.insert(p.to_string());
        }
    }
    set.insert("bacnet".into());
    set.into_iter().collect()
}

fn list_equipment(rows: &[Value]) -> Vec<String> {
    let mut set = BTreeSet::new();
    for row in rows {
        if let Some(e) = row.get("equipment_id").and_then(|v| v.as_str()) {
            set.insert(e.to_string());
        }
    }
    set.insert(DEFAULT_EQUIPMENT.into());
    set.into_iter().collect()
}

fn fault_row_estimate(rows: &[Value]) -> u64 {
    if rows.is_empty() {
        0
    } else {
        rows.len() as u64
    }
}

pub fn historian_csv(query: &ExportQuery) -> String {
    let rows = filtered_historian_rows(query);
    let label = historian_data_label(&rows);
    let path = store::pivot_jsonl_path().display().to_string();
    let mut out = String::from(HISTORIAN_CSV_HEADER);
    out.push('\n');
    let site = query.site_id.as_deref().unwrap_or("site:demo");
    let building = query.building_id.as_deref().unwrap_or("building:main");
    for row in rows {
        let ts = row.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
        let (utc, local, tz) = format_timestamps(ts);
        let equip = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or(DEFAULT_EQUIPMENT);
        let protocol = row
            .get("source_driver")
            .and_then(|v| v.as_str())
            .unwrap_or("bacnet");
        let device = row
            .get("source_device")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let quality = if row.get("is_simulated").and_then(|v| v.as_bool()) == Some(true) {
            "simulated"
        } else if label.contains("DEMO") {
            "demo"
        } else {
            "good"
        };
        for (point_id, point_name, value, unit) in pivot_point_values(&row) {
            out.push_str(&csv_row(&[
                utc.clone(),
                local.clone(),
                tz.clone(),
                site.to_string(),
                building.to_string(),
                equip.to_string(),
                protocol.to_string(),
                device.clone(),
                point_id,
                point_name,
                value,
                unit,
                quality.to_string(),
                path.clone(),
                label.clone(),
            ]));
            out.push('\n');
        }
    }
    out
}

fn pivot_point_values(row: &Value) -> Vec<(String, String, String, String)> {
    vec![
        (
            "oa_t".into(),
            "Outside Air Temp".into(),
            fmt_f64(row.get("oa_t")),
            "degF".into(),
        ),
        (
            "oa_h".into(),
            "Outside Air Humidity".into(),
            fmt_f64(row.get("oa_h")),
            "%RH".into(),
        ),
        (
            "duct_t".into(),
            "Discharge Air Temp".into(),
            fmt_f64(row.get("duct_t")),
            "degF".into(),
        ),
        (
            "zn_t".into(),
            "Zone Temp".into(),
            fmt_f64(row.get("zn_t")),
            "degF".into(),
        ),
    ]
}

pub fn faults_csv(query: &ExportQuery, summary: bool) -> String {
    let rows = filtered_historian_rows(query);
    let label = historian_data_label(&rows);
    if rows.is_empty() {
        return format!("{FAULTS_CSV_HEADER}\n");
    }
    let eval = fdd_eval_from_historian();
    let eval_rows = eval
        .get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    if summary {
        let mut raw = 0;
        let mut confirmed = 0;
        for r in &eval_rows {
            if r.get("raw_fault").and_then(|v| v.as_bool()) == Some(true) {
                raw += 1;
            }
            if r.get("confirmed_fault").and_then(|v| v.as_bool()) == Some(true) {
                confirmed += 1;
            }
        }
        return format!(
            "{FAULTS_CSV_HEADER}\n{}",
            csv_row(&[
                Utc::now().to_rfc3339(),
                Local::now().format("%Y-%m-%d %H:%M:%S").to_string(),
                "site:demo".into(),
                "building:main".into(),
                default_equipment(&rows),
                "oa_temp_out_of_range".into(),
                "OA Temperature Out Of Range".into(),
                if raw > 0 { "true" } else { "false" }.into(),
                if confirmed > 0 { "true" } else { "false" }.into(),
                "0".into(),
                "5".into(),
                if confirmed > 0 { "latched" } else { "normal" }.into(),
                "bacnet".into(),
                "oa_t".into(),
                label.clone(),
            ])
        );
    }
    let mut out = String::from(FAULTS_CSV_HEADER);
    out.push('\n');
    for row in eval_rows {
        let ts = row.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
        let (utc, local, _) = format_timestamps(ts);
        let raw = row
            .get("raw_fault")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        let confirmed = row
            .get("confirmed_fault")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        let minutes = row
            .get("minutes_in_fault")
            .map(|v| v.to_string())
            .unwrap_or_else(|| "0".into());
        let confirm_min = row
            .get("confirmation_required_minutes")
            .map(|v| v.to_string())
            .unwrap_or_else(|| "5".into());
        out.push_str(&csv_row(&[
            utc,
            local,
            "site:demo".into(),
            "building:main".into(),
            row.get("equipment_id")
                .and_then(|v| v.as_str())
                .unwrap_or(DEFAULT_EQUIPMENT)
                .into(),
            "oa_temp_out_of_range".into(),
            "OA Temperature Out Of Range".into(),
            raw.to_string(),
            confirmed.to_string(),
            minutes,
            confirm_min,
            if raw && !confirmed {
                "raw_only".into()
            } else if confirmed {
                "confirmed".into()
            } else {
                "normal".into()
            },
            "bacnet".into(),
            "oa_t".into(),
            label.clone(),
        ]));
        out.push('\n');
    }
    out
}

pub fn model_points_csv() -> String {
    let assignments = crate::model::assignments::load_assignments_value();
    let label = "model/assignments".to_string();
    let mut out = String::from(MODEL_POINTS_CSV_HEADER);
    out.push('\n');
    if let Some(points) = assignments.get("points").and_then(|v| v.as_array()) {
        for point in points {
            let haystack_id = point
                .get("haystack_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let equip = point
                .get("equip_ref")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let (protocol, device, object) = first_driver_binding(point);
            let rule_inputs = rule_inputs_for_point(haystack_id, &assignments);
            out.push_str(&csv_row(&[
                "site:demo".into(),
                "building:main".into(),
                equip.replace("equip:", ""),
                point
                    .get("dis")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                haystack_id.into(),
                point
                    .get("dis")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                protocol,
                device,
                object,
                point
                    .get("unit")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                haystack_id.into(),
                point
                    .get("kind")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                "true".into(),
                rule_inputs,
                label.clone(),
            ]));
            out.push('\n');
        }
    }
    out
}

pub fn rules_csv() -> String {
    let listed = rules::list_rules();
    let label = "fdd_wires/rules".to_string();
    let mut out = String::from(RULES_CSV_HEADER);
    out.push('\n');
    if let Some(items) = listed.get("rules").and_then(|v| v.as_array()) {
        for rule in items {
            let req = rule
                .get("required_inputs")
                .and_then(|v| v.as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|v| v.as_str())
                        .collect::<Vec<_>>()
                        .join(";")
                })
                .unwrap_or_default();
            let opt = rule
                .get("optional_inputs")
                .and_then(|v| v.as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|v| v.as_str())
                        .collect::<Vec<_>>()
                        .join(";")
                })
                .unwrap_or_default();
            let sql = rule
                .get("sql")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .replace('\n', " ");
            out.push_str(&csv_row(&[
                rule.get("rule_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                rule.get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                rule.get("severity")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                rule.get("review_status")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                rule.get("confirmation_seconds")
                    .map(|v| v.to_string())
                    .unwrap_or_default(),
                rule.get("clear_behavior")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                req,
                opt,
                sql,
                label.clone(),
            ]));
            out.push('\n');
        }
    }
    out
}

pub fn validation_runs_csv(_query: &ExportQuery) -> String {
    let mut out = String::from(VALIDATION_RUNS_CSV_HEADER);
    out.push('\n');
    let logs = store::workspace_dir().join("logs");
    let Ok(entries) = fs::read_dir(&logs) else {
        return out;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_string();
        if !name.starts_with("live_fdd_validation") {
            continue;
        }
        let summary = path.join("summary.jsonl");
        if !summary.exists() {
            continue;
        }
        let Ok(text) = fs::read_to_string(&summary) else {
            continue;
        };
        for line in text.lines() {
            if line.trim().is_empty() {
                continue;
            }
            let Ok(row) = serde_json::from_str::<Value>(line) else {
                continue;
            };
            out.push_str(&csv_row(&[
                row.get("timestamp_utc")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                row.get("sample_index")
                    .map(|v| v.to_string())
                    .unwrap_or_default(),
                row.get("api_health_ok")
                    .map(|v| v.to_string())
                    .unwrap_or_default(),
                row.get("fdd_sql_ok")
                    .map(|v| v.to_string())
                    .unwrap_or_default(),
                row.get("smoke_device_instance")
                    .map(|v| v.to_string())
                    .unwrap_or_default(),
                row.get("expected_phase")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                row.get("raw_fault_count")
                    .map(|v| v.to_string())
                    .unwrap_or_default(),
                row.get("confirmed_fault_count")
                    .map(|v| v.to_string())
                    .unwrap_or_default(),
                row.get("data_source")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                row.get("demo_only")
                    .map(|v| v.to_string())
                    .unwrap_or_default(),
                name.clone(),
            ]));
            out.push('\n');
        }
    }
    out
}

pub fn import_jobs_csv() -> String {
    crate::import::jobs_csv_export()
}

fn filtered_historian_rows(query: &ExportQuery) -> Vec<Value> {
    let mut rows = store::load_pivot_rows().unwrap_or_default();
    rows.sort_by(|a, b| {
        a.get("timestamp")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .cmp(b.get("timestamp").and_then(|v| v.as_str()).unwrap_or(""))
    });
    if let Some(hours) = query.hours {
        let cutoff = Utc::now() - chrono::Duration::hours(hours);
        rows.retain(|r| {
            r.get("timestamp")
                .and_then(|v| v.as_str())
                .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
                .map(|dt| dt.with_timezone(&Utc) >= cutoff)
                .unwrap_or(true)
        });
    }
    if let Some(ref equip) = query.equipment_id {
        rows.retain(|r| {
            r.get("equipment_id")
                .and_then(|v| v.as_str())
                .map(|e| e == equip)
                .unwrap_or(false)
        });
    }
    if let Some(ref protocol) = query.source_protocol {
        rows.retain(|r| {
            r.get("source_driver")
                .and_then(|v| v.as_str())
                .map(|p| p == protocol)
                .unwrap_or(false)
        });
    }
    if let Some(ref start) = query.start {
        rows.retain(|r| ts_gte(r, start));
    }
    if let Some(ref end) = query.end {
        rows.retain(|r| ts_lte(r, end));
    }
    rows
}

fn ts_gte(row: &Value, start: &str) -> bool {
    match (
        row.get("timestamp").and_then(|v| v.as_str()),
        DateTime::parse_from_rfc3339(start).ok(),
    ) {
        (Some(ts), Some(start_dt)) => DateTime::parse_from_rfc3339(ts)
            .map(|dt| dt >= start_dt)
            .unwrap_or(true),
        _ => true,
    }
}

fn ts_lte(row: &Value, end: &str) -> bool {
    match (
        row.get("timestamp").and_then(|v| v.as_str()),
        DateTime::parse_from_rfc3339(end).ok(),
    ) {
        (Some(ts), Some(end_dt)) => DateTime::parse_from_rfc3339(ts)
            .map(|dt| dt <= end_dt)
            .unwrap_or(true),
        _ => true,
    }
}

fn first_driver_binding(point: &Value) -> (String, String, String) {
    point
        .get("driver_bindings")
        .and_then(|v| v.as_array())
        .and_then(|a| a.first())
        .map(|b| {
            (
                b.get("driver")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .into(),
                b.get("ref").and_then(|v| v.as_str()).unwrap_or("").into(),
                b.get("object_id")
                    .map(|v| v.to_string())
                    .unwrap_or_default(),
            )
        })
        .unwrap_or_default()
}

fn rule_inputs_for_point(haystack_id: &str, assignments: &Value) -> String {
    let mut inputs = Vec::new();
    if let Some(bindings) = assignments
        .get("fault_equation_bindings")
        .and_then(|v| v.as_array())
    {
        for binding in bindings {
            if let Some(map) = binding.get("inputs").and_then(|v| v.as_object()) {
                for (input, point) in map {
                    if point.as_str() == Some(haystack_id) {
                        inputs.push(format!("{input}={haystack_id}"));
                    }
                }
            }
        }
    }
    inputs.join(";")
}

fn format_timestamps(iso: &str) -> (String, String, String) {
    if let Ok(dt) = DateTime::parse_from_rfc3339(iso) {
        let utc = dt.with_timezone(&Utc).to_rfc3339();
        let local = dt
            .with_timezone(&Local)
            .format("%Y-%m-%d %H:%M:%S")
            .to_string();
        let tz = env::var("TZ").unwrap_or_else(|_| "UTC".to_string());
        (utc, local, tz)
    } else {
        (iso.to_string(), iso.to_string(), "UTC".to_string())
    }
}

fn fmt_f64(value: Option<&Value>) -> String {
    value
        .and_then(|v| v.as_f64())
        .map(|n| n.to_string())
        .unwrap_or_default()
}

pub fn csv_row(fields: &[String]) -> String {
    fields
        .iter()
        .map(|f| {
            let escaped = f.replace('"', "\"\"");
            format!("\"{escaped}\"")
        })
        .collect::<Vec<_>>()
        .join(",")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn historian_header_is_stable() {
        assert!(HISTORIAN_CSV_HEADER.starts_with("timestamp_utc,timestamp_local,timezone"));
        assert!(HISTORIAN_CSV_HEADER.contains("source_path"));
    }

    #[test]
    fn export_filename_has_prefix_and_timestamp() {
        let name = export_filename("historian");
        assert!(name.starts_with("openfdd_historian_"));
        assert!(name.ends_with(".csv"));
    }

    #[test]
    fn timestamps_present_in_historian_export() {
        let csv = historian_csv(&ExportQuery::default());
        assert!(csv.starts_with(HISTORIAN_CSV_HEADER));
    }

    #[test]
    fn classifies_demo_only_label() {
        let rows = vec![json!({"source":"demo:static","source_driver":"demo"})];
        assert!(historian_data_label(&rows).contains("DEMO ONLY"));
    }
}
