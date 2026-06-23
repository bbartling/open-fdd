//! Read-only Postgres data-lake adapter (template-driven, demo-safe).

use crate::connectors::registry::load_source_config;
use crate::connectors::secrets::{redact_connection_string, resolve_secret};
use crate::connectors::sql_safety::{bind_template, is_connector_sql_safe, validate_connector_sql};
use crate::connectors::types::PostgresConfig;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::PathBuf;

pub fn parse_config(raw: &Value) -> Result<PostgresConfig, String> {
    serde_json::from_value(raw.clone()).map_err(|e| e.to_string())
}

pub fn test_connection(source_id: &str) -> Value {
    let Ok(raw) = load_source_config(source_id) else {
        return json!({"ok": false, "error": "config load failed"});
    };
    let Ok(cfg) = parse_config(&raw) else {
        return json!({"ok": false, "error": "invalid config"});
    };
    if demo_mode(&cfg) {
        return json!({
            "ok": true,
            "source_id": source_id,
            "mode": "demo",
            "connection": redact_connection_string("postgres://***:***@demo-db.example.com/readonly"),
            "message": "Local DSN secret not configured — demo catalog only"
        });
    }
    json!({
        "ok": true,
        "source_id": source_id,
        "mode": "configured",
        "connection": redact_connection_string(
            &resolve_secret(&cfg.connection_secret_ref).unwrap_or_default()
        ),
        "message": "DSN secret present; live query requires local Postgres"
    })
}

pub fn discover_catalog(source_id: &str) -> Value {
    let Ok(raw) = load_source_config(source_id) else {
        return json!({"ok": false, "error": "config load failed"});
    };
    let Ok(cfg) = parse_config(&raw) else {
        return json!({"ok": false, "error": "invalid config"});
    };
    let sql = load_sql_file(&cfg.catalog_sql_path);
    if !is_connector_sql_safe(&sql) {
        return json!({"ok": false, "error": "unsafe catalog SQL", "validation": validate_connector_sql(&sql)});
    }
    if demo_mode(&cfg) {
        return json!({
            "ok": true,
            "source_id": source_id,
            "mode": "demo",
            "points": demo_catalog_points(),
            "sql_preview": "SELECT point_id, point_name, units FROM point_catalog LIMIT 100"
        });
    }
    json!({
        "ok": true,
        "source_id": source_id,
        "mode": "configured",
        "sql_preview": redact_sql_preview(&sql),
        "message": "Execute catalog query against local read-only Postgres"
    })
}

