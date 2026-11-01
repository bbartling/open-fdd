//! Immutable effective-run identity shared by aggregate, interval series, and persist.

use std::collections::HashMap;

use fdd_rules::{RuleRegistry, RuleSpec};
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
}

/// Inputs for loading a confirmed_fault series inside an open transaction.
pub(crate) struct LiveConfirmedFaultQuery<'a> {
    pub reg: &'a RuleRegistry,
    pub rule: &'a RuleSpec,
    pub building_id: &'a str,
    pub equipment_id: &'a str,
    pub window_start: Option<&'a str>,
    pub window_end: Option<&'a str>,
    pub ctx: &'a EffectiveRunContext,
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
