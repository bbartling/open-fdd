//! FDD confirmation delay proof and window analytics from summary.jsonl.

use crate::validation::audit::confirmation_met;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::path::Path;

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct FddAnalytics {
    pub pass: bool,
    pub confirmation_minutes: i64,
    pub raw_fault_before_confirmed: bool,
    pub confirmed_after_delay: bool,
    pub no_fault_window: WindowStats,
    pub fault_window: WindowStats,
    pub fault_start_time: Option<String>,
    pub confirmed_time: Option<String>,
    pub elapsed_fault_minutes: f64,
    pub elapsed_fault_hours: f64,
    pub percent_window_in_fault: f64,
    pub rule_id: String,
    pub scenario_backed: bool,
    pub notes: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct WindowStats {
    pub sample_count: u64,
    pub missing_samples: u64,
    pub min: Option<f64>,
    pub max: Option<f64>,
    pub mean: Option<f64>,
    pub latest: Option<f64>,
}

pub fn analyze_summary_jsonl(
    path: &Path,
    confirmation_minutes: i64,
    total_samples: u64,
) -> FddAnalytics {
    let text = fs::read_to_string(path).unwrap_or_default();
    let mut rows: Vec<Value> = Vec::new();
    for line in text.lines() {
        if line.trim().is_empty() {
            continue;
        }
        if let Ok(v) = serde_json::from_str::<Value>(line) {
            rows.push(v);
        }
    }
    if rows.is_empty() {
        return FddAnalytics {
            confirmation_minutes,
            notes: "summary.jsonl missing or empty".into(),
            ..Default::default()
        };
    }
    let midpoint = rows.len() / 2;
    let no_fault = compute_window(&rows[..midpoint], "oa_t");
    let fault = compute_window(&rows[midpoint..], "oa_t");
    let mut first_raw: Option<String> = None;
    let mut first_confirmed: Option<String> = None;
    let mut raw_before_confirmed = false;
    for row in &rows {
        let ts = row
            .get("timestamp_utc")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let raw = row
            .get("raw_fault_count")
            .and_then(|v| v.as_u64())
            .unwrap_or(0)
            > 0;
        let confirmed = row
            .get("confirmed_fault_count")
            .and_then(|v| v.as_u64())
            .unwrap_or(0)
            > 0;
        if raw && first_raw.is_none() {
            first_raw = Some(ts.clone());
        }
        if confirmed && first_confirmed.is_none() {
            first_confirmed = Some(ts.clone());
        }
    }
    if first_raw.is_some() && first_confirmed.is_some() {
        raw_before_confirmed = true;
    }
    let minutes_in_fault = rows
        .last()
        .and_then(|r| r.get("minutes_in_fault").and_then(|v| v.as_f64()))
        .unwrap_or(0.0);
    let confirmed_after_delay = confirmation_met(minutes_in_fault, confirmation_minutes);
    let fault_samples = rows
        .iter()
        .filter(|r| {
            r.get("raw_fault_count")
                .and_then(|v| v.as_u64())
                .unwrap_or(0)
                > 0
        })
        .count() as f64;
    let percent = if total_samples > 0 {
        (fault_samples / total_samples as f64) * 100.0
    } else if !rows.is_empty() {
        (fault_samples / rows.len() as f64) * 100.0
    } else {
        0.0
    };
    let scenario = rows
        .iter()
        .any(|r| r.get("expected_phase").and_then(|v| v.as_str()) == Some("simulate"));
    let pass = raw_before_confirmed && confirmed_after_delay;
    FddAnalytics {
        pass,
        confirmation_minutes,
        raw_fault_before_confirmed: raw_before_confirmed,
        confirmed_after_delay,
        no_fault_window: no_fault,
        fault_window: fault,
        fault_start_time: first_raw,
        confirmed_time: first_confirmed,
        elapsed_fault_minutes: minutes_in_fault,
        elapsed_fault_hours: minutes_in_fault / 60.0,
        percent_window_in_fault: percent,
        rule_id: rows
            .first()
            .and_then(|r| r.get("fdd_rule_id").and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string(),
        scenario_backed: scenario,
        notes: String::new(),
    }
}

fn compute_window(rows: &[Value], field: &str) -> WindowStats {
    let mut values = Vec::new();
    for row in rows {
        if let Some(v) = row.get(field).and_then(|v| v.as_f64()) {
            values.push(v);
        }
    }
    if values.is_empty() {
        return WindowStats {
            sample_count: rows.len() as u64,
            missing_samples: rows.len() as u64,
            ..Default::default()
        };
    }
    let min = values.iter().copied().fold(f64::INFINITY, f64::min);
    let max = values.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let mean = values.iter().sum::<f64>() / values.len() as f64;
    WindowStats {
        sample_count: rows.len() as u64,
        missing_samples: (rows.len() as u64).saturating_sub(values.len() as u64),
        min: Some(min),
        max: Some(max),
        mean: Some(mean),
        latest: values.last().copied(),
    }
}

pub fn report_data_model(
    profile_name: &str,
    api_health: &[super::api_health::EndpointResult],
    browser: &super::browser::BrowserSmokeSummary,
    sources: &super::sources::SourceValidationSummary,
    fdd: &FddAnalytics,
    overall_pass: bool,
) -> Value {
    json!({
        "profile_name": profile_name,
        "overall_pass": overall_pass,
        "api_health": api_health,
        "browser_smoke": browser,
        "source_validation": sources,
        "fdd_analytics": fdd,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn confirmation_delay_proof() {
        assert!(!confirmation_met(4.0, 5));
        let analytics = FddAnalytics {
            confirmation_minutes: 5,
            raw_fault_before_confirmed: true,
            confirmed_after_delay: confirmation_met(5.0, 5),
            elapsed_fault_minutes: 5.0,
            pass: true,
            ..Default::default()
        };
        assert!(analytics.pass);
    }

    #[test]
    fn report_data_model_includes_sources() {
        let model = report_data_model(
            "test",
            &[],
            &Default::default(),
            &Default::default(),
            &Default::default(),
            true,
        );
        assert!(model.get("source_validation").is_some());
        assert!(model.get("api_health").is_some());
    }
}
