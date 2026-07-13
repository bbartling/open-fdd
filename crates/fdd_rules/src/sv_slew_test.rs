#[cfg(test)]
mod tests {
    //! SV-SLEW: time-normalized zone rate faults; transient widen when fan starts.

    use std::collections::{HashMap, HashSet};
    use std::io::Write;
    use std::path::Path;

    use fdd_sql::{register_parquet_tree, run_sql};
    use fdd_store::ingest_building;

    use crate::params::{rule_params, substitute_sql};
    use crate::registry::RuleParameterDef;
    use crate::registry::RuleSpec;
    use crate::runner::project_optional_roles;
    use crate::tuning::assert_sql_placeholders;

    fn base_params() -> HashMap<String, String> {
        let mut p = rule_params(300.0, 300); // CONFIRM_ROWS = 1
        p.insert("SLEW_SCALE".into(), "1".into());
        p.insert("MAX_GAP_FACTOR".into(), "3".into());
        p.insert("FAN_TRANSIENT_MINUTES".into(), "20".into());
        p.insert("ZONE_T_STEADY_FAULT".into(), "6".into());
        p.insert("ZONE_T_TRANSIENT_FAULT".into(), "8".into());
        p.insert("ZONE_EXTREME_JUMP".into(), "15".into());
        p.insert("ZONE_EXTREME_MINUTES".into(), "5".into());
        p.insert("OA_T_STEADY_FAULT".into(), "12".into());
        p.insert("OA_T_TRANSIENT_FAULT".into(), "20".into());
        p.insert("RAT_STEADY_FAULT".into(), "6".into());
        p.insert("RAT_TRANSIENT_FAULT".into(), "12".into());
        p.insert("MAT_STEADY_FAULT".into(), "12".into());
        p.insert("MAT_TRANSIENT_FAULT".into(), "30".into());
        p.insert("SAT_STEADY_FAULT".into(), "10".into());
        p.insert("SAT_TRANSIENT_FAULT".into(), "35".into());
        p.insert("CHW_SUPPLY_STEADY_FAULT".into(), "6".into());
        p.insert("CHW_SUPPLY_TRANSIENT_FAULT".into(), "15".into());
        p.insert("CHW_RETURN_STEADY_FAULT".into(), "8".into());
        p.insert("CHW_RETURN_TRANSIENT_FAULT".into(), "15".into());
        p.insert("HW_SUPPLY_STEADY_FAULT".into(), "15".into());
        p.insert("HW_SUPPLY_TRANSIENT_FAULT".into(), "50".into());
        p.insert("HW_RETURN_STEADY_FAULT".into(), "12".into());
        p.insert("HW_RETURN_TRANSIENT_FAULT".into(), "30".into());
        p.insert("OA_H_STEADY_FAULT".into(), "25".into());
        p.insert("OA_H_TRANSIENT_FAULT".into(), "40".into());
        p.insert("DUCT_STATIC_STEADY_FAULT".into(), "0.75".into());
        p.insert("DUCT_STATIC_TRANSIENT_FAULT".into(), "3".into());
        p
    }

