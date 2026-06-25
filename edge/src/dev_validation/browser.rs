//! Browser/UI smoke integration via existing shell script.

use serde::{Deserialize, Serialize};
use std::path::Path;
use std::process::Command;

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct BrowserSmokeSummary {
    pub pass: bool,
    pub pages_visited: Vec<String>,
    pub console_error_count: u64,
    pub failed_api_count: u64,
    pub artifact_dir: String,
    pub notes: String,
}

pub fn run_ui_smoke(
    repo_root: &Path,
    base_url: &str,
    artifact_dir: &Path,
) -> Result<BrowserSmokeSummary, String> {
    let script = repo_root.join("scripts/openfdd_ui_smoke.sh");
    if !script.exists() {
        return Ok(BrowserSmokeSummary {
            pass: true,
            notes: "ui smoke script missing — skipped".into(),
            artifact_dir: artifact_dir.display().to_string(),
            ..Default::default()
        });
    }
    let browser_dir = artifact_dir.join("browser");
    std::fs::create_dir_all(&browser_dir).map_err(|e| e.to_string())?;
    let output = Command::new("bash")
        .arg(&script)
        .env("OPENFDD_API_BASE", base_url)
        .env("OPENFDD_UI_SMOKE_ARTIFACT", &browser_dir)
        .env("OPENFDD_UI_SMOKE_REPORTS", "1")
        .current_dir(repo_root)
        .output()
        .map_err(|e| format!("ui smoke: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let summary_path = browser_dir.join("browser_summary.json");
    if summary_path.exists() {
        if let Ok(text) = std::fs::read_to_string(&summary_path) {
            if let Ok(parsed) = serde_json::from_str::<BrowserSmokeSummary>(&text) {
                return Ok(parsed);
            }
        }
    }
    Ok(parse_smoke_log(
        &stdout,
        &browser_dir,
        output.status.success(),
    ))
}

fn parse_smoke_log(log: &str, artifact_dir: &Path, exit_ok: bool) -> BrowserSmokeSummary {
    let mut pages = Vec::new();
    let mut console_errors = 0_u64;
    let mut failed_api = 0_u64;
    for line in log.lines() {
        if line.starts_with("OK: route ") {
            pages.push(line.trim_start_matches("OK: route ").to_string());
        }
        if line.contains("console.error") || line.contains("FAIL:") {
            if line.contains("console") {
                console_errors += 1;
            }
            if line.contains("/api/") {
                failed_api += 1;
            }
        }
    }
    BrowserSmokeSummary {
        pass: exit_ok && failed_api == 0,
        pages_visited: pages,
        console_error_count: console_errors,
        failed_api_count: failed_api,
        artifact_dir: artifact_dir.display().to_string(),
        notes: if exit_ok {
            "ui smoke script completed".into()
        } else {
            "ui smoke script failed".into()
        },
    }
}

pub fn parse_browser_summary_json(value: &serde_json::Value) -> BrowserSmokeSummary {
    serde_json::from_value(value.clone()).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_smoke_log_lines() {
        let log = "OK: route /dashboard\nFAIL: /api/modbus/driver/tree HTTP 500\n";
        let summary = parse_smoke_log(log, Path::new("/tmp/ui"), false);
        assert_eq!(summary.pages_visited, vec!["/dashboard".to_string()]);
        assert!(summary.failed_api_count >= 1);
        assert!(!summary.pass);
    }
}
