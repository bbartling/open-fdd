//! Immutable effective-run identity shared by aggregate, interval series, and persist.

use std::collections::HashMap;

use fdd_rules::RuleSpec;
use serde_json::Value;

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct EffectiveRunContext {
    pub poll_seconds: f64,
    pub confirm_seconds: u32,
    pub session_override: Option<HashMap<String, f64>>,
}

impl EffectiveRunContext {
    pub(crate) fn from_run_row(row: &Value, commit_poll: f64) -> Self {
        let poll = row
            .get("poll_seconds")
            .and_then(Value::as_f64)
            .filter(|v| v.is_finite() && *v > 0.0)
            .unwrap_or(commit_poll)
            .max(1.0);
        let confirm = row
            .get("confirm_seconds")
            .and_then(Value::as_f64)
            .filter(|v| v.is_finite() && *v >= 0.0)
            .map(|v| v.round() as u32)
            .unwrap_or(0);
        let session_override = row.get("session_params").and_then(session_params_from_json);
        Self {
            poll_seconds: poll,
            confirm_seconds: confirm,
            session_override,
        }
    }

    pub(crate) fn for_rule_catalog(rule: &RuleSpec, poll_seconds: f64) -> Self {
        Self {
            poll_seconds: poll_seconds.max(1.0),
            confirm_seconds: rule.confirm_seconds,
            session_override: None,
        }
    }
}

fn session_params_from_json(value: &Value) -> Option<HashMap<String, f64>> {
    let obj = value.as_object()?;
    let mut out = HashMap::new();
    for (k, v) in obj {
        let n = v.as_f64().or_else(|| v.as_i64().map(|i| i as f64))?;
        if n.is_finite() {
            out.insert(k.clone(), n);
        }
    }
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}
