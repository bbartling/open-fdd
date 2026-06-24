//! Dashboard analytics API (Haystack model + historian + DataFusion faults).

use crate::data_management;
use crate::drivers::bacnet;
use crate::export;
use crate::faults;
use crate::historian::store;
use crate::model::query;
use serde_json::{json, Value};
use std::env;

fn protocol_enabled(env_key: &str) -> bool {
    env::var(env_key)
        .map(|v| v != "0" && v.to_lowercase() != "false")
        .unwrap_or(true)
}

fn service_status(id: &str, enabled: bool, label: &str, detail: &str) -> Value {
    if enabled {
        json!({
            "id": id,
            "label": label,
            "status": "green",
            "configured": true,
            "detail": detail
        })
    } else {
        json!({
            "id": id,
            "label": label,
            "status": "gray",
            "configured": false,
            "detail": detail
        })
    }
}

pub fn stack_health() -> Value {
    let bacnet_on = protocol_enabled("OPENFDD_BACNET_ENABLED");
    let modbus_on = protocol_enabled("OPENFDD_MODBUS_ENABLED");
    let haystack_on = protocol_enabled("OPENFDD_HAYSTACK_ENABLED");
    let json_api_on = protocol_enabled("OPENFDD_JSON_API_ENABLED");
    let import_on = protocol_enabled("OPENFDD_IMPORT_ENABLED");
    let export_on = protocol_enabled("OPENFDD_EXPORT_ENABLED");

    let csv_on = import_on || export_on;
    let csv_detail = match (import_on, export_on) {
        (true, true) => "Import + export sidecars ready",
        (true, false) => "Import sidecar ready · export disabled",
        (false, true) => "Export sidecar ready · import disabled",
        (false, false) => "Disabled — OPENFDD_IMPORT_ENABLED=0 and OPENFDD_EXPORT_ENABLED=0",
    };

    let services = vec![
        service_status(
            "openfdd-bridge",
            true,
            "API + dashboard + historian",
            "Rust edge bridge online",
        ),
        service_status(
            "bacnet",
            bacnet_on,
            "BACnet",
            if bacnet_on {
                "Commission/poll ready"
            } else {
                "Disabled — OPENFDD_BACNET_ENABLED=0"
            },
        ),
        service_status(
            "modbus",
            modbus_on,
            "Modbus",
            if modbus_on {
                "Sidecar ready"
            } else {
                "Disabled — OPENFDD_MODBUS_ENABLED=0"
            },
        ),
        service_status(
            "haystack",
            haystack_on,
            "Haystack gateway",
            if haystack_on {
                "Model navigation ready"
            } else {
                "Disabled — OPENFDD_HAYSTACK_ENABLED=0"
            },
        ),
        service_status(
            "json-api",
            json_api_on,
            "JSON API ingest",
            if json_api_on { "Enabled" } else { "Disabled" },
        ),
        service_status("csv-sidecars", csv_on, "CSV sidecars", csv_detail),
        service_status(
            "arrow-datafusion",
            true,
            "Arrow + DataFusion",
            "Rule SQL engine ready",
        ),
    ];

    let overall = if services.iter().any(|s| s["status"] == "red") {
        "red"
    } else if services.iter().any(|s| s["status"] == "yellow") {
        "yellow"
    } else {
        "green"
    };

    json!({
        "ok": true,
        "overall": overall,
        "services": services,
        "bacnet_bind": env::var("OPENFDD_BACNET_BIND").ok()
    })
}

pub fn building_snapshot() -> Value {
    json!({
        "stack": stack_health(),
        "faults": faults::status_json()
    })
}

/// Minimal stub until the Python-era building-insight agent is ported.
pub fn building_insight_stub() -> Value {
    json!({
        "ok": true,
        "generated_at": null,
        "lookback_days": 14,
        "device_sentence": null,
        "device_poll_health": {
            "healthy_count": 0,
            "offline_equipment": [],
            "flaky_equipment": []
        },
        "zone_temps": null,
        "worst_zones": [],
        "brick_model": { "feeds_chains": [], "equipment_count": 0 }
    })
}

pub fn building_status() -> Value {
    let coverage = query::model_coverage();
    let fault_summary = faults::summary_json();
    json!({
        "ok": true,
        "model_score": coverage.get("model_score").cloned().unwrap_or(json!(null)),
        "model_counts": {
            "equipment": coverage.get("equipment_count").cloned().unwrap_or(json!(0)),
            "points": coverage.get("point_count").cloned().unwrap_or(json!(0))
        },
        "alert_count": fault_summary.get("active_count").cloned().unwrap_or(json!(0))
    })
}

pub fn summary() -> Value {
    let coverage = query::model_coverage();
    let sources = source_health();
    let historian = historian_health();
    let fault_summary = faults::summary_json();
    let overrides = bacnet_override_counts();
    json!({
        "ok": true,
        "portfolio": {
            "sites": query::list_sites()["sites"].clone(),
            "site_count": query::list_sites()["sites"].as_array().map(|a| a.len()).unwrap_or(0)
        },
        "model_coverage": coverage,
        "source_health": sources,
        "historian_health": historian,
        "faults": fault_summary,
        "bacnet_overrides": overrides,
        "validation": validation_status(),
        "data_management": data_management::storage_summary(),
        "security": security_status()
    })
}

pub fn sites() -> Value {
    query::list_sites()
}

pub fn faults_panel() -> Value {
    faults::list_json(None)
}

pub fn faults_active() -> Value {
    faults::list_json(Some("active"))
}

pub fn faults_history() -> Value {
    faults::list_json(Some("history"))
}

