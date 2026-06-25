//! Write dev validation artifacts and call report APIs.

use super::api_health::EndpointResult;
use super::browser::BrowserSmokeSummary;
use super::fdd_analytics::FddAnalytics;
use super::sources::SourceValidationSummary;
use reqwest::blocking::Client;
use serde_json::{json, Value};
use std::fs;
use std::path::Path;

pub fn write_artifacts(
    output_dir: &Path,
    pass: bool,
    report: &Value,
    markdown: &str,
) -> Result<(), String> {
    fs::create_dir_all(output_dir).map_err(|e| e.to_string())?;
    fs::write(
        output_dir.join("dev_validation_report.json"),
        serde_json::to_string_pretty(report).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())?;
    fs::write(output_dir.join("dev_validation_report.md"), markdown).map_err(|e| e.to_string())?;
    let status = if pass { "PASS" } else { "FAIL" };
    fs::write(output_dir.join("status.txt"), status).map_err(|e| e.to_string())?;
    Ok(())
}

pub fn build_markdown(
    title: &str,
    pass: bool,
    api: &[EndpointResult],
    browser: &BrowserSmokeSummary,
    sources: &SourceValidationSummary,
    fdd: &FddAnalytics,
    pdf_path: Option<&str>,
) -> String {
    let mut md = format!(
        "# {title}\n\n**Overall:** {}\n\n",
        if pass { "PASS" } else { "FAIL" }
    );
    md.push_str("## API health\n\n| Endpoint | Status | Latency ms | Pass | Notes |\n|---|---:|---:|---:|---|\n");
    for row in api {
        md.push_str(&format!(
            "| `{}` | {} | {} | {} | {} |\n",
            row.endpoint,
            row.actual_status,
            row.latency_ms,
            if row.pass { "PASS" } else { "FAIL" },
            row.notes
        ));
    }
    md.push_str("\n## UI smoke\n\n");
    md.push_str(&format!(
        "- Pass: {}\n- Pages: {}\n- Console errors: {}\n- Failed API: {}\n- Artifacts: {}\n\n",
        browser.pass,
        browser.pages_visited.join(", "),
        browser.console_error_count,
        browser.failed_api_count,
        browser.artifact_dir
    ));
    md.push_str("## Data sources\n\n");
    md.push_str(&format!(
        "- BACnet: {} (samples {})\n- Modbus: {} ({})\n- JSON API: {} ({})\n- Haystack: {} ({})\n- CSV: {} ({})\n\n",
        sources.bacnet.status,
        sources.bacnet.sample_count,
        sources.modbus.status,
        sources.modbus.sample_count,
        sources.json_api.status,
        sources.json_api.sample_count,
        sources.haystack.status,
        sources.haystack.sample_count,
        sources.csv.status,
        sources.csv.sample_count
    ));
    md.push_str("## FDD analytics\n\n");
    md.push_str(&format!(
        "- Confirmation minutes: {}\n- Raw before confirmed: {}\n- Confirmed after delay: {}\n- Elapsed fault hours: {:.2}\n- Percent in fault: {:.1}%\n- Scenario backed: {}\n\n",
        fdd.confirmation_minutes,
        fdd.raw_fault_before_confirmed,
        fdd.confirmed_after_delay,
        fdd.elapsed_fault_hours,
        fdd.percent_window_in_fault,
        fdd.scenario_backed
    ));
    if let Some(path) = pdf_path {
        md.push_str(&format!("## PDF\n\n{path}\n"));
    }
    md
}

pub fn create_report_via_api(
    client: &Client,
    base_url: &str,
    token: &str,
    run_id: &str,
    artifact_dir: &str,
    pass: bool,
    harness: &Value,
) -> Result<Value, String> {
    let url = format!(
        "{}/api/reports/from-validation-run",
        base_url.trim_end_matches('/')
    );
    let body = json!({
        "validation_run_id": run_id,
        "artifact_dir": artifact_dir,
        "pass": pass,
        "harness": harness,
    });
    let resp = client
        .post(url)
        .header("Authorization", format!("Bearer {token}"))
        .json(&body)
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    let value: Value = resp.json().map_err(|e| e.to_string())?;
    if !status.is_success() || value.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return Err(format!(
            "report API failed: HTTP {status} — {}",
            value
                .get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
        ));
    }
    Ok(value)
}

pub fn verify_report_lifecycle(
    client: &Client,
    base_url: &str,
    token: &str,
    report_id: &str,
) -> Result<(), String> {
    let list_url = format!("{}/api/reports", base_url.trim_end_matches('/'));
    let list: Value = client
        .get(&list_url)
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .map_err(|e| e.to_string())?
        .json()
        .map_err(|e| e.to_string())?;
    let found = list
        .get("reports")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .any(|r| r.get("report_id").and_then(|v| v.as_str()) == Some(report_id))
        })
        .unwrap_or(false);
    if !found {
        return Err("report not listed".into());
    }
    let dl_url = format!(
        "{}/api/reports/{}/download.pdf",
        base_url.trim_end_matches('/'),
        report_id
    );
    let dl = client
        .get(dl_url)
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .map_err(|e| e.to_string())?;
    if !dl.status().is_success() {
        return Err(format!("download failed HTTP {}", dl.status()));
    }
    let del_url = format!(
        "{}/api/reports/{}",
        base_url.trim_end_matches('/'),
        report_id
    );
    let del = client
        .delete(del_url)
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .map_err(|e| e.to_string())?;
    if !del.status().is_success() {
        return Err(format!("delete failed HTTP {}", del.status()));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dev_validation::api_health::EndpointResult;

    #[test]
    fn markdown_includes_api_table() {
        let md = build_markdown(
            "Test",
            true,
            &[EndpointResult {
                endpoint: "/api/health".into(),
                method: "GET".into(),
                expected_status: 200,
                actual_status: 200,
                latency_ms: 1,
                pass: true,
                notes: String::new(),
            }],
            &Default::default(),
            &Default::default(),
            &Default::default(),
            None,
        );
        assert!(md.contains("API health"));
        assert!(md.contains("/api/health"));
    }
}