pub fn preview_query(source_id: &str, template_kind: &str, params: &Value) -> Value {
    let Ok(raw) = load_source_config(source_id) else {
        return json!({"ok": false, "error": "config load failed"});
    };
    let Ok(cfg) = parse_config(&raw) else {
        return json!({"ok": false, "error": "invalid config"});
    };
    let path = match template_kind {
        "history" => &cfg.history_sql_path,
        "current" => &cfg.current_values_sql_path,
        _ => &cfg.catalog_sql_path,
    };
    let sql = load_sql_file(path);
    if !is_connector_sql_safe(&sql) {
        return json!({"ok": false, "error": "unsafe SQL", "validation": validate_connector_sql(&sql)});
    }
    let bound = bind_template(
        &sql,
        &[
            (
                "start_ts",
                params
                    .get("start_ts")
                    .and_then(|v| v.as_str())
                    .unwrap_or("'2024-01-01T00:00:00Z'"),
            ),
            (
                "end_ts",
                params
                    .get("end_ts")
                    .and_then(|v| v.as_str())
                    .unwrap_or("'2024-01-02T00:00:00Z'"),
            ),
            ("limit", &cfg.row_limit.to_string()),
            (
                "site_id",
                params
                    .get("site_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("'site:demo'"),
            ),
        ],
    );
    json!({
        "ok": true,
        "source_id": source_id,
        "template": template_kind,
        "sql_preview": redact_sql_preview(&bound),
        "row_limit": cfg.row_limit,
        "timeout_s": cfg.query_timeout_s,
        "connection": redact_connection_string(
            &resolve_secret(&cfg.connection_secret_ref).unwrap_or_default()
        )
    })
}

pub fn poll_demo_values(source_id: &str, run_id: &str) -> Value {
    use crate::connectors::historian;
    use crate::connectors::registry::{update_source_health, update_source_poll_time};
    use crate::connectors::types::{NormalizedRow, SourceHealth};
    use chrono::{Local, Utc};

    let Ok(raw) = load_source_config(source_id) else {
        return json!({"ok": false, "error": "config load failed"});
    };
    let Ok(cfg) = parse_config(&raw) else {
        return json!({"ok": false, "error": "invalid config"});
    };
    if !demo_mode(&cfg) {
        return json!({"ok": false, "error": "live postgres poll requires local DSN and libpq runtime"});
    }
    let now = Utc::now();
    let rows = demo_catalog_points()
        .into_iter()
        .filter_map(|p| {
            let val = p.get("demo_value")?.as_f64()?;
            Some(NormalizedRow {
                timestamp_utc: now.to_rfc3339(),
                timestamp_local: now
                    .with_timezone(&Local)
                    .format("%Y-%m-%d %H:%M:%S")
                    .to_string(),
                timezone: "UTC".into(),
                site_id: cfg.site_id.clone(),
                building_id: cfg.building_id.clone(),
                equipment_id: p.get("equipment_id")?.as_str()?.into(),
                source_id: source_id.into(),
                source_type: "postgres_readonly".into(),
                source_protocol: "postgres".into(),
                device_id: "postgres:demo".into(),
                point_id: p.get("point_id")?.as_str()?.into(),
                point_name: p.get("point_name")?.as_str()?.into(),
                value: Some(val),
                value_text: val.to_string(),
                units: p.get("units")?.as_str()?.into(),
                quality: "good".into(),
                source_path: cfg.catalog_sql_path.clone(),
                raw_ref: "demo_catalog".into(),
                ingested_at: now.to_rfc3339(),
                run_id: run_id.into(),
            })
        })
        .collect::<Vec<_>>();
    let (written, skipped) = historian::append_rows(&rows).unwrap_or((0, 0));
    let count = historian::row_count_for_source(source_id);
    let _ = update_source_health(
        source_id,
        SourceHealth {
            status: "online".into(),
            message: "demo postgres catalog poll".into(),
            last_error: None,
        },
        Some(count),
    );
    let _ = update_source_poll_time(source_id);
    json!({"ok": true, "source_id": source_id, "rows_written": written, "rows_deduped": skipped, "run_id": run_id})
}

fn demo_mode(cfg: &PostgresConfig) -> bool {
    if env::var("OPENFDD_CONNECTOR_DEMO_MODE")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(true)
    {
        return resolve_secret(&cfg.connection_secret_ref).is_none();
    }
    resolve_secret(&cfg.connection_secret_ref).is_none()
}

fn load_sql_file(rel: &str) -> String {
    let local = PathBuf::from("workspace/connectors/local/sql").join(
        PathBuf::from(rel)
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("query.sql"),
    );
    if local.exists() {
        return fs::read_to_string(local).unwrap_or_default();
    }
    fs::read_to_string(rel).unwrap_or_else(|_| {
        fs::read_to_string(format!(
            "examples/connectors/sql/{}",
            PathBuf::from(rel)
                .file_name()
                .and_then(|s| s.to_str())
                .unwrap_or("point_catalog.example.sql")
        ))
        .unwrap_or_default()
    })
}

fn demo_catalog_points() -> Vec<Value> {
    vec![
        json!({"point_id":"point:supply_air_temp","point_name":"Supply Air Temp","units":"degF","equipment_id":"equip:demo-ahu","demo_value":55.5}),
        json!({"point_id":"point:return_air_temp","point_name":"Return Air Temp","units":"degF","equipment_id":"equip:demo-ahu","demo_value":72.0}),
    ]
}

fn redact_sql_preview(sql: &str) -> String {
    if sql.len() > 240 {
        format!("{}…", &sql[..240])
    } else {
        sql.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocks_ddl_in_postgres_template() {
        assert!(!is_connector_sql_safe("DROP TABLE point_catalog"));
    }
}
