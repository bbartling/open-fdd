//! Model-driven report drafts and HTML/PDF export bundles (Rust-era, no Python).

use crate::fdd::rules;
use crate::faults;
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
    let report_id = format!("rpt-{}", Utc::now().timestamp_millis());
    let coverage = query::model_coverage();
    let equips = query::list_equips(None);
    let hist_status = store::status_json();
    let mut sections = vec![
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
    ];
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
            let stitle = sec.get("title").and_then(|v| v.as_str()).unwrap_or("Section");
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
            let body = serde_json::to_string(sec.get("content").unwrap_or(&json!({})))
                .unwrap_or_default();
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_report_id() {
        assert_eq!(sanitize_id("rpt-123"), "rpt-123");
        assert_eq!(sanitize_id("../evil"), "____evil");
    }

    #[test]
    fn templates_include_validation_summary() {
        let t = templates();
        assert_eq!(t["ok"], true);
        assert!(t["templates"].as_array().unwrap().len() >= 1);
    }

    #[test]
    fn create_draft_has_sections() {
        let doc = create_draft(&json!({"title": "Test Report"}));
        assert_eq!(doc["ok"], true);
        assert!(doc["sections"].as_array().unwrap().len() >= 5);
    }
}
