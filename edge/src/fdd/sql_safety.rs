//! SQL safety validator for DataFusion rule execution.
//!
//! Blocks DDL/DML and restricts queries to read-only SELECT against allowed views.

use serde_json::{json, Value};

const BLOCKED: &[&str] = &[
    "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "COPY", "ATTACH", "PRAGMA",
    "TRUNCATE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "CALL", "MERGE", "REPLACE",
];

const ALLOWED_TABLES: &[&str] = &["telemetry", "telemetry_pivot", "hvac"];

pub fn validate_sql(sql: &str) -> Value {
    let upper = normalize_for_scan(sql);
    let mut errors = Vec::new();
    let mut warnings = Vec::new();

    if !upper.contains("SELECT") {
        errors.push("SQL must be a SELECT query".to_string());
    }
    for kw in BLOCKED {
        if contains_keyword(&upper, kw) {
            errors.push(format!("Blocked SQL operation: {kw}"));
        }
    }
    if upper.contains(';') && upper.matches(';').count() > 1 {
        warnings
            .push("Multiple statements detected; only the first SELECT is executed".to_string());
    }
    let table_ok = ALLOWED_TABLES.iter().any(|t| {
        let tu = t.to_uppercase();
        upper.contains(&format!("FROM {tu}")) || upper.contains(&format!("JOIN {tu}"))
    });
    if !table_ok {
        errors.push(format!(
            "SQL must read from allowed tables/views: {}",
            ALLOWED_TABLES.join(", ")
        ));
    }
    if !upper.contains("FAULT_RAW") && !upper.contains(" AS FAULT_RAW") {
        warnings.push(
            "Missing fault_raw output alias; rules should expose fault_raw boolean".to_string(),
        );
    }
    json!({
        "ok": errors.is_empty(),
        "safe": errors.is_empty(),
        "errors": errors,
        "warnings": warnings,
        "allowed_tables": ALLOWED_TABLES,
    })
}

pub fn is_sql_safe(sql: &str) -> bool {
    validate_sql(sql)
        .get("safe")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

fn normalize_for_scan(sql: &str) -> String {
    sql.replace(['\n', '\r', '\t'], " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_uppercase()
}

fn contains_keyword(upper: &str, kw: &str) -> bool {
    upper
        .split(' ')
        .any(|token| token == kw || token.starts_with(&format!("{kw}(")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocks_drop_delete() {
        assert!(!is_sql_safe("DROP TABLE telemetry"));
        assert!(!is_sql_safe("DELETE FROM telemetry_pivot"));
        assert!(!is_sql_safe("INSERT INTO telemetry VALUES (1)"));
    }

    #[test]
    fn allows_select_from_telemetry_pivot() {
        let sql = "SELECT timestamp, equipment_id, oa_t, CASE WHEN oa_t > 100 THEN true ELSE false END AS fault_raw FROM telemetry_pivot WHERE equipment_id = 'AHU-1'";
        assert!(is_sql_safe(sql));
    }
}
