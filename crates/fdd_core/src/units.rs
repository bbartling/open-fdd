//! Canonical FDD physics are imperial (°F). Metric/SI CSVs convert at query time.

/// Temperature cookbook roles stored as °C when `unit_system` is metric|si.
/// `dry_bulb_f` is already Fahrenheit even if the session is metric — never convert.
pub const TEMPERATURE_ROLES: &[&str] = &[
    "sat",
    "sat_sp",
    "mat",
    "rat",
    "oa_t",
    "web_oa_t",
    "web_oa_dp",
    "zone_t",
    "zn_t",
    "sa_t",
    "chw_supply_t",
    "chw_return_t",
    "cw_supply_t",
    "hw_supply_t",
    "hw_return_t",
    "preheat_leaving_t",
    "vav_dat",
    "vav_inlet_t",
    "ccet",
    "cclt",
    "hcet",
    "hclt",
];

pub fn is_metric_unit_system(unit_system: &str) -> bool {
    matches!(
        unit_system.trim().to_ascii_lowercase().as_str(),
        "metric" | "si"
    )
}

pub fn is_temperature_role(role: &str) -> bool {
    let r = role.trim().to_ascii_lowercase();
    if r == "dry_bulb_f" {
        return false;
    }
    TEMPERATURE_ROLES.iter().any(|t| *t == r)
}

pub fn celsius_to_fahrenheit(c: f64) -> f64 {
    c * 9.0 / 5.0 + 32.0
}

pub fn fahrenheit_to_celsius(f: f64) -> f64 {
    (f - 32.0) * 5.0 / 9.0
}

/// SQL expression: convert a history column from stored °C to °F, or pass through.
pub fn sql_temp_to_fahrenheit(column: &str, metric: bool) -> String {
    let ident = column.replace('"', "");
    if metric && is_temperature_role(&ident) {
        format!("((\"{ident}\" * 9.0 / 5.0) + 32.0)")
    } else {
        format!("\"{ident}\"")
    }
}

/// Wrap `FROM history` / `FROM weather` so metric CSVs run against °F SQL.
/// Callers must register `history_si` / `weather_si` views (converted SELECT)
/// on the DataFusion context; this helper only rewrites table names so nested
/// `WITH` queries do not shadow those views with CTEs in the wrong order.
pub fn sql_with_metric_to_imperial(
    sql: &str,
    _history_columns: &[String],
    weather_columns: &[String],
    unit_system: &str,
) -> String {
    if !is_metric_unit_system(unit_system) {
        return sql.to_string();
    }
    let mut rewritten = sql
        .replace(" FROM history", " FROM history_si")
        .replace(" from history", " FROM history_si")
        .replace("\nFROM history", "\nFROM history_si")
        .replace("\nfrom history", "\nFROM history_si");
    if !weather_columns.is_empty() {
        rewritten = rewritten
            .replace(" FROM weather", " FROM weather_si")
            .replace(" from weather", " FROM weather_si")
            .replace("\nFROM weather", "\nFROM weather_si")
            .replace("\nfrom weather", "\nFROM weather_si");
    }
    rewritten
}

pub fn metric_select_list(columns: &[String]) -> String {
    if columns.is_empty() {
        return "*".into();
    }
    columns
        .iter()
        .map(|c| {
            let ident = c.replace('"', "");
            if is_temperature_role(&ident) {
                format!("((\"{ident}\" * 9.0 / 5.0) + 32.0) AS \"{ident}\"")
            } else {
                format!("\"{ident}\"")
            }
        })
        .collect::<Vec<_>>()
        .join(", ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn c_to_f_water_and_body() {
        assert!((celsius_to_fahrenheit(0.0) - 32.0).abs() < 1e-9);
        assert!((celsius_to_fahrenheit(32.0) - 89.6).abs() < 1e-9);
        assert!((celsius_to_fahrenheit(100.0) - 212.0).abs() < 1e-9);
    }

    #[test]
    fn round_trip() {
        let f = 70.0;
        assert!((celsius_to_fahrenheit(fahrenheit_to_celsius(f)) - f).abs() < 1e-9);
    }

    #[test]
    fn dry_bulb_f_not_temperature_role() {
        assert!(!is_temperature_role("dry_bulb_f"));
        assert!(is_temperature_role("sat"));
        assert!(is_temperature_role("web_oa_t"));
    }

    #[test]
    fn metric_sql_wraps_history() {
        let sql = "SELECT sat FROM history WHERE sat > 55";
        let out = sql_with_metric_to_imperial(
            sql,
            &["timestamp".into(), "sat".into(), "fan_cmd".into()],
            &[],
            "metric",
        );
        assert!(out.contains("FROM history_si"));
        assert!(
            !sql_with_metric_to_imperial(sql, &["sat".into()], &[], "imperial")
                .contains("history_si")
        );
        let sel = metric_select_list(&["timestamp".into(), "sat".into(), "fan_cmd".into()]);
        assert!(sel.contains("* 9.0 / 5.0"));
        assert!(sel.contains("AS \"sat\""));
    }
}
