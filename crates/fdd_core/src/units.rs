//! Running stacks store historian samples in metric-c-v2 (°C / Pa / L/s).
//! The processing ABI contract is metric-c-v2 — see `sql/contract/metric_units.json`
//! and `units_contract`. Ingest converts declared source units once (W2b).
//! Display preference is independent of processing.

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
    fn pressure_and_flow_round_trip() {
        assert!((pa_to_in_wc(248.84) - 1.0).abs() < 1e-9);
        assert!((lps_to_cfm(0.471947) - 1.0).abs() < 1e-6);
        assert!(is_pressure_role("duct_static"));
        assert!(is_flow_role("zone_flow"));
    }

    #[test]
    fn delta_f_to_delta_c_round_trip() {
        assert!((delta_f_to_delta_c(5.0) - 2.777777777777778).abs() < 1e-12);
    }

    #[test]
    fn metric_select_list_temperature_scales() {
        let sel = metric_select_list(&["timestamp".into(), "sat".into(), "duct_static".into()]);
        assert!(sel.contains("* 9.0 / 5.0"));
        assert!(sel.contains("AS \"sat\""));
        assert!(sel.contains("/ 248.84"));
    }
}
