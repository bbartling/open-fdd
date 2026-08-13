//! Shared helpers for SQL ↔ pandas-equivalent oracle fixtures (#550 phase 1).

use std::collections::HashMap;
use std::io::Write;
use std::path::{Path, PathBuf};

use anyhow::Result;
use datafusion::prelude::SessionContext;
use fdd_sql::{register_parquet_tree, run_sql};
use fdd_store::ingest_building;

use crate::params::{rule_params, substitute_sql};

pub struct RoleCol {
    pub csv_col: &'static str,
    pub role: &'static str,
}

/// Minimal building layout: one equipment folder with `columns.csv` + `history_wide.csv`.
pub fn write_equipment_fixture(
    building_root: &Path,
    equipment_id: &str,
    grid_minutes: u32,
    roles: &[RoleCol],
    header_and_rows: &str,
) {
    std::fs::write(
        building_root.join("manifest.json"),
        format!(r#"{{"grid_minutes": {grid_minutes}}}"#),
    )
    .unwrap();
    let eq = building_root.join(equipment_id);
    std::fs::create_dir_all(&eq).unwrap();
    let mut cols = String::from("col,point_role\n");
    for r in roles {
        cols.push_str(&format!("{},{}\n", r.csv_col, r.role));
    }
    std::fs::write(eq.join("columns.csv"), cols).unwrap();
    let mut f = std::fs::File::create(eq.join("history_wide.csv")).unwrap();
    write!(f, "{header_and_rows}").unwrap();
}

pub async fn run_rule_fault_hours(
    building_root: &Path,
    sql_file: &str,
    poll_seconds: f64,
    confirm_seconds: u32,
    extra_params: &[(&str, &str)],
) -> f64 {
    let tmp_parquet = building_root
        .parent()
        .unwrap()
        .join(format!("parquet-{}", sql_file.replace('.', "-")));
    let _ = std::fs::remove_dir_all(&tmp_parquet);
    let data_root = building_root.parent().unwrap();
    let building_id = building_root
        .file_name()
        .unwrap()
        .to_string_lossy()
        .into_owned();
    ingest_building(data_root, &building_id, &tmp_parquet).unwrap();

    let ctx = SessionContext::new();
    register_parquet_tree(&ctx, &tmp_parquet).await.unwrap();

    let sql_path = repo_sql_rules().join(sql_file);
    let raw_sql = std::fs::read_to_string(&sql_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", sql_path.display()));
    let mut params = rule_params(poll_seconds, confirm_seconds);
    for (k, v) in extra_params {
        params.insert((*k).into(), (*v).into());
    }
    let sql = substitute_sql(&raw_sql, &params);
    // Match runner: inject NULL optional fan proof columns when fixtures omit them.
    let sql = inject_optional_fan_cols(&ctx, sql_file, &sql)
        .await
        .unwrap();
    let result = run_sql(&ctx, &sql).await.unwrap();
    if result.row_count == 0 {
        return 0.0;
    }
    result.rows[0]
        .get("fault_hours")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0)
}

/// Pandas `confirm_fault` equivalent: confirm after `confirm_rows` consecutive true samples
/// in a streak (group on raw != raw.shift()).
pub fn pandas_confirm_fault_hours(raw: &[bool], poll_seconds: f64, confirm_rows: usize) -> f64 {
    let mut confirmed = 0usize;
    let mut streak = 0usize;
    let mut prev: Option<bool> = None;
    for &r in raw {
        if prev != Some(r) {
            streak = 0;
        }
        if r {
            streak += 1;
            if streak >= confirm_rows {
                confirmed += 1;
            }
        } else {
            streak = 0;
        }
        prev = Some(r);
    }
    confirmed as f64 * poll_seconds / 3600.0
}

pub fn assert_hours_close(got: f64, expected: f64, label: &str) {
    assert!(
        (got - expected).abs() < 1e-6,
        "{label}: expected {expected}h, got {got}h"
    );
}

async fn inject_optional_fan_cols(
    ctx: &SessionContext,
    _sql_file: &str,
    sql: &str,
) -> Result<String> {
    let df = ctx.table("history").await?;
    let have: std::collections::HashSet<String> = df
        .schema()
        .fields()
        .iter()
        .map(|f| f.name().to_ascii_lowercase())
        .collect();
    let needed = [
        "fan_cmd",
        "fan_status",
        "pump_status",
        "chiller_status",
        "chw_flow",
        "chw_pump_cmd",
        "chw_pump_status",
        "compressor_status",
        "building_zone_load_satisfied",
        "vav_total_flow",
        "occ_mode",
        "hw_reset_request_sum",
        "chw_reset_request_sum",
        // Portable SV / PID / coil / TRIM optional channels
        "oa_t",
        "mat",
        "zone_t",
        "rat",
        "sat",
        "oa_damper_pct",
        "clg_valve_pct",
        "htg_valve_pct",
        "damper_pct",
        "loop_enabled",
        "cooling_coil_entering_temp",
        "cooling_coil_leaving_temp",
        "heating_coil_entering_temp",
        "heating_coil_leaving_temp",
        "duct_static",
        "duct_static_sp",
        "static_reset_request",
        "web_oa_t",
    ];
    let missing: Vec<&str> = needed.into_iter().filter(|c| !have.contains(*c)).collect();
    if missing.is_empty() {
        return Ok(sql.to_string());
    }
    let nulls = missing
        .iter()
        .map(|c| {
            let ty = if *c == "occ_mode" {
                "VARCHAR"
            } else {
                "DOUBLE"
            };
            format!("CAST(NULL AS {ty}) AS \"{c}\"")
        })
        .collect::<Vec<_>>()
        .join(", ");
    let cte = format!("history_opt AS (SELECT history.*, {nulls} FROM history)");
    let rewritten = sql
        .replace(" FROM history", " FROM history_opt")
        .replace(" from history", " from history_opt")
        .replace("\nFROM history", "\nFROM history_opt")
        .replace("\nfrom history", "\nfrom history_opt");
    let rewritten = if let Some(idx) = rewritten.find("WITH ") {
        let (pre, rest) = rewritten.split_at(idx);
        let rest = rest.trim_start_matches("WITH ");
        format!("{pre}WITH {cte}, {rest}")
    } else if let Some(idx) = rewritten.find("with ") {
        let (pre, rest) = rewritten.split_at(idx);
        let rest = rest.trim_start_matches("with ");
        format!("{pre}WITH {cte}, {rest}")
    } else {
        format!("WITH {cte} {rewritten}")
    };
    Ok(rewritten)
}

fn repo_sql_rules() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("sql_rules")
}

/// Convenience: build params map for debugging.
#[allow(dead_code)]
pub fn merge_params(
    poll_seconds: f64,
    confirm_seconds: u32,
    extra: &[(&str, &str)],
) -> HashMap<String, String> {
    let mut m = rule_params(poll_seconds, confirm_seconds);
    for (k, v) in extra {
        m.insert((*k).into(), (*v).into());
    }
    m
}
