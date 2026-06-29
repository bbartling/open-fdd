//! Building insight agent — context-aware HVAC FDD summary with 15-minute cache + optional Ollama.

use super::{analytics, building_status, summary};
use crate::faults;
use crate::historian::store;
use crate::ops::ollama;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

pub const REFRESH_INTERVAL_S: i64 = 900;

fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

fn cache_path() -> PathBuf {
    workspace_dir().join("data/agent/building_insight_cache.json")
}

fn now_unix() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Generate or return cached building insight for the main dashboard.
pub fn generate(force: bool) -> Value {
    if !force {
        if let Some(cached) = read_cache() {
            let next = cached
                .get("next_refresh_at")
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            if next > now_unix() {
                let mut out = cached;
                out["cached"] = json!(true);
                return out;
            }
        }
    }

    let ctx = gather_context();
    let mut out = build_deterministic(&ctx);
    out["cached"] = json!(false);

    if let Ok(llm) = try_ollama_sentence(&ctx, &out) {
        out["sentence"] = json!(llm);
        out["source"] = json!("ollama");
        out["ollama_ok"] = json!(true);
    } else {
        out["source"] = json!("rules");
        out["ollama_ok"] = json!(false);
        if ollama::probe_quick().is_none() {
            out["error"] = json!("Ollama offline — showing rule-based HVAC summary");
        }
    }

    let ts = now_unix();
    out["generated_at"] = json!(ts);
    out["next_refresh_at"] = json!(ts + REFRESH_INTERVAL_S);
    out["refresh_interval_s"] = json!(REFRESH_INTERVAL_S);
    out["memory"] = ctx.get("memory").cloned().unwrap_or(json!({}));
    let _ = write_cache(&out);
    out
}

