//! Analytics rollups (distinct from FDD rule statuses).
//!
//! Phase 1 overlap with Vibe19 Overview analytics: motor runtime hours.

use std::collections::HashSet;
use std::path::Path;

use anyhow::Result;
use datafusion::prelude::SessionContext;
use fdd_sql::{register_parquet_tree, run_sql};
use serde::Serialize;
use serde_json::{json, Value};

use crate::params::read_poll_from_cache;

const MOTOR_ROLES: &[&str] = &[
    "fan_cmd",
    "fan_status",
    "chw_pump_status",
    "chw_pump_cmd",
    "hw_pump_cmd",
    "pump_cmd",
    "pump_status",
];

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct MotorHoursRow {
    pub equipment_id: String,
    pub motor_kind: String,
    pub on_samples: u64,
    pub run_hours: f64,
    pub samples: u64,
    pub signal: String,
}

fn norm_on_expr(col: &str) -> String {
    // Match Vibe19 `_is_on` numeric path: scale values >1.5 by /100, threshold 0.05.
    if col.contains("status") {
        format!(
            "(CASE WHEN {col} IS NULL THEN 0 \
             WHEN TRIM(CAST({col} AS VARCHAR)) IN ('1','1.0','true','TRUE','on','ON') THEN 1 \
             ELSE 0 END)"
        )
    } else {
        format!(
            "(CASE WHEN {col} IS NULL THEN 0 \
             WHEN {col} > 1.5 THEN CASE WHEN {col} / 100.0 > 0.05 THEN 1 ELSE 0 END \
             WHEN {col} > 0.05 THEN 1 ELSE 0 END)"
        )
    }
}

fn motor_kind(role: &str) -> &'static str {
    if role.contains("fan") {
        "fan"
    } else {
        "pump"
    }
}

/// Compute motor runtime hours for every present motor-like role in `history`.
pub async fn compute_motor_hours(parquet_root: &Path) -> Result<Vec<MotorHoursRow>> {
    let poll = read_poll_from_cache(parquet_root).unwrap_or(300.0);
    let ctx = SessionContext::new();
    register_parquet_tree(&ctx, parquet_root).await?;
    let cols = {
        let df = ctx.sql("SELECT * FROM history LIMIT 0").await?;
        df.schema()
            .fields()
            .iter()
            .map(|f| f.name().clone())
            .collect::<HashSet<_>>()
    };

    let mut out = Vec::new();
    for role in MOTOR_ROLES {
        if !cols.contains(*role) {
            continue;
        }
        let on = norm_on_expr(role);
        let sql = format!(
            "SELECT equipment_id, \
                    SUM(CASE WHEN {on} > 0 THEN 1 ELSE 0 END) AS on_samples, \
                    COUNT(*) AS samples \
             FROM history \
             WHERE {role} IS NOT NULL \
             GROUP BY equipment_id \
             HAVING SUM(CASE WHEN {role} IS NOT NULL THEN 1 ELSE 0 END) > 0 \
             ORDER BY equipment_id"
        );
        let result = run_sql(&ctx, &sql).await?;
        for row in result.rows {
            let Some(eq) = row.get("equipment_id").and_then(|v| v.as_str()) else {
                continue;
            };
            let on_samples = row
                .get("on_samples")
                .and_then(|v| v.as_u64().or_else(|| v.as_f64().map(|f| f as u64)))
                .unwrap_or(0);
            let samples = row
                .get("samples")
                .and_then(|v| v.as_u64().or_else(|| v.as_f64().map(|f| f as u64)))
                .unwrap_or(0);
            if samples == 0 {
                continue;
            }
            let run_hours = (on_samples as f64) * poll / 3600.0;
            out.push(MotorHoursRow {
                equipment_id: eq.to_string(),
                motor_kind: motor_kind(role).to_string(),
                on_samples,
                run_hours: (run_hours * 1_000_000.0).round() / 1_000_000.0,
                samples,
                signal: (*role).to_string(),
            });
        }
    }
    out.sort_by(|a, b| {
        (&a.motor_kind, &a.equipment_id, &a.signal).cmp(&(
            &b.motor_kind,
            &b.equipment_id,
            &b.signal,
        ))
    });
    Ok(out)
}

pub fn motor_hours_to_json(rows: &[MotorHoursRow]) -> Value {
    json!({
        "ok": true,
        "analytics": "motor_hours",
        "units": { "run_hours": "h", "on_samples": "count", "samples": "count" },
        "row_count": rows.len(),
        "rows": rows,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use fdd_store::ingest_building;
    use std::path::PathBuf;

    #[tokio::test]
    async fn motor_hours_matches_vibe19_small_golden() {
        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/analytics_golden_building");
        if !fixture.join("ANALYTICS_GOLDEN_B1/manifest.json").is_file() {
            eprintln!("skip: analytics_golden_building fixture missing");
            return;
        }
        let tmp = tempfile::TempDir::new().unwrap();
        let parquet = tmp.path().join("parquet");
        ingest_building(&fixture, "ANALYTICS_GOLDEN_B1", &parquet).unwrap();

        let rows = compute_motor_hours(&parquet).await.unwrap();
        assert!(!rows.is_empty(), "expected motor hour rows");

        let golden_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/vibe19_analytics_golden/motor_hours.csv");
        let mut rdr = csv::Reader::from_path(&golden_path).unwrap();
        let mut expected = Vec::new();
        for rec in rdr.records() {
            let r = rec.unwrap();
            expected.push(MotorHoursRow {
                equipment_id: r[0].to_string(),
                motor_kind: r[1].to_string(),
                on_samples: r[2].parse::<f64>().unwrap() as u64,
                run_hours: r[3].parse::<f64>().unwrap(),
                samples: r[4].parse::<f64>().unwrap() as u64,
                signal: r[5].to_string(),
            });
        }
        expected.sort_by(|a, b| {
            (&a.motor_kind, &a.equipment_id, &a.signal).cmp(&(
                &b.motor_kind,
                &b.equipment_id,
                &b.signal,
            ))
        });

        assert_eq!(
            rows.len(),
            expected.len(),
            "row count mismatch\n got: {rows:?}\n exp: {expected:?}"
        );
        for (g, e) in rows.iter().zip(expected.iter()) {
            assert_eq!(g.equipment_id, e.equipment_id);
            assert_eq!(g.signal, e.signal);
            assert_eq!(g.motor_kind, e.motor_kind);
            assert_eq!(
                g.on_samples, e.on_samples,
                "{} {}",
                g.equipment_id, g.signal
            );
            assert_eq!(g.samples, e.samples);
            assert!(
                (g.run_hours - e.run_hours).abs() < 0.01,
                "{} {} hours {} vs {}",
                g.equipment_id,
                g.signal,
                g.run_hours,
                e.run_hours
            );
        }
    }
}