    fn rule_spec() -> RuleSpec {
        let mut parameters = HashMap::new();
        for (key, placeholder, default) in [
            ("slew_scale", "SLEW_SCALE", 1.0),
            ("max_gap_factor", "MAX_GAP_FACTOR", 3.0),
            ("fan_transient_minutes", "FAN_TRANSIENT_MINUTES", 20.0),
            ("zone_t_steady_fault", "ZONE_T_STEADY_FAULT", 6.0),
            ("zone_t_transient_fault", "ZONE_T_TRANSIENT_FAULT", 8.0),
            ("zone_extreme_jump", "ZONE_EXTREME_JUMP", 15.0),
            ("zone_extreme_minutes", "ZONE_EXTREME_MINUTES", 5.0),
            ("oa_t_steady_fault", "OA_T_STEADY_FAULT", 12.0),
            ("oa_t_transient_fault", "OA_T_TRANSIENT_FAULT", 20.0),
            ("rat_steady_fault", "RAT_STEADY_FAULT", 6.0),
            ("rat_transient_fault", "RAT_TRANSIENT_FAULT", 12.0),
            ("mat_steady_fault", "MAT_STEADY_FAULT", 12.0),
            ("mat_transient_fault", "MAT_TRANSIENT_FAULT", 30.0),
            ("sat_steady_fault", "SAT_STEADY_FAULT", 10.0),
            ("sat_transient_fault", "SAT_TRANSIENT_FAULT", 35.0),
            ("chw_supply_steady_fault", "CHW_SUPPLY_STEADY_FAULT", 6.0),
            (
                "chw_supply_transient_fault",
                "CHW_SUPPLY_TRANSIENT_FAULT",
                15.0,
            ),
            ("chw_return_steady_fault", "CHW_RETURN_STEADY_FAULT", 8.0),
            (
                "chw_return_transient_fault",
                "CHW_RETURN_TRANSIENT_FAULT",
                15.0,
            ),
            ("hw_supply_steady_fault", "HW_SUPPLY_STEADY_FAULT", 15.0),
            (
                "hw_supply_transient_fault",
                "HW_SUPPLY_TRANSIENT_FAULT",
                50.0,
            ),
            ("hw_return_steady_fault", "HW_RETURN_STEADY_FAULT", 12.0),
            (
                "hw_return_transient_fault",
                "HW_RETURN_TRANSIENT_FAULT",
                30.0,
            ),
            ("oa_h_steady_fault", "OA_H_STEADY_FAULT", 25.0),
            ("oa_h_transient_fault", "OA_H_TRANSIENT_FAULT", 40.0),
            ("duct_static_steady_fault", "DUCT_STATIC_STEADY_FAULT", 0.75),
            (
                "duct_static_transient_fault",
                "DUCT_STATIC_TRANSIENT_FAULT",
                3.0,
            ),
            ("confirm_seconds", "CONFIRM_SECONDS", 600.0),
        ] {
            parameters.insert(
                key.into(),
                RuleParameterDef {
                    label: key.into(),
                    default,
                    min: 0.0,
                    max: 1000.0,
                    step: 0.1,
                    unit: "".into(),
                    frontend_control: "slider".into(),
                    sql_placeholder: placeholder.into(),
                },
            );
        }
        RuleSpec {
            rule_id: "SV-SLEW".into(),
            sql_file: "sv_slew.sql".into(),
            description: "t".into(),
            required_roles: vec![],
            optional_roles: vec![
                "oa_t".into(),
                "rat".into(),
                "mat".into(),
                "sat".into(),
                "zone_t".into(),
                "chw_supply_t".into(),
                "chw_return_t".into(),
                "hw_supply_t".into(),
                "hw_return_t".into(),
                "oa_h".into(),
                "duct_static".into(),
                "fan_status".into(),
            ],
            equipment_types: vec![],
            output_columns: vec![],
            confirm_seconds: 300,
            parameters,
            parity_status: String::new(),
            dashboard_wired: false,
            operational_gate: None,
        }
    }

