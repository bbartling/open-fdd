//! Active SQL pack ABI is imperial-f-v1 (°F / in.w.c. / cfm).
//! Target processing contract is metric-c-v2 (°C / Pa / L/s) — see
//! `sql/contract/metric_units.json`. Admit known source units into the pack ABI
//! before pivot/SQL. Display preference is independent of processing.

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

pub const PRESSURE_ROLES: &[&str] = &["duct_static", "duct_static_sp"];

/// Volumetric flow cookbook roles stored as L/s when `unit_system` is metric|si.
pub const FLOW_ROLES: &[&str] = &[
    "zone_flow",
    "zone_airflow_sp",
    "vav_total_flow",
    "min_flow_sp",
    "chw_flow",
];

/// Pascal per inch of water column (I-P static used by SQL placeholders).
pub const PA_PER_IN_WC: f64 = 248.84;
/// Litres per second per cubic foot per minute.
pub const LPS_PER_CFM: f64 = 0.471947;

pub fn is_pressure_role(role: &str) -> bool {
    let r = role.trim().to_ascii_lowercase();
    PRESSURE_ROLES.iter().any(|t| *t == r)
}

pub fn is_flow_role(role: &str) -> bool {
    let r = role.trim().to_ascii_lowercase();
    FLOW_ROLES.iter().any(|t| *t == r)
}

pub fn pa_to_in_wc(pa: f64) -> f64 {
    pa / PA_PER_IN_WC
}

pub fn lps_to_cfm(lps: f64) -> f64 {
    lps / LPS_PER_CFM
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

pub fn delta_c_to_delta_f(dc: f64) -> f64 {
    dc * 9.0 / 5.0
}

pub fn delta_f_to_delta_c(df: f64) -> f64 {
    df * 5.0 / 9.0
}

fn normalize_unit_token(unit: &str) -> String {
    unit.trim()
        .to_ascii_lowercase()
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect()
}

/// True when `unit` names Celsius (absolute).
pub fn unit_is_celsius(unit: &str) -> bool {
    matches!(
        normalize_unit_token(unit).as_str(),
        "c" | "degc" | "celsius"
    )
}

/// True when `unit` names Fahrenheit (absolute), or is empty (legacy assume F).
pub fn unit_is_fahrenheit_or_unset(unit: &str) -> bool {
    let t = normalize_unit_token(unit);
    t.is_empty() || matches!(t.as_str(), "f" | "degf" | "fahrenheit")
}

pub fn unit_is_pa(unit: &str) -> bool {
    matches!(normalize_unit_token(unit).as_str(), "pa" | "pascal")
}

pub fn unit_is_lps(unit: &str) -> bool {
    matches!(normalize_unit_token(unit).as_str(), "lps" | "ls" | "lpers")
}

/// Admit one sample into imperial-f-v1 pack units for a cookbook role.
pub fn admit_value_to_pack_v1(role: &str, value: f64, source_unit: &str) -> f64 {
    if is_temperature_role(role) {
        if unit_is_celsius(source_unit) {
            return celsius_to_fahrenheit(value);
        }
        return value;
    }
    if is_pressure_role(role) && unit_is_pa(source_unit) {
        return pa_to_in_wc(value);
    }
    if is_flow_role(role) && unit_is_lps(source_unit) {
        return lps_to_cfm(value);
    }
    value
}

/// SQL expression: convert `val` using the sample `unit` column into pack °F/in.w.c./cfm.
pub fn sql_admit_val_expr(role: &str) -> String {
    if is_temperature_role(role) {
        return "CASE WHEN lower(regexp_replace(coalesce(unit, ''), '[^a-zA-Z0-9]', '', 'g')) \
             IN ('c', 'degc', 'celsius') THEN (val * 9.0 / 5.0) + 32.0 ELSE val END"
            .to_string();
    }
    if is_pressure_role(role) {
        return format!(
            "CASE WHEN lower(regexp_replace(coalesce(unit, ''), '[^a-zA-Z0-9]', '', 'g')) \
             IN ('pa', 'pascal') THEN val / {PA_PER_IN_WC} ELSE val END"
        );
    }
    if is_flow_role(role) {
        return format!(
            "CASE WHEN lower(regexp_replace(coalesce(unit, ''), '[^a-zA-Z0-9]', '', 'g')) \
             IN ('lps', 'ls', 'lpers') THEN val / {LPS_PER_CFM} ELSE val END"
        );
    }
    "val".into()
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
            } else if is_pressure_role(&ident) {
                format!("(\"{ident}\" / {PA_PER_IN_WC}) AS \"{ident}\"")
            } else if is_flow_role(&ident) {
                format!("(\"{ident}\" / {LPS_PER_CFM}) AS \"{ident}\"")
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
        let sel = metric_select_list(&["timestamp".into(), "sat".into(), "duct_static".into()]);
        assert!(sel.contains("* 9.0 / 5.0"));
        assert!(sel.contains("AS \"sat\""));
        assert!(sel.contains("/ 248.84"));
    }

    #[test]
    fn pressure_and_flow_round_trip() {
        assert!((pa_to_in_wc(248.84) - 1.0).abs() < 1e-9);
        assert!((lps_to_cfm(0.471947) - 1.0).abs() < 1e-6);
        assert!(is_pressure_role("duct_static"));
        assert!(is_flow_role("zone_flow"));
    }

    #[test]
    fn admit_20c_equals_68f() {
        assert!((admit_value_to_pack_v1("sat", 20.0, "°C") - 68.0).abs() < 1e-9);
        assert!((admit_value_to_pack_v1("sat", 68.0, "°F") - 68.0).abs() < 1e-9);
        assert!((delta_f_to_delta_c(5.0) - 2.777777777777778).abs() < 1e-12);
    }

    #[test]
    fn sql_admit_temp_uses_unit_column() {
        let expr = sql_admit_val_expr("sat");
        assert!(expr.contains("celsius"));
        assert!(expr.contains("9.0 / 5.0"));
        assert_eq!(sql_admit_val_expr("fan_cmd"), "val");
    }
}
