//! HTTP handlers for CSV UT3 import API.

pub mod dataset;
pub mod parse;
pub mod plan;
pub mod session;
pub mod timestamp;
mod upload;

pub use dataset::{delete_dataset, list_datasets, preview_dataset, save_dataset};

use plan::{
    auto_detect_mapping, infer_ut3_plan_from_session, is_weather_filename, plan_from_json,
    OutputRow,
};
use session::{create_session, load_session, save_session, stage_file};

use plan::{append_rows, join_rows, parse_file_to_rows, preview_rows, JoinAlignment};
use serde_json::{json, Value};
use session::read_staged_file;

pub fn preview_handler(content_type: &str, body: &[u8]) -> Value {
    let files = match upload::parse_upload(content_type, body) {
        Ok(f) => f,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    if files.is_empty() {
        return json!({"ok": false, "error": "no files in upload"});
    }
    let session = create_session();
    let session_id = session
        .get("session_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if session_id.is_empty() {
        return session;
    }
    let mut staged = Vec::new();
    let mut errors = Vec::new();
    for (name, raw) in files {
        match stage_file(&session_id, &name, &raw) {
            Ok(meta) => staged.push(meta),
            Err(e) => errors.push(json!({"file": name, "error": e})),
        }
    }
    let mut session = load_session(&session_id).unwrap_or(session);
    session["files"] = json!(staged);
    session["status"] = json!("previewed");
    let _ = save_session(&session_id, &session);
    json!({
        "ok": errors.is_empty(),
        "session_id": session_id,
        "files": staged,
        "errors": errors,
    })
}

pub fn preview_json_handler(body: &Value) -> Value {
    let session = create_session();
    let session_id = session
        .get("session_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let files = body.get("files").and_then(|v| v.as_array());
    let Some(files) = files else {
        return json!({"ok": false, "error": "files array required"});
    };
    let mut staged = Vec::new();
    for f in files {
        let name = f
            .get("filename")
            .and_then(|v| v.as_str())
            .unwrap_or("upload.csv");
        let content = f
            .get("content_base64")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let raw = match base64_decode(content) {
            Ok(b) => b,
            Err(e) => {
                staged.push(json!({"filename": name, "error": e}));
                continue;
            }
        };
        match stage_file(&session_id, name, &raw) {
            Ok(meta) => staged.push(meta),
            Err(e) => staged.push(json!({"filename": name, "error": e})),
        }
    }
    let mut session = load_session(&session_id).unwrap_or(session);
    session["files"] = json!(staged);
    session["status"] = json!("previewed");
    let _ = save_session(&session_id, &session);
    json!({"ok": true, "session_id": session_id, "files": staged})
}

fn base64_decode(s: &str) -> Result<Vec<u8>, String> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD
        .decode(s)
        .map_err(|e| e.to_string())
}

pub fn plan_handler(body: &Value) -> Value {
    let session_id = body
        .get("session_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let Some(mut session) = load_session(session_id) else {
        return json!({"ok": false, "error": "session not found"});
    };
    let plan = match plan_from_json(body.get("plan").unwrap_or(body)) {
        Ok(p) => p,
        Err(e) => return json!({"ok": false, "error": e}),
    };

    let rows = match execute_plan_preview(&plan, session_id) {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let preview = preview_rows(&rows, 100);
    let validation_report = json!({
        "timestamp_analysis": preview.timestamp_analysis,
        "warnings": preview.warnings,
        "row_count": preview.row_count,
        "quarantined": 0,
    });
    session["plan"] = serde_json::to_value(&plan).unwrap_or(json!({}));
    session["status"] = json!("planned");
    session["validation_report"] = validation_report.clone();
    session["preview_summary"] = json!({
        "row_count": preview.row_count,
        "column_names": preview.column_names,
        "time_range": preview.time_range,
        "sample_rows": preview.sample_rows.iter().take(25).collect::<Vec<_>>(),
    });
    let _ = save_session(session_id, &session);
    json!({
        "ok": true,
        "session_id": session_id,
        "plan": plan,
        "preview": preview,
        "validation_report": validation_report,
        "fusion_url": format!("/csv?session={session_id}"),
    })
}

fn execute_plan_preview(
    plan: &plan::ImportPlan,
    session_id: &str,
) -> Result<Vec<OutputRow>, String> {
    match plan.mode {
        plan::OperationMode::Single | plan::OperationMode::Append => {
            let mut batches = Vec::new();
            for fm in &plan.files {
                let (profile, text) = read_staged_file(session_id, &fm.filename)?;
                let mut mapping = fm.clone();
                if mapping.timestamp_column.is_empty() {
                    mapping = auto_detect_mapping(&fm.filename, &profile.headers);
                }
                let rows =
                    parse_file_to_rows(&text, &mapping, profile.delimiter, &plan.ambiguous_policy)?;
                batches.push(rows);
            }
            Ok(append_rows(batches))
        }
        plan::OperationMode::Join => {
            if plan.files.len() < 2 {
                return Err("join requires at least two file mappings".into());
            }
            let weather_idx = plan
                .files
                .iter()
                .position(|f| is_weather_filename(&f.filename));
            if let Some(widx) = weather_idx {
                let school_maps: Vec<_> = plan
                    .files
                    .iter()
                    .enumerate()
                    .filter(|(i, _)| *i != widx)
                    .map(|(_, f)| f.clone())
                    .collect();
                let weather_map = plan.files[widx].clone();
                let left = if school_maps.len() > 1 {
                    let mut batches = Vec::new();
                    for fm in &school_maps {
                        let (profile, text) = read_staged_file(session_id, &fm.filename)?;
                        let mut mapping = fm.clone();
                        if mapping.timestamp_column.is_empty() {
                            mapping = auto_detect_mapping(&fm.filename, &profile.headers);
                        }
                        batches.push(parse_file_to_rows(
                            &text,
                            &mapping,
                            profile.delimiter,
                            &plan.ambiguous_policy,
                        )?);
                    }
                    append_rows(batches)
                } else {
                    let fm = &school_maps[0];
                    let (profile, text) = read_staged_file(session_id, &fm.filename)?;
                    parse_file_to_rows(&text, fm, profile.delimiter, &plan.ambiguous_policy)?
                };
                let (profile_r, text_r) = read_staged_file(session_id, &weather_map.filename)?;
                let right = parse_file_to_rows(
                    &text_r,
                    &weather_map,
                    profile_r.delimiter,
                    &plan.ambiguous_policy,
                )?;
                let alignment = plan.join_alignment.unwrap_or(JoinAlignment::FloorHour);
                join_rows(left, right, alignment, plan.fill_policy)
            } else {
                let (profile_l, text_l) = read_staged_file(session_id, &plan.files[0].filename)?;
                let (profile_r, text_r) = read_staged_file(session_id, &plan.files[1].filename)?;
                let left = parse_file_to_rows(
                    &text_l,
                    &plan.files[0],
                    profile_l.delimiter,
                    &plan.ambiguous_policy,
                )?;
                let right = parse_file_to_rows(
                    &text_r,
                    &plan.files[1],
                    profile_r.delimiter,
                    &plan.ambiguous_policy,
                )?;
                let alignment = plan.join_alignment.unwrap_or(JoinAlignment::FloorHour);
                join_rows(left, right, alignment, plan.fill_policy)
            }
        }
    }
}

pub fn execute_handler(body: &Value) -> Value {
    let session_id = body
        .get("session_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let confirm = body.get("confirm").and_then(|v| v.as_bool()) == Some(true);
    if !confirm {
        return json!({"ok": false, "error": "confirm:true required to write Feather/Arrow store"});
    }
    let Some(session) = load_session(session_id) else {
        return json!({"ok": false, "error": "session not found"});
    };
    let plan_val = session.get("plan").cloned().unwrap_or(json!({}));
    let plan: plan::ImportPlan = match serde_json::from_value(plan_val) {
        Ok(p) => p,
        Err(e) => return json!({"ok": false, "error": e.to_string()}),
    };
    let rows = match execute_plan_preview(&plan, session_id) {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let preview = preview_rows(&rows, 5);
    let validation_report = session
        .get("validation_report")
        .cloned()
        .unwrap_or_else(|| json!({"warnings": preview.warnings}));
    let dataset_id = plan.output_dataset_name.clone();
    match save_dataset(
        &dataset_id,
        &rows,
        &validation_report,
        &json!({"session_id": session_id}),
    ) {
        Ok(result) => {
            let mut session = session;
            session["status"] = json!("executed");
            session["result"] = result.clone();
            let _ = save_session(session_id, &session);
            result
        }
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn get_session_handler(session_id: &str) -> Value {
    match load_session(session_id) {
        Some(s) => json!({"ok": true, "session": s}),
        None => json!({"ok": false, "error": "session not found"}),
    }
}

const FUSION_PREVIEW_DEFAULT_LIMIT: usize = 2_000;
const FUSION_PREVIEW_MAX_LIMIT: usize = 10_000;

pub fn fusion_preview_handler(session_id: &str, limit: usize) -> Value {
    let Some(mut session) = load_session(session_id) else {
        return json!({
            "ok": false,
            "error": "session not found",
            "hint": "Run UT3 Upload then Preview plan first, or restart edge after rebuild so session routes are live."
        });
    };
    let status = session
        .get("status")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if status != "planned" && status != "previewed" && status != "executed" {
        return json!({
            "ok": false,
            "error": "session has no staged files — upload CSVs via POST /api/csv/import/preview first",
            "status": status
        });
    }
    let mut plan_val = session.get("plan").cloned().unwrap_or(json!({}));
    let plan: plan::ImportPlan = match serde_json::from_value::<plan::ImportPlan>(plan_val.clone())
    {
        Ok(p) if !p.files.is_empty() => p,
        _ => {
            let inferred = infer_ut3_plan_from_session(&session);
            if inferred.files.is_empty() {
                return json!({"ok": false, "error": "session has no staged files"});
            }
            plan_val = serde_json::to_value(&inferred).unwrap_or(json!({}));
            session["plan"] = plan_val.clone();
            if status == "previewed" {
                session["status"] = json!("planned");
            }
            let _ = save_session(session_id, &session);
            inferred
        }
    };
    if plan.files.is_empty() {
        return json!({"ok": false, "error": "session plan has no file mappings — run Preview plan"});
    }
    let rows = match execute_plan_preview(&plan, session_id) {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let total = rows.len();
    let cap = limit.clamp(1, FUSION_PREVIEW_MAX_LIMIT);
    let (columns, grid) = plan::output_rows_to_fusion_grid(&rows, cap);
    let validation = session
        .get("validation_report")
        .cloned()
        .unwrap_or(json!({}));
    json!({
        "ok": true,
        "session_id": session_id,
        "dataset_name": plan.output_dataset_name,
        "status": status,
        "row_count": total,
        "preview_row_count": grid.len(),
        "truncated": total > grid.len(),
        "columns": columns,
        "rows": grid,
        "validation_report": validation,
        "fusion_url_hint": format!("/csv?session={session_id}"),
    })
}

pub fn fusion_preview_limit_from_query(limit: Option<&str>) -> usize {
    limit
        .and_then(|s| s.parse::<usize>().ok())
        .unwrap_or(FUSION_PREVIEW_DEFAULT_LIMIT)
        .clamp(1, FUSION_PREVIEW_MAX_LIMIT)
}

pub fn list_sessions_handler(limit: usize) -> Value {
    session::list_sessions_handler(limit)
}

pub fn latest_planned_session_handler() -> Value {
    session::latest_planned_session_handler()
}

pub fn delete_session_file_handler(body: &Value) -> Value {
    let session_id = body
        .get("session_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let filename = body.get("filename").and_then(|v| v.as_str()).unwrap_or("");
    match session::delete_staged_file(session_id, filename) {
        Ok(()) => json!({"ok": true}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}
