//! Shared bench smoke status for API/UI.

use crate::bench::smoke::SmokeOutcome;
use serde_json::{json, Value};
use std::sync::{Mutex, OnceLock};

#[derive(Clone, Debug, Default)]
pub struct SmokeStatus {
    pub running: bool,
    pub last_pass: Option<bool>,
    pub last_report_dir: Option<String>,
    pub last_error: Option<String>,
    pub last_finished_at: Option<String>,
}

static STATUS: OnceLock<Mutex<SmokeStatus>> = OnceLock::new();

fn status_lock() -> &'static Mutex<SmokeStatus> {
    STATUS.get_or_init(|| Mutex::new(SmokeStatus::default()))
}

pub fn mark_running() {
    if let Ok(mut s) = status_lock().lock() {
        s.running = true;
        s.last_error = None;
    }
}

pub fn mark_finished(outcome: &SmokeOutcome) {
    if let Ok(mut s) = status_lock().lock() {
        s.running = false;
        s.last_pass = Some(outcome.pass);
        s.last_report_dir = Some(outcome.report.config.report_dir.clone());
        s.last_finished_at = Some(outcome.report.ended_at.to_rfc3339());
        s.last_error = if outcome.pass {
            None
        } else {
            Some(outcome.failure_reasons.join("; "))
        };
    }
}

pub fn mark_failed(err: &str) {
    if let Ok(mut s) = status_lock().lock() {
        s.running = false;
        s.last_pass = Some(false);
        s.last_error = Some(err.to_string());
    }
}

pub fn status_json() -> Value {
    let s = status_lock().lock().map(|s| s.clone()).unwrap_or_default();
    json!({
        "ok": true,
        "running": s.running,
        "last_pass": s.last_pass,
        "last_report_dir": s.last_report_dir,
        "last_error": s.last_error,
        "last_finished_at": s.last_finished_at,
        "report_files": [
            "final_report.json",
            "final_report.md",
            "events.csv",
            "samples_summary.csv",
            "rule_phase_results.csv"
        ]
    })
}
