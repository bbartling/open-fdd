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
        ("SETBACK_HI", "68"),
        ("FREE_COOL_OAT", "65"),
        ("REHEAT_PCT", "0.25"),
        ("RESET_ERR_F", "3"),
        ("RESET_SAT_AT_65", "52"),
        ("RESET_SLOPE", "0.25"),
        ("RESET_OAT_REF", "65"),
        ("ECON1_DAMPER_MAX", "0.05"),
        ("ECON1_OAT_MIN", "55"),
        ("ECON2_OAT_HI", "63"),
        ("ECON2_DAMPER", "0.42"),
        ("DUCT_HIGH_MARGIN", "0.25"),
        ("PRESSURE_ON_MIN", "0.2"),
        ("ALWAYS_ON_PCT", "0.95"),
        // Wave B / 3.3.28 Lab residual thresholds (registry defaults)
        ("CLG_OPEN_MIN", "0.01"),
        ("HTG_OPEN_MIN", "0.01"),
        ("FLOW_BIAS_CFM", "50"),
        ("DAMPER_CLOSED_MAX", "0.10"),
        ("LOAD_SAT_HI", "0.5"),
        // Wave G Lab tuner parity (Vibe19)
        ("FAN_ON_MIN", "0.01"),
        ("EPS_MAT", "1.15"),
        ("EPS_OAT", "1.15"),
        ("EPS_RAT", "1.15"),
        ("EPS_SAT", "1.15"),
        ("MIX_TOL", "1.15"),
        ("SUPPLY_TOL", "1.15"),
        ("MODE_DELAY_MIN", "10"),
        ("STARTUP_DELAY_MIN", "0"),
        ("REQUIRE_OPERATIONAL_GATE", "1"),
        ("MINIMUM_ACTIVE_COVERAGE_PCT", "5"),
        ("ECON_FULL_OPEN", "0.9"),
        ("ECON_MIN_POS", "0.05"),
        ("CLG_INACTIVE_MAX", "0.01"),
        ("CLG_ON_MIN", "0.01"),
        ("HTG_ON_MIN", "0.01"),
        ("DELTA_SUPPLY_FAN", "0.55"),
        ("EPS_AIRFLOW", "0.15"),
        ("OAT_RAT_DELTA_MIN", "5"),
        ("EPS_CCET", "1.15"),
        ("EPS_CCLT", "1.15"),
        ("EPS_HCET", "1.15"),
        ("EPS_HCLT", "1.15"),
        ("CLG_FULL_MIN", "0.9"),
        ("SPIKE_SCALE", "1"),
        ("SPIKE_SCALE_TEMPERATURE", "1"),
        ("SPIKE_SCALE_HUMIDITY", "1"),
        ("SPIKE_SCALE_PRESSURE", "1"),
        ("DESIGN_FLOW", "1000"),
        ("MAX_GAP_HOURS", "1"),
        ("SENSOR_SPAN", "100"),
    ] {
        params.entry(k.into()).or_insert_with(|| v.into());
    }
    // Legacy mix_tol / supply_tol masters fill per-sensor eps when unset.
    if let Some(mt) = params.get("MIX_TOL").cloned() {
        for k in ["EPS_MAT", "EPS_OAT", "EPS_RAT", "EPS_SAT"] {
            params.entry(k.into()).or_insert_with(|| mt.clone());
        }
    }
    if let Some(st) = params.get("SUPPLY_TOL").cloned() {
        params.insert("EPS_SAT".into(), st);
    }
    // Startup delay raises mode-delay holdoff when larger.
    let mode = params
        .get("MODE_DELAY_MIN")
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(0.0);
    let startup = params
        .get("STARTUP_DELAY_MIN")
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(0.0);
    if startup > mode {
        params.insert("MODE_DELAY_MIN".into(), format_number(startup));
    }
    let derived = derive_window_row_params(&params);
    let mut out = sql.to_string();
    for (key, val) in params.iter().chain(derived.iter()) {
        out = out.replace(&format!("{{{{{key}}}}}"), val);
    }
    out
}

