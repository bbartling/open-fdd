//! Shared helpers for SQL ↔ pandas-equivalent oracle fixtures (#550 phase 1).

use std::collections::HashMap;
use std::io::Write;
use std::path::{Path, PathBuf};

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

    let ctx = datafusion::prelude::SessionContext::new();
    register_parquet_tree(&ctx, &tmp_parquet).await.unwrap();

    let sql_path = repo_sql_rules().join(sql_file);
    let raw_sql = std::fs::read_to_string(&sql_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", sql_path.display()));
    let mut params = rule_params(poll_seconds, confirm_seconds);
    for (k, v) in extra_params {
        params.insert((*k).into(), (*v).into());
    }
    let sql = substitute_sql(&raw_sql, &params);
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
