//! Registry-backed FDD API — Timescale path (Wave-X C2).
//! DataFusion Parquet registry runner deleted.

#[path = "registry_api_timescale.rs"]
mod imp;

pub use imp::*;

/// `GET /api/fdd/rules/{id}/params` with a quantity on every tuner parameter.
///
/// The timescale registry response stays the source of the numeric schema.
/// Quantity is attached here so that metadata can ship without editing the
/// shared registry response builder.
pub fn rule_params_with_quantity(rule_id: &str) -> serde_json::Value {
    let mut body = imp::rule_params_response(rule_id);
    let registry = imp::load_registry_rules_map();
    fdd_rules::annotate_rule_param_quantities(&mut body, registry.get(rule_id));
    fdd_rules::annotate_rule_param_effects(&mut body);
    body
}

#[cfg(test)]
mod quantity_tests {
    use super::rule_params_with_quantity;
    use serde_json::json;

    #[test]
    fn fc1_params_carry_distinct_quantities() {
        let body = rule_params_with_quantity("FC1");
        assert_eq!(body["ok"], json!(true), "{body}");
        assert_eq!(body["params"]["eps_dsp"]["quantity"], json!("pressure"));
        assert_eq!(body["params"]["eps_vfd_spd"]["quantity"], json!("fraction"));
        assert_eq!(
            body["params"]["mode_delay_min"]["quantity"],
            json!("minutes")
        );
        assert_eq!(body["params"]["confirm_min"]["quantity"], json!("minutes"));

        let fc2 = rule_params_with_quantity("FC2");
        assert_eq!(
            fc2["params"]["eps_mat"]["quantity"],
            json!("temperature_delta")
        );

        let vav = rule_params_with_quantity("VAV-1");
        assert_eq!(vav["params"]["zone_t_lo"]["quantity"], json!("temperature"));
    }
}
