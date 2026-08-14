//! Substitute runtime parameters into SQL rule templates.

use std::collections::HashMap;
use std::path::Path;

use serde_json::Value;

/// Replace `{{KEY}}` placeholders in SQL text.
///
/// Window-row placeholders derived from `*_HOURS` parameters are injected first
/// (see [`derive_window_row_params`]) so rolling rules can use literal `ROWS`
/// frame bounds.
pub fn substitute_sql(sql: &str, params: &HashMap<String, String>) -> String {
    let mut params = params.clone();
    for (k, v) in [
        ("FIXED_FLOW_HOURS", "1"),
        ("FIXED_FLOW_MAX_STD", "15"),
        ("FIXED_FLOW_MIN_MEAN", "200"),
        ("HIGH_MIN_FLOW_SP", "250"),
        ("FLOW_ON_MIN", "25"),
        ("FULL_OPEN_PCT", "0.975"),
        ("SUSTAIN_HOURS", "1.5"),
        ("HTG_FULL_MIN", "0.9"),
        ("SAT_ERR", "1"),
    ] {
        params.entry(k.into()).or_insert_with(|| v.into());
    }
    let derived = derive_window_row_params(&params);
    let mut out = sql.to_string();
    for (key, val) in params.iter().chain(derived.iter()) {
        out = out.replace(&format!("{{{{{key}}}}}"), val);
    }
    out
}

/// Row counts for rolling windows expressed in hours.
///
/// DataFusion requires `ROWS BETWEEN <n> PRECEDING` offsets to be integer
/// literals, so `CEIL({{X_HOURS}} * 3600 / {{POLL_SECONDS}})` cannot be written
/// inline. For every `<PREFIX>_HOURS` parameter this derives:
///
/// * `<PREFIX>_ROWS` — samples covered by the window (>= 1)
/// * `<PREFIX>_ROWS_PRECEDING` — `<PREFIX>_ROWS - 1`, the frame bound
///
/// Explicit values in `params` win, so a rule may still pin its own row count.
pub fn derive_window_row_params(params: &HashMap<String, String>) -> HashMap<String, String> {
    let poll = params
        .get("POLL_SECONDS")
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|v| *v > 0.0)
        .unwrap_or(300.0);
    let mut out = HashMap::new();
    for (key, val) in params {
        let Some(prefix) = key.strip_suffix("_HOURS") else {
            continue;
        };
        let Some(hours) = val
            .parse::<f64>()
            .ok()
            .filter(|h| h.is_finite() && *h > 0.0)
        else {
            continue;
        };
        let mut rows = ((hours * 3600.0 / poll).ceil() as i64).max(1);
        if prefix == "FIXED_FLOW" {
            rows = rows.max(6);
        }
        let rows_key = format!("{prefix}_ROWS");
        let preceding_key = format!("{prefix}_ROWS_PRECEDING");
        let min_periods_key = format!("{prefix}_MIN_PERIODS");
        if !params.contains_key(&rows_key) {
            out.insert(rows_key, rows.to_string());
        }
        if !params.contains_key(&preceding_key) {
            out.insert(preceding_key, (rows - 1).max(0).to_string());
        }
        if !params.contains_key(&min_periods_key) {
            out.insert(min_periods_key, (rows / 2).max(3).to_string());
        }
    }
    out
}

pub fn poll_params(poll_seconds: f64) -> HashMap<String, String> {
    let mut m = HashMap::new();
    m.insert("POLL_SECONDS".into(), format!("{poll_seconds}"));
    m
}

/// Per-rule params including confirm streak rows (Open-FDD ``confirm_fault`` parity).
pub fn rule_params(poll_seconds: f64, confirm_seconds: u32) -> HashMap<String, String> {
    let mut m = poll_params(poll_seconds);
    let rows = ((confirm_seconds as f64 / poll_seconds.max(1.0)).ceil() as u32).max(1);
    m.insert("CONFIRM_ROWS".into(), rows.to_string());
    m.insert("CONFIRM_SECONDS".into(), confirm_seconds.to_string());
    m
}

/// Read poll interval from ingest sidecar manifest written during ingest.
pub fn read_poll_from_cache(parquet_root: &Path) -> Option<f64> {
    let manifest = parquet_root.join("manifest.json");
    if !manifest.is_file() {
        return None;
    }
    let text = std::fs::read_to_string(&manifest).ok()?;
    let v: Value = serde_json::from_str(&text).ok()?;
    v.get("effective_poll_seconds")
        .and_then(|x| x.as_f64())
        .or_else(|| {
            v.get("grid_minutes")
                .and_then(|x| x.as_f64())
                .map(|m| m * 60.0)
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn substitutes_poll_seconds() {
        let sql = "COUNT(*) * {{POLL_SECONDS}} / 3600.0";
        let out = substitute_sql(sql, &poll_params(300.0));
        assert!(out.contains("300"));
        assert!(!out.contains("{{"));
    }

    #[test]
    fn confirm_rows_from_seconds() {
        let p = rule_params(300.0, 900);
        assert_eq!(p.get("CONFIRM_ROWS"), Some(&"3".to_string()));
        let p2 = rule_params(300.0, 0);
        assert_eq!(p2.get("CONFIRM_ROWS"), Some(&"1".to_string()));
    }

    #[test]
    fn window_rows_derived_from_hours() {
        let mut p = rule_params(300.0, 0);
        p.insert("FLATLINE_HOURS".into(), "1".into());
        p.insert("STALE_HOURS".into(), "2".into());
        let sql = "ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING, n={{STALE_ROWS}}";
        let out = substitute_sql(sql, &p);
        assert_eq!(out, "ROWS BETWEEN 11 PRECEDING, n=24");
    }

    #[test]
    fn window_rows_round_up_and_floor_at_one() {
        let mut p = rule_params(900.0, 0);
        p.insert("FLATLINE_HOURS".into(), "0.5".into());
        let d = derive_window_row_params(&p);
        assert_eq!(d.get("FLATLINE_ROWS"), Some(&"2".to_string()));
        assert_eq!(d.get("FLATLINE_ROWS_PRECEDING"), Some(&"1".to_string()));
    }
}