    async fn run_case(building: &str, write: impl FnOnce(&Path)) -> f64 {
        let tmp = tempfile::TempDir::new().unwrap();
        let data_root = tmp.path().join("data");
        let building_root = data_root.join(building);
        std::fs::create_dir_all(&building_root).unwrap();
        write(&building_root);

        let parquet_root = tmp.path().join("parquet");
        ingest_building(&data_root, building, &parquet_root).unwrap();

        let ctx = datafusion::prelude::SessionContext::new();
        register_parquet_tree(&ctx, &parquet_root).await.unwrap();

        let sql_path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("sql_rules/sv_slew.sql");
        let raw = std::fs::read_to_string(&sql_path).unwrap();
        let rule = rule_spec();
        assert_sql_placeholders(&raw, &rule).unwrap();

        let mut available = HashSet::new();
        available.insert("zone_t".into());
        available.insert("fan_status".into());
        available.insert("equipment_id".into());
        available.insert("timestamp_utc".into());

        let sql = substitute_sql(
            &project_optional_roles(&raw, &rule, &available),
            &base_params(),
        );
        let result = run_sql(&ctx, &sql).await.unwrap();
        result.rows[0]
            .get("fault_hours")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0)
    }

    #[tokio::test]
    async fn zone_fast_slew_while_fan_off_is_fault() {
        // ~24 °F/h steady (2 °F / 5 min) while fan off → above 6 °F/h steady fault.
        let hours = run_case("VAV_SLEW_OFF", |root| {
            std::fs::write(root.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
            let eq = root.join("ZONE_1");
            std::fs::create_dir_all(&eq).unwrap();
            std::fs::write(
                eq.join("columns.csv"),
                "col,point_role\nzn,zone_t\nfan,fan_status\n",
            )
            .unwrap();
            let mut f = std::fs::File::create(eq.join("history_wide.csv")).unwrap();
            writeln!(f, "timestamp_utc,zn,fan").unwrap();
            for i in 0..24 {
                let minute = (i * 5) % 60;
                let hour = (i * 5) / 60;
                let t = 70.0 + (i as f64) * 2.0;
                writeln!(f, "2026-01-01T{hour:02}:{minute:02}:00Z,{t},0").unwrap();
            }
        })
        .await;
        assert!(
            hours > 0.0,
            "expected FAULT hours for ~24°F/h zone slew with fan off; got {hours}"
        );
    }

    #[tokio::test]
    async fn zone_slew_during_fan_start_uses_transient_limit() {
        // ~7.2 °F/h (0.6 °F / 5 min): above steady 6, below transient 8.
        // Keep samples within the 20-minute fan-start window.
        let hours = run_case("VAV_SLEW_START", |root| {
            std::fs::write(root.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
            let eq = root.join("ZONE_1");
            std::fs::create_dir_all(&eq).unwrap();
            std::fs::write(
                eq.join("columns.csv"),
                "col,point_role\nzn,zone_t\nfan,fan_status\n",
            )
            .unwrap();
            let mut f = std::fs::File::create(eq.join("history_wide.csv")).unwrap();
            writeln!(f, "timestamp_utc,zn,fan").unwrap();
            writeln!(f, "2026-01-01T00:00:00Z,70.0,0").unwrap();
            for i in 1..=4 {
                let minute = i * 5;
                let t = 70.0 + (i as f64) * 0.6;
                writeln!(f, "2026-01-01T00:{minute:02}:00Z,{t},1").unwrap();
            }
        })
        .await;
        assert!(
            hours < 1e-6,
            "7.2°F/h during fan-start transient should not fault at 8°F/h transient limit; got {hours}"
        );
    }

    #[tokio::test]
    async fn zone_extreme_jump_in_five_minutes_faults() {
        let hours = run_case("VAV_SLEW_EXTREME", |root| {
            std::fs::write(root.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
            let eq = root.join("ZONE_1");
            std::fs::create_dir_all(&eq).unwrap();
            std::fs::write(
                eq.join("columns.csv"),
                "col,point_role\nzn,zone_t\nfan,fan_status\n",
            )
            .unwrap();
            let mut f = std::fs::File::create(eq.join("history_wide.csv")).unwrap();
            writeln!(f, "timestamp_utc,zn,fan").unwrap();
            writeln!(f, "2026-01-01T00:00:00Z,70.0,0").unwrap();
            writeln!(f, "2026-01-01T00:05:00Z,90.0,0").unwrap();
            writeln!(f, "2026-01-01T00:10:00Z,90.0,0").unwrap();
        })
        .await;
        assert!(
            hours > 0.0,
            "extreme +20°F in 5 minutes must fault; got {hours}"
        );
    }
}
