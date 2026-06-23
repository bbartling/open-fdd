//! Read-only SQL template safety for connector queries.

use serde_json::{json, Value};

const BLOCKED: &[&str] = &[
    "DROP",
    "DELETE",
    "INSERT",
    "UPDATE",
    "ALTER",
    "CREATE",
    "COPY",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
    "CALL",
    "MERGE",
    "REPLACE",
    "VACUUM",
    "REINDEX",
    "SET ROLE",
    "SET SESSION",
];

pub fn validate_connector_sql(sql: &str) -> Value {
    let upper = normalize(sql);
    let mut errors = Vec::new();
    if !upper.starts_with("SELECT ") && !upper.contains(" SELECT ") {
        errors.push("Connector SQL must be a single SELECT query".into());
    }
    for kw in BLOCKED {
        if contains_kw(&upper, kw) {
            errors.push(format!("Blocked SQL keyword: {kw}"));
        }
    }
    if upper.contains(';') {
        errors.push("Multiple statements are not allowed".into());
    }
    json!({
        "ok": errors.is_empty(),
        "safe": errors.is_empty(),
        "errors": errors
    })
}

pub fn is_connector_sql_safe(sql: &str) -> bool {
    validate_connector_sql(sql)
        .get("safe")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

pub fn bind_template(sql: &str, params: &[(&str, &str)]) -> String {
    let mut pairs: Vec<_> = params.to_vec();
    pairs.sort_by(|a, b| b.0.len().cmp(&a.0.len()));
    let mut out = sql.to_string();
    for (k, v) in pairs {
        let colon_key = format!(":{}", k);
        out = out.replace(&colon_key, v);
        out = out.replace(&format!("${{{}}}", k), v);
    }
    out
}

fn normalize(sql: &str) -> String {
    sql.replace(['\n', '\r', '\t'], " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_uppercase()
}

fn contains_kw(upper: &str, kw: &str) -> bool {
    upper
        .split(' ')
        .any(|t| t == kw || t.starts_with(&format!("{kw}(")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocks_write_keywords() {
        assert!(!is_connector_sql_safe("UPDATE points SET value = 1"));
        assert!(!is_connector_sql_safe("DELETE FROM history"));
        assert!(!is_connector_sql_safe("DROP TABLE points"));
    }

    #[test]
    fn allows_select_with_params() {
        let sql = "SELECT ts, point_id, value FROM history WHERE ts >= :start_ts AND ts <= :end_ts LIMIT :limit";
        assert!(is_connector_sql_safe(sql));
    }

    #[test]
    fn binds_template_params() {
        let sql = "SELECT * FROM t WHERE ts >= :start_ts LIMIT :limit";
        let bound = bind_template(
            sql,
            &[("start_ts", "'2024-01-01T00:00:00Z'"), ("limit", "100")],
        );
        assert_eq!(
            bound,
            "SELECT * FROM t WHERE ts >= '2024-01-01T00:00:00Z' LIMIT 100"
        );
    }
}