pub fn model_coverage_route() -> Value {
    query::model_coverage()
}

pub fn source_health() -> Value {
    let coverage = query::source_coverage();
    let protocols = coverage
        .get("protocols")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut rows = Vec::new();
    for key in [
        ("bacnet", "OPENFDD_BACNET_ENABLED"),
        ("modbus", "OPENFDD_MODBUS_ENABLED"),
        ("haystack", "OPENFDD_HAYSTACK_ENABLED"),
        ("json_api", "OPENFDD_JSON_API_ENABLED"),
        ("csv_import", "OPENFDD_IMPORT_ENABLED"),
        ("postgres", "OPENFDD_POSTGRES_ENABLED"),
    ] {
        let enabled = protocol_enabled(key.1);
        let point_count = protocols
            .iter()
            .find(|p| p.get("protocol").and_then(|v| v.as_str()) == Some(key.0))
            .and_then(|p| p.get("point_count").and_then(|v| v.as_u64()))
            .unwrap_or(0);
        rows.push(json!({
            "protocol": key.0,
            "enabled": enabled,
            "status": if enabled { "ready" } else { "disabled" },
            "point_count": point_count,
            "note": if enabled { json!(null) } else { json!(format!("{}=0", key.1)) }
        }));
    }
    json!({"ok": true, "sources": rows})
}

pub fn historian_health() -> Value {
    let rows = store::load_pivot_rows().unwrap_or_default();
    let latest = rows
        .last()
        .and_then(|r| r.get("timestamp").and_then(|v| v.as_str()))
        .unwrap_or("");
    let subdirs = store::list_historian_subdirs();
    let row_count = store::row_count_in(&store::historian_subdir());
    json!({
        "ok": true,
        "row_count": row_count,
        "latest_sample_at": latest,
        "subdir_count": subdirs.len(),
        "subdirs": subdirs,
        "storage_label": export::meta_json()["exports"]
            .as_array()
            .and_then(|a| a.first())
            .and_then(|e| e.get("data_source_label"))
            .cloned()
            .unwrap_or(json!("unknown"))
    })
}

pub fn security_status() -> Value {
    let caddy_enabled = env::var("OPENFDD_CADDY_ENABLED")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    let caddy_mode = env::var("OPENFDD_CADDY_MODE").unwrap_or_else(|_| "off".into());
    let tls = caddy_mode.eq_ignore_ascii_case("tls");
    let auth_required = crate::auth::config::AuthConfig::load().required;
    json!({
        "ok": true,
        "auth_required": auth_required,
        "caddy": {
            "enabled": caddy_enabled,
            "mode": caddy_mode,
            "hostname": env::var("OPENFDD_CADDY_HOSTNAME").unwrap_or_else(|_| "openfdd.local".into()),
            "tls_cn": env::var("OPENFDD_CADDY_TLS_CN").unwrap_or_else(|_| "openfdd.local".into()),
            "cert_dir": env::var("OPENFDD_CADDY_CERT_DIR").unwrap_or_else(|_| "workspace/deploy/caddy/certs".into())
        },
        "tls_active": tls,
        "ingress": if caddy_enabled {
            format!("caddy/{caddy_mode}")
        } else {
            "direct".into()
        }
    })
}

pub fn analytics() -> Value {
    let coverage = query::model_coverage();
    let fault_trend = faults::history_trend();
    json!({
        "ok": true,
        "model": coverage,
        "unmapped_points": query::unmapped_points(),
        "points_by_equip": query::group_points_by_equip(),
        "source_coverage": query::source_coverage(),
        "fault_trend": fault_trend,
        "top_faulted_equipment": faults::top_faulted_equipment(),
        "rule_health": faults::rule_health(),
        "bacnet_overrides": bacnet_override_counts()
    })
}

fn bacnet_override_counts() -> Value {
    if !protocol_enabled("OPENFDD_BACNET_ENABLED") {
        return json!({
            "ok": true,
            "available": false,
            "priority8_count": 0,
            "other_priority_count": 0,
            "total": 0,
            "note": "BACnet disabled"
        });
    }
    let scan = bacnet::overrides_last_scan();
    let events = scan
        .get("overrides")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut p8 = 0_usize;
    let mut other = 0_usize;
    for ev in events {
        let priority = ev.get("priority").and_then(|v| v.as_u64()).unwrap_or(0);
        if priority == 8 {
            p8 += 1;
        } else if priority > 0 {
            other += 1;
        }
    }
    json!({
        "ok": true,
        "available": true,
        "priority8_count": p8,
        "other_priority_count": other,
        "total": p8 + other,
        "last_scan_at": scan.get("scanned_at").cloned().unwrap_or(json!(null))
    })
}

fn validation_status() -> Value {
    let profile = crate::validation::profile::active_profile();
    json!({
        "ok": true,
        "profile_id": profile.profile_id,
        "live_fdd_pass": env::var("OPENFDD_LIVE_FDD_PASS").unwrap_or_else(|_| "unknown".into())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn summary_includes_core_sections() {
        let body = summary();
        assert_eq!(body.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert!(body.get("model_coverage").is_some());
        assert!(body.get("source_health").is_some());
        assert!(body.get("historian_health").is_some());
        assert!(body.get("faults").is_some());
        assert!(body.get("security").is_some());
    }

    #[test]
    fn stack_health_uses_traffic_colors() {
        let body = stack_health();
        assert_eq!(body.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert!(body.get("overall").is_some());
        assert!(body.get("services").and_then(|v| v.as_array()).is_some());
    }
}