fn gather_context() -> Value {
    let sum = summary();
    let status = building_status();
    let anal = analytics();
    let fault_summary = sum
        .get("faults")
        .cloned()
        .unwrap_or_else(faults::summary_json);
    let active_count = fault_summary
        .get("active_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let coverage = sum.get("model_coverage").cloned().unwrap_or(json!({}));
    let eq_count = coverage
        .get("equipment_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let pt_count = coverage
        .get("point_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let mapped = coverage
        .get("mapped_points")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);

    let protocols = anal
        .get("source_coverage")
        .and_then(|v| v.get("protocols"))
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    let mut active_sources: Vec<String> = Vec::new();
    for p in &protocols {
        let name = p.get("protocol").and_then(|v| v.as_str()).unwrap_or("");
        let count = p.get("point_count").and_then(|v| v.as_u64()).unwrap_or(0);
        if count > 0 && name != "unmapped" {
            active_sources.push(format!("{name} ({count} pts)"));
        }
    }

    let historian = sum.get("historian_health").cloned().unwrap_or(json!({}));
    let row_count = historian
        .get("row_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    if row_count > 0 {
        if let Ok(rows) = store::load_pivot_rows() {
            let csv_rows = rows
                .iter()
                .filter(|r| {
                    r.get("source_driver").and_then(|v| v.as_str()) == Some("csv")
                        || r.get("source")
                            .and_then(|v| v.as_str())
                            .is_some_and(|s| s.starts_with("csv:") || s == "csv")
                })
                .count();
            if csv_rows > 0 && !active_sources.iter().any(|s| s.starts_with("csv")) {
                active_sources.push(format!("csv ({csv_rows} historian rows)"));
            }
        }
    }

    let deployment_mode = classify_deployment(&active_sources, eq_count, pt_count);

    let prior = read_cache()
        .and_then(|c| c.get("memory").cloned())
        .unwrap_or(json!({}));

    let active_issues = build_active_issues(active_count, &fault_summary, &coverage, &status);
    let memory = json!({
        "deployment_mode": deployment_mode,
        "active_sources": active_sources,
        "active_issues": active_issues,
        "prior_issues": prior.get("active_issues").cloned().unwrap_or(json!([])),
        "equipment_count": eq_count,
        "point_count": pt_count,
        "mapped_points": mapped,
        "historian_rows": row_count,
        "updated_at": now_unix()
    });

    json!({
        "deployment_mode": deployment_mode,
        "active_sources": active_sources,
        "active_count": active_count,
        "coverage": coverage,
        "fault_summary": fault_summary,
        "status": status,
        "historian_rows": row_count,
        "lookback_days": 14,
        "memory": memory
    })
}

fn classify_deployment(sources: &[String], eq: u64, pts: u64) -> &'static str {
    let joined = sources.join(" ").to_ascii_lowercase();
    let has_ot = joined.contains("bacnet")
        || joined.contains("modbus")
        || joined.contains("haystack")
        || joined.contains("json");
    let has_csv = joined.contains("csv") || joined.contains("import");
    match (has_ot, has_csv, eq, pts) {
        (true, true, _, _) => "mixed_ot_and_csv",
        (true, false, _, _) => "ot_lan_supervisory",
        (false, true, _, _) => "csv_analytics",
        (_, _, 0, 0) => "greenfield",
        _ => "model_only",
    }
}

fn build_active_issues(
    active_count: u64,
    fault_summary: &Value,
    coverage: &Value,
    status: &Value,
) -> Value {
    let mut issues = Vec::new();
    if active_count > 0 {
        issues.push(json!({
            "kind": "faults",
            "count": active_count,
            "detail": format!("{active_count} active FDD fault(s)")
        }));
    }
    let unmapped = coverage
        .get("unmapped_points")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    if unmapped > 0 {
        issues.push(json!({
            "kind": "model",
            "count": unmapped,
            "detail": format!("{unmapped} unmapped Haystack points")
        }));
    }
    let alert = status
        .get("alert_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    if alert > 0 && alert != active_count {
        issues.push(json!({
            "kind": "alerts",
            "count": alert,
            "detail": format!("{alert} dashboard alert(s)")
        }));
    }
    if let Some(families) = fault_summary.get("families").and_then(|v| v.as_array()) {
        for fam in families.iter().take(5) {
            let title = fam.get("title").and_then(|v| v.as_str()).unwrap_or("Fault");
            let count = fam.get("count").and_then(|v| v.as_u64()).unwrap_or(0);
            if count > 0 {
                issues.push(json!({
                    "kind": "family",
                    "title": title,
                    "count": count
                }));
            }
        }
    }
    json!(issues)
}

fn build_deterministic(ctx: &Value) -> Value {
    let mode = ctx
        .get("deployment_mode")
        .and_then(|v| v.as_str())
        .unwrap_or("model_only");
    let active = ctx
        .get("active_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let eq = ctx
        .get("coverage")
        .and_then(|c| c.get("equipment_count"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let pts = ctx
        .get("coverage")
        .and_then(|c| c.get("point_count"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let mapped = ctx
        .get("coverage")
        .and_then(|c| c.get("mapped_points"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let rows = ctx
        .get("historian_rows")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let sources = ctx
        .get("active_sources")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|v| v.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        })
        .unwrap_or_default();

    let mode_label = match mode {
        "csv_analytics" => "CSV analytics workflow",
        "ot_lan_supervisory" => "OT LAN supervisory (BACnet/field drivers)",
        "mixed_ot_and_csv" => "Mixed OT LAN + CSV historian",
        "greenfield" => "Greenfield — model not loaded",
        _ => "Haystack model",
    };

    let fault_part = if active == 0 {
        "No active FDD faults.".to_string()
    } else {
        format!("{active} active FDD fault(s) need review.")
    };

    let sentence = format!(
        "{mode_label}: {eq} equipment, {pts} points ({mapped} mapped). Sources: {}. Historian ~{rows} rows. {fault_part}",
        if sources.is_empty() { "none yet".into() } else { sources }
    );

    let device_sentence = if eq > 0 {
        Some(format!(
            "{mapped}/{pts} points mapped across {eq} equipment."
        ))
    } else {
        None
    };

    let fault_sentences: Vec<String> = ctx
        .get("memory")
        .and_then(|m| m.get("active_issues"))
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|i| i.get("detail").and_then(|v| v.as_str()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();

    json!({
        "ok": true,
        "stub": false,
        "sentence": sentence,
        "zone_sentence": null,
        "device_sentence": device_sentence,
        "lookback_days": ctx.get("lookback_days").cloned().unwrap_or(json!(14)),
        "fault_sentences": fault_sentences,
        "deployment_mode": mode,
        "methodology": {
            "lookback_days": 14,
            "context": "Live Haystack SPARQL model coverage, historian rows, active FDD faults, driver source protocols"
        },
        "device_poll_health": {
            "healthy_count": eq,
            "offline_equipment": [],
            "flaky_equipment": []
        },
        "zone_temps": {
            "topology_mode": mode,
            "zone_sensor_count": pts,
            "struggling_zones": [],
            "research": { "opportunities": [] },
            "refresh_interval_s": REFRESH_INTERVAL_S
        },
        "worst_zones": [],
        "brick_model": {
            "feeds_chains": [],
            "equipment_count": eq
        },
        "faults_linked": []
    })
}

fn try_ollama_sentence(ctx: &Value, base: &Value) -> Result<String, String> {
    let base_url = ollama::probe_quick().ok_or("ollama unavailable")?;
    let prompt = format!(
        "You are an HVAC fault-detection operator assistant for Open-FDD.\n\
         Deployment: {}\n\
         Data sources: {}\n\
         Equipment: {}, points: {}, active faults: {}\n\
         Prior issues memory: {}\n\
         Rule-based summary: {}\n\
         Write 2 concise sentences for the main dashboard: (1) what data path is active (CSV vs BACnet/OT LAN), \
         (2) top current HVAC/FDD concern or all-clear. Plain English, no markdown.",
        ctx.get("deployment_mode").and_then(|v| v.as_str()).unwrap_or("?"),
        ctx.get("active_sources").cloned().unwrap_or(json!([])),
        ctx.get("coverage")
            .and_then(|c| c.get("equipment_count"))
            .and_then(|v| v.as_u64())
            .unwrap_or(0),
        ctx.get("coverage")
            .and_then(|c| c.get("point_count"))
            .and_then(|v| v.as_u64())
            .unwrap_or(0),
        ctx.get("active_count").and_then(|v| v.as_u64()).unwrap_or(0),
        ctx.get("memory")
            .and_then(|m| m.get("prior_issues"))
            .cloned()
            .unwrap_or(json!([])),
        base.get("sentence").and_then(|v| v.as_str()).unwrap_or("")
    );
    let messages = vec![
        json!({"role": "system", "content": "HVAC FDD building insight — brief operator briefing only."}),
        json!({"role": "user", "content": prompt}),
    ];
    let result = ollama::chat_at(&base_url, &messages, None)?;
    let text = result.content.trim();
    if text.is_empty() {
        return Err("empty ollama response".into());
    }
    Ok(text.to_string())
}

fn read_cache() -> Option<Value> {
    let path = cache_path();
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

fn write_cache(doc: &Value) -> std::io::Result<()> {
    let path = cache_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(
        path,
        serde_json::to_string_pretty(doc).unwrap_or_else(|_| "{}".into()),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_csv_vs_ot() {
        assert_eq!(
            classify_deployment(&["csv (100 pts)".into()], 1, 100),
            "csv_analytics"
        );
        assert_eq!(
            classify_deployment(&["bacnet (50 pts)".into()], 5, 50),
            "ot_lan_supervisory"
        );
    }
}
