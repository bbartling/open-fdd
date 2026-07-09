//! Substitute runtime parameters into SQL rule templates.

use std::collections::HashMap;
use std::path::Path;

use serde_json::Value;

/// Replace `{{KEY}}` placeholders in SQL text.
pub fn substitute_sql(sql: &str, params: &HashMap<String, String>) -> String {
    let mut out = sql.to_string();
    for (key, val) in params {
        out = out.replace(&format!("{{{{{key}}}}}"), val);
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
}
