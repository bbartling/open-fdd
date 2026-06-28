//! Model-driven report drafts and HTML/PDF export bundles (Rust-era, no Python).

use crate::faults;
use crate::fdd::rules;
use crate::historian::store;
use crate::model::query;
use chrono::Utc;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

pub fn reports_dir() -> PathBuf {
    store::workspace_dir().join("reports/generated")
}

fn report_dir(id: &str) -> PathBuf {
    reports_dir().join(sanitize_id(id))
}

pub fn sanitize_id(raw: &str) -> String {
    raw.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

fn save_report(id: &str, doc: &Value) -> Result<(), String> {
    let dir = report_dir(id);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    fs::write(
        dir.join("report.json"),
        serde_json::to_string_pretty(doc).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())
}

fn load_report(id: &str) -> Option<Value> {
    let path = report_dir(id).join("report.json");
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

fn rule_explanation_block(rule_id: &str) -> Value {
    let rule_doc = rules::get_rule(rule_id);
    let rule = rule_doc.get("rule").cloned().unwrap_or(json!({}));
    json!({
        "rule_id": rule_id,
        "rule_name": rule.get("name").cloned().unwrap_or(json!("FDD Rule")),
        "sql": rule.get("sql").cloned().unwrap_or(json!(null)),
        "confirmation_seconds": rule.get("confirmation_seconds").cloned().unwrap_or(json!(300)),
        "required_inputs": rule.get("required_inputs").cloned().unwrap_or(json!([])),
        "raw_fault_logic": rule.get("raw_fault_sql").cloned().unwrap_or(rule.get("raw_fault").cloned().unwrap_or(json!("raw_fault when SQL predicate true"))),
        "confirmed_fault_logic": rule.get("confirmed_fault_sql").cloned().unwrap_or(json!("confirmed_fault when raw_fault sustained for confirmation_seconds")),
        "explanation": rule.get("description").and_then(|v| v.as_str()).unwrap_or(
            "Rule evaluates historian bindings via DataFusion SQL; raw_fault starts immediately, confirmed_fault after confirmation delay."
        )
    })
}

fn suggested_plot_blocks() -> Vec<Value> {
    let mut blocks = Vec::new();
    let points = query::list_points(None);
    let point_list = points
        .get("points")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut roles: std::collections::HashSet<String> = std::collections::HashSet::new();
    for p in &point_list {
        if let Some(role) = p.get("fdd_input").and_then(|v| v.as_str()) {
            roles.insert(role.to_string());
        }
    }
    if roles.contains("oa_t") || roles.contains("duct_t") || roles.contains("zn_t") {
        let series: Vec<&str> = ["oa_t", "duct_t", "zn_t"]
            .iter()
            .copied()
            .filter(|r| roles.contains(*r))
            .collect();
        blocks.push(json!({
            "id": "plot-trends",
            "type": "plot",
            "title": "Temperature trends",
            "visible": true,
            "order": 10,
            "content": {
                "plot_type": "multi_trend",
                "series": series,
                "source": "historian"
            }
        }));
    }
    if roles.contains("sat") && roles.contains("sat_sp") {
        blocks.push(json!({
            "id": "plot-sat-tracking",
            "type": "plot",
            "title": "SAT vs setpoint",
            "visible": true,
            "order": 11,
            "content": {"plot_type": "sat_tracking", "series": ["sat", "sat_sp"], "overlay_faults": true}
        }));
    }
    if roles.contains("fan_cmd") && roles.contains("fan_status") {
        blocks.push(json!({
            "id": "plot-fan-mismatch",
            "type": "plot",
            "title": "Fan command vs status",
            "visible": true,
            "order": 12,
            "content": {"plot_type": "command_status", "series": ["fan_cmd", "fan_status"]}
        }));
    }
    blocks
}

pub fn templates() -> Value {
    json!({
        "ok": true,
        "templates": [
            {
                "id": "validation-summary",
                "title": "Validation summary",
                "description": "Auto-built from historian, FDD rules, imports, and source health"
            },
            {
                "id": "equipment-fdd",
                "title": "Equipment FDD report",
                "description": "Per-equipment plots, SQL rules, and fault timelines"
            },
            {
                "id": "rcx-universal-3",
                "title": "RCx Universal 3 (ASHRAE)",
                "description": "Retro-commissioning style report: faults, trends, recommendations, and CSV-backed evidence"
            },
            {
                "id": "openfdd-branded",
                "title": "Open-FDD branded RCx",
                "description": "RCx-style report with optional Open-FDD chiller cover branding"
            }
        ]
    })
}

pub fn create_draft(body: &Value) -> Value {
    let template = body
        .get("template_id")
        .and_then(|v| v.as_str())
        .unwrap_or("validation-summary");
    let title = body
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or("Open-FDD Report");
    let include_branding = body
        .get("include_branding")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let report_id = format!("rpt-{}", Utc::now().timestamp_millis());
    let coverage = query::model_coverage();
    let equips = query::list_equips(None);
    let hist_status = store::status_json();
    let mut sections = vec![];
    if include_branding || template == "openfdd-branded" {
        sections.push(json!({
            "id": "cover-branding",
            "type": "cover",
            "title": "Open-FDD",
            "visible": include_branding,
            "order": sections.len(),
            "content": {
                "brand": "Open-FDD",
                "logo_url": "https://raw.githubusercontent.com/bbartling/open-fdd/master/image_new_chiller.png",
                "accent_color": "#58a6ff",
                "subtitle": title
            }
        }));
    }
    sections.extend(vec![
        json!({
            "id": "building-summary",
            "type": "building_summary",
            "title": "Building summary",
            "visible": true,
            "order": 0,
            "content": {
                "generated_at": Utc::now().to_rfc3339(),
                "template_id": template,
                "title": title,
                "sites": query::list_sites()
            }
        }),
        json!({
            "id": "model-coverage",
            "type": "model_coverage",
            "title": "Model coverage",
            "visible": true,
            "order": 1,
            "content": coverage
        }),
        json!({
            "id": "source-health",
            "type": "source_health",
            "title": "Source health",
            "visible": true,
            "order": 2,
            "content": query::source_coverage()
        }),
        json!({
            "id": "historian-summary",
            "type": "historian_summary",
            "title": "Historian summary",
            "visible": true,
            "order": 3,
            "content": hist_status
        }),
        json!({
            "id": "rule-explanation",
            "type": "rule_explanation",
            "title": "FDD rule: oa_temp_out_of_range",
            "visible": true,
            "order": 4,
            "content": rule_explanation_block("oa_temp_out_of_range")
        }),
        json!({
            "id": "equipment-summary",
            "type": "equipment_summary",
            "title": "Equipment",
            "visible": true,
            "order": 5,
            "content": equips
        }),
        json!({
            "id": "fault-summary",
            "type": "fault_summary",
            "title": "Fault summary",
            "visible": true,
            "order": 6,
            "content": faults::summary_json()
        }),
        json!({
            "id": "data-quality",
            "type": "data_quality",
            "title": "Data quality",
            "visible": true,
            "order": 7,
            "content": query::source_coverage()
        }),
        json!({
            "id": "recommendations",
            "type": "recommendations",
            "title": "Recommendations",
            "visible": true,
            "order": 8,
            "content": {"notes": "Review confirmed faults and model gaps before commissioning sign-off.", "items": []}
        }),
    ]);
    for (i, sec) in sections.iter_mut().enumerate() {
        if sec.get("order").is_none() {
            sec["order"] = json!(i);
        }
    }
    for plot in suggested_plot_blocks() {
        sections.push(plot);
    }
    let doc = json!({
        "ok": true,
        "report_id": report_id,
        "title": title,
        "template_id": template,
        "created_at": Utc::now().to_rfc3339(),
        "updated_at": Utc::now().to_rfc3339(),
        "sections": sections,
        "metadata": {
            "generator": "open-fdd-rust-report-builder",
            "pdf_ready": false
        }
    });
    match save_report(&report_id, &doc) {
        Ok(()) => doc,
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn get_report(report_id: &str) -> Value {
    load_report(report_id)
        .map(|doc| json!({"ok": true, "report": doc}))
        .unwrap_or_else(|| json!({"ok": false, "error": "report not found"}))
}

pub fn patch_report(report_id: &str, body: &Value) -> Value {
    let Some(mut doc) = load_report(report_id) else {
        return json!({"ok": false, "error": "report not found"});
    };
    if let Some(title) = body.get("title").and_then(|v| v.as_str()) {
        doc["title"] = json!(title);
    }
    if let Some(sections) = body.get("sections") {
        doc["sections"] = sections.clone();
    }
    doc["updated_at"] = json!(Utc::now().to_rfc3339());
    match save_report(report_id, &doc) {
        Ok(()) => json!({"ok": true, "report": doc}),
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn reorder_sections(report_id: &str, body: &Value) -> Value {
    let Some(order) = body.get("section_ids").and_then(|v| v.as_array()) else {
        return json!({"ok": false, "error": "section_ids array required"});
    };
    let Some(mut doc) = load_report(report_id) else {
        return json!({"ok": false, "error": "report not found"});
    };
    let sections = doc
        .get("sections")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut by_id = std::collections::HashMap::new();
    for s in sections {
        if let Some(id) = s.get("id").and_then(|v| v.as_str()) {
            by_id.insert(id.to_string(), s);
        }
    }
    let mut reordered = Vec::new();
    for (idx, idv) in order.iter().enumerate() {
        if let Some(id) = idv.as_str() {
            if let Some(mut sec) = by_id.remove(id) {
                sec["order"] = json!(idx);
                reordered.push(sec);
            }
        }
    }
    for (_, mut sec) in by_id {
        sec["order"] = json!(reordered.len());
        reordered.push(sec);
    }
    doc["sections"] = json!(reordered);
    doc["updated_at"] = json!(Utc::now().to_rfc3339());
    match save_report(report_id, &doc) {
        Ok(()) => json!({"ok": true, "report": doc}),
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn report_data(report_id: &str) -> Value {
    let Some(doc) = load_report(report_id) else {
        return json!({"ok": false, "error": "report not found"});
    };
    json!({
        "ok": true,
        "report_id": report_id,
        "sections": doc.get("sections").cloned().unwrap_or(json!([]))
    })
}

pub fn render_html(report_id: &str) -> Result<PathBuf, String> {
    let doc = load_report(report_id).ok_or("report not found")?;
    let title = doc
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or("Open-FDD Report");
    let generated = Utc::now().to_rfc3339();
    let mut html = format!(
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>{title}</title>\
<style>body{{font-family:sans-serif;margin:2rem;color:#111}}\
section{{margin-bottom:2rem;border-bottom:1px solid #ccc;padding-bottom:1rem;page-break-inside:avoid}}\
h1{{margin-bottom:0.2rem}}h2{{color:#333;margin-top:0}}\
.meta{{color:#666;font-size:0.9rem}}pre{{background:#f5f5f5;padding:1rem;overflow:auto;font-size:0.85rem}}\
@media print{{header,footer{{display:block}}}}</style></head><body>\
<header><h1>{title}</h1><p class=\"meta\">Generated {generated} · Open-FDD Report Builder</p></header>"
    );
    if let Some(sections) = doc.get("sections").and_then(|v| v.as_array()) {
        for sec in sections {
            if sec.get("visible").and_then(|v| v.as_bool()) == Some(false) {
                continue;
            }
            let stitle = sec
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or("Section");
            html.push_str(&format!("<section><h2>{stitle}</h2><pre>"));
            html.push_str(
                &serde_json::to_string_pretty(sec.get("content").unwrap_or(&json!({})))
                    .unwrap_or_default(),
            );
            html.push_str("</pre></section>");
        }
    }
    html.push_str("<footer><p class=\"meta\">Open-FDD · confidential commissioning data — no secrets included</p></footer></body></html>");
    let dir = report_dir(report_id);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join("report.html");
    fs::write(&path, html).map_err(|e| e.to_string())?;
    Ok(path)
}

fn pdf_escape(text: &str) -> String {
    text.replace('\\', "\\\\")
        .replace('(', "\\(")
        .replace(')', "\\)")
}

fn write_text_pdf(path: &Path, title: &str, lines: &[String]) -> Result<(), String> {
    let mut body = format!("BT /F1 14 Tf 50 750 Td ({}) Tj ", pdf_escape(title));
    body.push_str("0 -18 Td /F1 10 Tf ");
    for line in lines.iter().take(48) {
        body.push_str(&format!("({}) Tj 0 -12 Tj ", pdf_escape(line)));
    }
    body.push_str("ET");

    let objects = [
        "<< /Type /Catalog /Pages 2 0 R >>".to_string(),
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>".to_string(),
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> >>"
            .to_string(),
        format!("<< /Length {} >>\nstream\n{}\nendstream", body.len(), body),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>".to_string(),
    ];

    let mut pdf = String::from("%PDF-1.4\n");
    let mut offsets = vec![0_usize];
    for (i, obj) in objects.iter().enumerate() {
        offsets.push(pdf.len());
        pdf.push_str(&format!("{} 0 obj\n{obj}\nendobj\n", i + 1));
    }
    let xref_pos = pdf.len();
    pdf.push_str(&format!("xref\n0 {}\n", objects.len() + 1));
    pdf.push_str("0000000000 65535 f \n");
    for off in &offsets[1..] {
        pdf.push_str(&format!("{:010} 00000 n \n", off));
    }
    pdf.push_str(&format!(
        "trailer << /Size {} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n",
        objects.len() + 1
    ));
    fs::write(path, pdf).map_err(|e| e.to_string())
}

pub fn render_pdf(report_id: &str) -> Result<PathBuf, String> {
    let doc = load_report(report_id).ok_or("report not found")?;
    let title = doc
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or("Open-FDD Report")
        .to_string();
    let mut lines = vec![
        format!("Generated: {}", Utc::now().to_rfc3339()),
        format!("Report ID: {report_id}"),
    ];
    if let Some(sections) = doc.get("sections").and_then(|v| v.as_array()) {
        for sec in sections {
            if sec.get("visible").and_then(|v| v.as_bool()) == Some(false) {
                continue;
            }
            let stitle = sec
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or("Section");
            lines.push(String::new());
            lines.push(format!("## {stitle}"));
            let body =
                serde_json::to_string(sec.get("content").unwrap_or(&json!({}))).unwrap_or_default();
            for chunk in body.as_bytes().chunks(90) {
                lines.push(String::from_utf8_lossy(chunk).into_owned());
            }
        }
    }
    let dir = report_dir(report_id);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let pdf_path = dir.join("report.pdf");
    write_text_pdf(&pdf_path, &title, &lines)?;
    let _ = render_html(report_id);
    if let Some(mut saved) = load_report(report_id) {
        saved["metadata"]["pdf_ready"] = json!(true);
        saved["metadata"]["pdf_generated_at"] = json!(Utc::now().to_rfc3339());
        let _ = save_report(report_id, &saved);
    }
    Ok(pdf_path)
}

pub fn render_pdf_bundle(report_id: &str) -> Value {
    match render_pdf(report_id) {
        Ok(pdf_path) => {
            let html_path = report_dir(report_id).join("report.html");
            json!({
                "ok": true,
                "report_id": report_id,
                "html_path": html_path.display().to_string(),
                "pdf_path": pdf_path.display().to_string(),
                "render_engine": "rust-text-pdf",
                "size_bytes": fs::metadata(&pdf_path).map(|m| m.len()).unwrap_or(0)
            })
        }
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn download_path(report_id: &str, kind: &str) -> Option<PathBuf> {
    let id = safe_report_id(report_id)?;
    let dir = report_dir(&id);
    match kind {
        "html" => {
            let p = dir.join("report.html");
            if p.exists() {
                Some(p)
            } else {
                render_html(&id).ok()
            }
        }
        "pdf" => {
            let p = dir.join("report.pdf");
            if p.exists() {
                Some(p)
            } else {
                render_pdf(&id).ok()
            }
        }
        _ => None,
    }
}

pub fn safe_report_id(raw: &str) -> Option<String> {
    if raw.is_empty() || raw.contains("..") || raw.contains('/') {
        return None;
    }
    let sanitized = sanitize_id(raw);
    if sanitized.is_empty() {
        return None;
    }
    Some(sanitized)
}

pub fn list_rcx_reports() -> Value {
    let body = list_reports();
    let records = body
        .get("records")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|r| {
            r.get("report_type")
                .and_then(|v| v.as_str())
                .map(|t| t.contains("rcx") || t.contains("RCx"))
                .unwrap_or(false)
        })
        .collect::<Vec<_>>();
    json!({"ok": true, "reports": records, "count": records.len()})
}

pub fn generate_rcx(payload: &Value) -> Value {
    let mut draft = payload.clone();
    if draft.get("template_id").is_none() {
        draft["template_id"] = json!("openfdd-branded");
    }
    if draft.get("title").is_none() {
        draft["title"] = json!("RCx Report");
    }
    create_draft(&draft)
}

pub fn list_reports() -> Value {
    let dir = reports_dir();
    let _ = fs::create_dir_all(&dir);
    let mut records: Vec<Value> = Vec::new();
    if let Ok(entries) = fs::read_dir(&dir) {
        for ent in entries.flatten() {
            if !ent.path().is_dir() {
                continue;
            }
            let id = ent.file_name().to_string_lossy().to_string();
            let Some(doc) = load_report(&id) else {
                continue;
            };
            let meta = doc.get("metadata").cloned().unwrap_or(json!({}));
            let pdf_path = ent.path().join("report.pdf");
            records.push(json!({
                "report_id": id,
                "title": doc.get("title").cloned().unwrap_or(json!(null)),
                "report_type": meta.get("template_id").or(doc.get("template_id")).cloned().unwrap_or(json!("validation-summary")),
                "validation_run_id": meta.get("validation_run_id").cloned().unwrap_or(json!(null)),
                "status": meta.get("validation_status").cloned().unwrap_or(json!("draft")),
                "created_at": meta.get("created_at").cloned().or_else(|| doc.get("created_at").cloned()).unwrap_or(json!(null)),
                "pdf_ready": pdf_path.exists(),
                "size_bytes": fs::metadata(&pdf_path).map(|m| m.len()).unwrap_or(0),
            }));
        }
    }
    records.sort_by(|a, b| {
        let ta = a.get("created_at").and_then(|v| v.as_str()).unwrap_or("");
        let tb = b.get("created_at").and_then(|v| v.as_str()).unwrap_or("");
        tb.cmp(ta)
    });
    json!({"ok": true, "records": records})
}

pub fn delete_report(report_id: &str) -> Value {
    let id = match safe_report_id(report_id) {
        Some(v) => v,
        None => return json!({"ok": false, "error": "invalid report id"}),
    };
    let dir = report_dir(&id);
    if !dir.exists() {
        return json!({"ok": false, "error": "report not found", "report_id": id});
    }
    match fs::remove_dir_all(&dir) {
        Ok(()) => json!({"ok": true, "deleted": true, "report_id": id}),
        Err(e) => json!({"ok": false, "error": e.to_string(), "report_id": id}),
    }
}

fn validation_summary_from_artifact(artifact_dir: &str) -> Value {
    let path = Path::new(artifact_dir).join("summary.jsonl");
    let text = match fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return json!({"ok": false, "error": "summary.jsonl not found"}),
    };
    let mut samples = 0_u64;
    let mut bacnet_poll_ok = 0_u64;
    let mut modbus_ok = 0_u64;
    let mut haystack_ok = 0_u64;
    let mut csv_ok = 0_u64;
    let mut raw_fault_samples = 0_u64;
    let mut confirmed_fault_samples = 0_u64;
    for line in text.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        samples += 1;
        if row.get("bacnet_poll_ok").and_then(|v| v.as_bool()) == Some(true) {
            bacnet_poll_ok += 1;
        }
        if row.get("modbus_ok").and_then(|v| v.as_bool()) == Some(true) {
            modbus_ok += 1;
        }
        if row.get("haystack_ok").and_then(|v| v.as_bool()) == Some(true) {
            haystack_ok += 1;
        }
        if row.get("csv_import_ok").and_then(|v| v.as_bool()) == Some(true) {
            csv_ok += 1;
        }
        if row
            .get("raw_fault_count")
            .and_then(|v| v.as_u64())
            .unwrap_or(0)
            > 0
        {
            raw_fault_samples += 1;
        }
        if row
            .get("confirmed_fault_count")
            .and_then(|v| v.as_u64())
            .unwrap_or(0)
            > 0
        {
            confirmed_fault_samples += 1;
        }
    }
    json!({
        "samples": samples,
        "bacnet_poll_ok": bacnet_poll_ok,
        "modbus_ok": modbus_ok,
        "haystack_ok": haystack_ok,
        "csv_import_ok": csv_ok,
        "raw_fault_samples": raw_fault_samples,
        "confirmed_fault_samples": confirmed_fault_samples,
        "artifact_dir": artifact_dir,
    })
}

pub fn from_validation_run(body: &Value) -> Value {
    let artifact_dir = body
        .get("artifact_dir")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let run_id = body
        .get("validation_run_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let passed = body.get("pass").and_then(|v| v.as_bool()).unwrap_or(false);
    let title = if passed {
        "Open-FDD 1-Hour Validation Report — PASS"
    } else {
        "Open-FDD 1-Hour Validation Report — FAILED"
    };
    let summary = validation_summary_from_artifact(artifact_dir);
    let doc = create_draft(&json!({
        "template_id": "validation-summary",
        "title": title,
    }));
    if doc.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return doc;
    }
    let report_id = doc
        .get("report_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if let Some(mut saved) = load_report(&report_id) {
        saved["metadata"] = json!({
            "validation_run_id": run_id,
            "validation_status": if passed { "pass" } else { "fail" },
            "artifact_dir": artifact_dir,
            "created_at": Utc::now().to_rfc3339(),
            "template_id": "validation-summary",
            "pdf_ready": false,
        });
        if let Some(sections) = saved.get_mut("sections").and_then(|v| v.as_array_mut()) {
            sections.push(json!({
                "id": "validation-run-summary",
                "type": "validation_summary",
                "title": "Validation run summary",
                "visible": true,
                "order": 99,
                "content": summary
            }));
        }
        let _ = save_report(&report_id, &saved);
    }
    let pdf = render_pdf_bundle(&report_id);
    json!({
        "ok": true,
        "report_id": report_id,
        "pass": passed,
        "validation_run_id": run_id,
        "artifact_dir": artifact_dir,
        "summary": summary,
        "pdf": pdf,
    })
}

/// Build a PDF report draft from an ad-hoc SQL FDD test run (SQL tab → Reports).
pub fn from_fdd_sql_run(body: &Value) -> Value {
    let rule_name = body
        .get("rule_name")
        .and_then(|v| v.as_str())
        .unwrap_or("FDD SQL Rule");
    let sql = body.get("sql").and_then(|v| v.as_str()).unwrap_or("");
    let equipment_id = body
        .get("equipment_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let fault_code = body
        .get("fault_code")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let run = body.get("run_result").cloned().unwrap_or(json!({}));
    let confirmation = run.get("confirmation").cloned().unwrap_or(json!({}));
    let confirmed_count = confirmation
        .get("confirmed_fault_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let raw_count = confirmation
        .get("raw_fault_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let row_count = run.get("row_count").and_then(|v| v.as_u64()).unwrap_or(0);
    let sample_rows: Vec<Value> = run
        .get("rows")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().take(25).cloned().collect())
        .unwrap_or_default();
    let title = format!("FDD SQL Report — {rule_name}");
    let doc = create_draft(&json!({
        "template_id": "fdd-sql-run",
        "title": title,
    }));
    if doc.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return doc;
    }
    let report_id = doc
        .get("report_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if let Some(mut saved) = load_report(&report_id) {
        saved["metadata"] = json!({
            "rule_name": rule_name,
            "equipment_id": equipment_id,
            "fault_code": fault_code,
            "confirmed_fault_count": confirmed_count,
            "raw_fault_count": raw_count,
            "row_count": row_count,
            "created_at": Utc::now().to_rfc3339(),
            "template_id": "fdd-sql-run",
            "pdf_ready": false,
        });
        if let Some(sections) = saved.get_mut("sections").and_then(|v| v.as_array_mut()) {
            sections.push(json!({
                "id": "fdd-sql-run",
                "type": "fdd_sql_run",
                "title": "SQL FDD run results",
                "visible": true,
                "order": 50,
                "content": {
                    "rule_name": rule_name,
                    "equipment_id": equipment_id,
                    "fault_code": fault_code,
                    "sql": sql,
                    "row_count": row_count,
                    "raw_fault_count": raw_count,
                    "confirmed_fault_count": confirmed_count,
                    "confirmation": confirmation,
                    "sample_rows": sample_rows,
                }
            }));
        }
        let _ = save_report(&report_id, &saved);
    }
    let pdf = render_pdf_bundle(&report_id);
    json!({
        "ok": true,
        "report_id": report_id,
        "rule_name": rule_name,
        "confirmed_fault_count": confirmed_count,
        "raw_fault_count": raw_count,
        "dashboard_url": "/",
        "pdf": pdf,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn workspace_test_lock() -> std::sync::MutexGuard<'static, ()> {
        crate::test_support::workspace_env_lock()
    }

    #[test]
    fn sanitize_report_id() {
        assert_eq!(sanitize_id("rpt-123"), "rpt-123");
        assert_eq!(sanitize_id("../evil"), "___evil");
    }

    #[test]
    fn templates_include_validation_summary() {
        let t = templates();
        assert_eq!(t["ok"], true);
        assert!(!t["templates"].as_array().unwrap().is_empty());
    }

    #[test]
    fn create_draft_has_sections() {
        let _guard = workspace_test_lock();
        use std::sync::atomic::{AtomicU64, Ordering};
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        let tmp = std::env::temp_dir().join(format!("ofdd-report-test-{}-{n}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", tmp.to_string_lossy().as_ref());
        let doc = create_draft(&json!({"title": "Test Report"}));
        assert_eq!(doc["ok"], true, "draft error: {:?}", doc.get("error"));
        assert!(doc["sections"].as_array().unwrap().len() >= 5);
        std::env::remove_var("OPENFDD_WORKSPACE");
        let _ = std::fs::remove_dir_all(tmp);
    }

    #[test]
    fn report_title_uses_request_not_hardcoded_bench() {
        let _guard = workspace_test_lock();
        use std::sync::atomic::{AtomicU64, Ordering};
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        let tmp =
            std::env::temp_dir().join(format!("ofdd-report-title-{}-{n}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", tmp.to_string_lossy().as_ref());

        let custom_title = "RCx Report — equip:custom-lab-99";
        let doc = create_draft(&json!({"title": custom_title}));
        assert_eq!(doc["ok"], true);
        assert_eq!(doc["title"].as_str(), Some(custom_title));
        let body = doc.to_string();
        let forbidden_bench = format!("{}-bench", 5007);
        let forbidden_equip = format!("equip:{}", 5007);
        let forbidden_actuator = format!("ACTUATOR-{}", 0);
        assert!(!body.contains(&forbidden_bench));
        assert!(!body.contains(&forbidden_equip));
        assert!(!body.contains(&forbidden_actuator));

        std::env::remove_var("OPENFDD_WORKSPACE");
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn list_delete_and_from_validation_run() {
        let _guard = workspace_test_lock();
        use std::sync::atomic::{AtomicU64, Ordering};
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        let tmp = std::env::temp_dir().join(format!("ofdd-report-list-{}-{n}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", tmp.to_string_lossy().as_ref());

        let listed = list_reports();
        assert_eq!(listed["ok"], true);

        let artifact = tmp.join("val");
        std::fs::create_dir_all(&artifact).unwrap();
        std::fs::write(
            artifact.join("summary.jsonl"),
            r#"{"bacnet_poll_ok":true,"modbus_ok":true,"haystack_ok":true,"csv_import_ok":true,"raw_fault_count":0,"confirmed_fault_count":0}"#,
        )
        .unwrap();

        let created = from_validation_run(&json!({
            "artifact_dir": artifact.to_string_lossy(),
            "validation_run_id": "run-test-1",
            "pass": true
        }));
        assert_eq!(created["ok"], true, "{created:?}");
        let rid = created["report_id"].as_str().unwrap();
        let again = list_reports();
        assert!(again["records"]
            .as_array()
            .unwrap()
            .iter()
            .any(|r| r.get("report_id").and_then(|v| v.as_str()) == Some(rid)));

        let del = delete_report(rid);
        assert_eq!(del["ok"], true);
        std::env::remove_var("OPENFDD_WORKSPACE");
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn from_fdd_sql_run_creates_report() {
        let _guard = workspace_test_lock();
        use std::sync::atomic::{AtomicU64, Ordering};
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        let tmp = std::env::temp_dir().join(format!("ofdd-fdd-report-{}-{n}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", tmp.to_string_lossy().as_ref());

        let out = from_fdd_sql_run(&json!({
            "rule_name": "OA temp high",
            "sql": "SELECT timestamp, oa_t FROM telemetry_pivot",
            "equipment_id": "equip:test",
            "fault_code": "OA_TEMP",
            "run_result": {
                "row_count": 2,
                "confirmation": {"raw_fault_count": 1, "confirmed_fault_count": 1},
                "rows": [{"timestamp": "2013-06-19T00:00:00Z", "confirmed_fault": true}]
            }
        }));
        assert_eq!(
            out.get("ok").and_then(|v| v.as_bool()),
            Some(true),
            "{out:?}"
        );
        assert_eq!(
            out.get("confirmed_fault_count").and_then(|v| v.as_u64()),
            Some(1)
        );

        std::env::remove_var("OPENFDD_WORKSPACE");
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