fn format_number(v: f64) -> String {
    if (v.fract()).abs() < 1e-9 {
        format!("{:.0}", v)
    } else {
        format!("{v}")
    }
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
    // Wave G: MODE_DELAY_MIN / STARTUP_DELAY_MIN (minutes) → *_ROWS / *_ROWS_PRECEDING
    for key in ["MODE_DELAY_MIN", "STARTUP_DELAY_MIN"] {
        let Some(minutes) = params.get(key).and_then(|v| v.parse::<f64>().ok()) else {
            continue;
        };
        if !minutes.is_finite() || minutes < 0.0 {
            continue;
        }
        let prefix = key.strip_suffix("_MIN").unwrap();
        let rows = if minutes <= 0.0 {
            1_i64
        } else {
            ((minutes * 60.0 / poll).ceil() as i64).max(1)
        };
        let rows_key = format!("{prefix}_ROWS");
        let preceding_key = format!("{prefix}_ROWS_PRECEDING");
        if !params.contains_key(&rows_key) && !out.contains_key(&rows_key) {
            out.insert(rows_key, rows.to_string());
        }
        if !params.contains_key(&preceding_key) && !out.contains_key(&preceding_key) {
            out.insert(preceding_key, (rows - 1).max(0).to_string());
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

fn json_as_f64(v: &Value) -> Option<f64> {
    v.as_f64()
        .or_else(|| v.as_u64().map(|n| n as f64))
        .or_else(|| v.as_i64().map(|n| n as f64))
}

fn poll_from_manifest_json(v: &Value) -> Option<f64> {
    v.get("effective_poll_seconds")
        .and_then(json_as_f64)
        .or_else(|| {
            v.get("grid_minutes")
                .and_then(json_as_f64)
                .map(|m| m * 60.0)
        })
}

/// Read poll interval from ingest sidecar manifest written during ingest.
pub fn read_poll_from_cache(parquet_root: &Path) -> Option<f64> {
    let mut dirs = vec![parquet_root.to_path_buf()];
    if parquet_root
        .file_name()
        .and_then(|s| s.to_str())
        .is_some_and(|s| s.starts_with("building="))
    {
        if let Some(parent) = parquet_root.parent() {
            dirs.push(parent.to_path_buf());
        }
    }
    for dir in dirs {
        let manifest = dir.join("manifest.json");
        if !manifest.is_file() {
            continue;
        }
        let text = std::fs::read_to_string(&manifest).ok()?;
        let v: Value = serde_json::from_str(&text).ok()?;
        if let Some(poll) = poll_from_manifest_json(&v) {
            return Some(poll);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn read_poll_from_building_scoped_parent_manifest() {
        let tmp = std::env::temp_dir().join(format!("poll_cache_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(tmp.join("building=B1")).unwrap();
        std::fs::write(
            tmp.join("manifest.json"),
            r#"{"grid_minutes":1,"effective_poll_seconds":60}"#,
        )
        .unwrap();
        let scoped = tmp.join("building=B1");
        assert_eq!(read_poll_from_cache(&scoped), Some(60.0));
        let _ = std::fs::remove_dir_all(&tmp);
    }

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
    fn mode_delay_min_derives_rows() {
        let mut p = rule_params(300.0, 0);
        p.insert("MODE_DELAY_MIN".into(), "10".into());
        let d = derive_window_row_params(&p);
        assert_eq!(d.get("MODE_DELAY_ROWS"), Some(&"2".to_string())); // 10min / 5min poll
        assert_eq!(d.get("MODE_DELAY_ROWS_PRECEDING"), Some(&"1".to_string()));
        let sql = "ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING";
        let out = substitute_sql(sql, &p);
        assert_eq!(out, "ROWS BETWEEN 1 PRECEDING");
    }
}
