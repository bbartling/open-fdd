//! Analytics rollups (distinct from FDD rule statuses).
//!
//! Phase 1 overlap with Vibe19 Overview analytics: motor runtime hours / weekly.

use std::collections::{HashMap, HashSet};
use std::path::Path;

use anyhow::Result;
use datafusion::prelude::SessionContext;
use fdd_sql::{register_parquet_tree, register_weather_if_present, run_sql};
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

/// Preference order for weekly plant motors (status before command).
const WEEKLY_MOTOR_PREF: &[&str] = &[
    "fan_status",
    "fan_cmd",
    "chw_pump_status",
    "chw_pump_cmd",
    "hw_pump_status",
    "pump_status",
    "cw_pump_status",
    "pump_cmd",
    "hw_pump_cmd",
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

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct MotorWeeklyRow {
    pub equipment_id: String,
    pub signal: String,
    pub motor_kind: String,
    pub plant_group: String,
    pub label: String,
    pub week_start: String,
    pub week_label: String,
    pub hours: f64,
    pub avg_oat_f: Option<f64>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct MechCoolingOatBinRow {
    pub equipment_id: String,
    pub source: String,
    pub source_kind: String,
    pub bin_start: i64,
    pub bin_label: String,
    pub hours: f64,
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

fn weekly_motor_kind(role: &str) -> &'static str {
    if role.contains("fan") {
        "fan"
    } else if role.starts_with("chw_pump") {
        "chiller"
    } else {
        "pump"
    }
}

fn weekly_signal_name(role: &str) -> &str {
    match role {
        "hw_pump_status" | "cw_pump_status" | "pump_status" => "pump_status",
        "hw_pump_cmd" | "cw_pump_cmd" | "pump_cmd" => "pump_cmd",
        other => other,
    }
}

fn plant_group_for(equipment_id: &str, motor_kind: &str) -> &'static str {
    let u = equipment_id.to_ascii_uppercase();
    if motor_kind == "fan" || u.contains("AHU") {
        "air"
    } else if u.contains("BOILER") {
        "boiler"
    } else {
        "chiller"
    }
}

fn is_vav_like(equipment_id: &str) -> bool {
    let u = equipment_id.to_ascii_uppercase();
    u.contains("VAV") || u.starts_with("ZONE")
}

/// Monday 00:00 UTC week start matching pandas `resample("W-MON", label="left")`.
fn week_start_monday_utc(ts: &str) -> Option<(String, String)> {
    let trimmed = ts.trim();
    let date = if let Some(t) = trimmed.split('T').next() {
        t
    } else {
        trimmed
    };
    let parts: Vec<_> = date.split('-').collect();
    if parts.len() != 3 {
        return None;
    }
    let y: i32 = parts[0].parse().ok()?;
    let m: u32 = parts[1].parse().ok()?;
    let d: u32 = parts[2].parse().ok()?;
    // Civil date → days since 1970-01-01 (Howard Hinnant).
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = (y - era * 400) as u32;
    let mp = if m > 2 { m - 3 } else { m + 9 };
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = (era * 146097 + doe as i32 - 719468) as i64;
    // 1970-01-01 was Thursday. Monday-on-or-before: days - ((days+3) % 7)
    let monday = days - ((days + 3).rem_euclid(7));
    // Convert monday days back to Y-M-D.
    let z = monday + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u32;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = (yoe as i32) + (era as i32) * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    let label = format!("{y:04}-{m:02}-{d:02}");
    Some((format!("{label}T00:00:00Z"), label))
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

/// Weekly on-hours per preferred plant motor (Vibe19 `motor_run_hours_weekly` overlap).
pub async fn compute_motor_weekly(parquet_root: &Path) -> Result<Vec<MotorWeeklyRow>> {
    let poll = read_poll_from_cache(parquet_root).unwrap_or(300.0);
    let ctx = SessionContext::new();
    register_parquet_tree(&ctx, parquet_root).await?;
    let has_weather = register_weather_if_present(&ctx, parquet_root).await?;
    let weather_has_oa = if has_weather {
        let df = ctx.sql("SELECT * FROM weather LIMIT 0").await?;
        df.schema().fields().iter().any(|f| f.name() == "oa_t")
    } else {
        false
    };
    let cols = {
        let df = ctx.sql("SELECT * FROM history LIMIT 0").await?;
        df.schema()
            .fields()
            .iter()
            .map(|f| f.name().clone())
            .collect::<HashSet<_>>()
    };
    let has_oa = cols.contains("oa_t");

    let eq_sql = "SELECT DISTINCT equipment_id FROM history ORDER BY equipment_id";
    let eq_result = run_sql(&ctx, eq_sql).await?;
    let equipment: Vec<String> = eq_result
        .rows
        .iter()
        .filter_map(|r| {
            r.get("equipment_id")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
        .filter(|e| !is_vav_like(e))
        .collect();

    let mut out = Vec::new();
    for eq in equipment {
        let mut chosen: Option<&str> = None;
        for role in WEEKLY_MOTOR_PREF {
            if !cols.contains(*role) {
                continue;
            }
            let check = format!(
                "SELECT COUNT(*) AS n FROM history \
                 WHERE equipment_id = '{eq}' AND {role} IS NOT NULL"
            );
            let res = run_sql(&ctx, &check).await?;
            let n = res
                .rows
                .first()
                .and_then(|r| r.get("n"))
                .and_then(|v| v.as_u64().or_else(|| v.as_f64().map(|f| f as u64)))
                .unwrap_or(0);
            if n > 0 {
                chosen = Some(*role);
                break;
            }
        }
        let Some(role) = chosen else {
            continue;
        };
        let on = norm_on_expr(&format!("h.{role}"));
        let join_weather = has_weather && weather_has_oa;
        let oat_expr = if join_weather && has_oa {
            "COALESCE(h.oa_t, w.oa_t)".to_string()
        } else if join_weather {
            "w.oa_t".to_string()
        } else if has_oa {
            "h.oa_t".to_string()
        } else {
            "CAST(NULL AS DOUBLE)".to_string()
        };
        let sql = if join_weather {
            format!(
                "SELECT CAST(h.timestamp_utc AS VARCHAR) AS ts, \
                        CASE WHEN {on} > 0 THEN 1 ELSE 0 END AS is_on, \
                        {oat_expr} AS oat \
                 FROM history h \
                 LEFT JOIN weather w ON h.timestamp_utc = w.timestamp_utc \
                 WHERE h.equipment_id = '{eq}' AND h.{role} IS NOT NULL"
            )
        } else {
            let on_h = norm_on_expr(role);
            format!(
                "SELECT CAST(timestamp_utc AS VARCHAR) AS ts, \
                        CASE WHEN {on_h} > 0 THEN 1 ELSE 0 END AS is_on, \
                        {oat_expr} AS oat \
                 FROM history \
                 WHERE equipment_id = '{eq}' AND {role} IS NOT NULL"
            )
        };
        let result = run_sql(&ctx, &sql).await?;
        #[derive(Default)]
        struct Acc {
            on_samples: u64,
            oat_sum: f64,
            oat_n: u64,
        }
        let mut by_week: HashMap<String, Acc> = HashMap::new();
        let mut labels: HashMap<String, String> = HashMap::new();
        for row in result.rows {
            let Some(ts) = row.get("ts").and_then(|v| v.as_str()) else {
                continue;
            };
            let is_on = row
                .get("is_on")
                .and_then(|v| v.as_u64().or_else(|| v.as_f64().map(|f| f as u64)))
                .unwrap_or(0)
                > 0;
            if !is_on {
                continue;
            }
            let Some((week_start, week_label)) = week_start_monday_utc(ts) else {
                continue;
            };
            labels.insert(week_start.clone(), week_label);
            let acc = by_week.entry(week_start).or_default();
            acc.on_samples += 1;
            if let Some(oat) = row.get("oat").and_then(|v| v.as_f64()) {
                acc.oat_sum += oat;
                acc.oat_n += 1;
            }
        }
        let signal = weekly_signal_name(role).to_string();
        let kind = weekly_motor_kind(role).to_string();
        let plant = plant_group_for(&eq, &kind).to_string();
        let label = format!("{eq} · {signal}");
        for (week_start, acc) in by_week {
            let hours = ((acc.on_samples as f64) * poll / 3600.0 * 100.0).round() / 100.0;
            if hours <= 0.0 {
                continue;
            }
            let avg_oat_f = if acc.oat_n > 0 {
                Some(((acc.oat_sum / acc.oat_n as f64) * 10.0).round() / 10.0)
            } else {
                None
            };
            let week_label = labels.get(&week_start).cloned().unwrap_or_default();
            out.push(MotorWeeklyRow {
                equipment_id: eq.clone(),
                signal: signal.clone(),
                motor_kind: kind.clone(),
                plant_group: plant.clone(),
                label: label.clone(),
                week_start,
                week_label,
                hours,
                avg_oat_f,
            });
        }
    }
    out.sort_by(|a, b| {
        (
            &a.plant_group,
            &a.week_start,
            &a.motor_kind,
            &a.equipment_id,
            &a.signal,
        )
            .cmp(&(
                &b.plant_group,
                &b.week_start,
                &b.motor_kind,
                &b.equipment_id,
                &b.signal,
            ))
    });
    Ok(out)
}

pub fn motor_weekly_to_json(rows: &[MotorWeeklyRow]) -> Value {
    json!({
        "ok": true,
        "analytics": "motor_weekly",
        "units": { "hours": "h", "avg_oat_f": "°F" },
        "row_count": rows.len(),
        "rows": rows,
    })
}

/// Mechanical cooling run hours binned by OAT (Vibe19 `mech_cooling_oat_bins` overlap).
pub async fn compute_mech_cooling_oat_bins(
    parquet_root: &Path,
) -> Result<Vec<MechCoolingOatBinRow>> {
    let poll = read_poll_from_cache(parquet_root).unwrap_or(300.0);
    let bin_width = 5.0_f64;
    let ctx = SessionContext::new();
    register_parquet_tree(&ctx, parquet_root).await?;
    let has_weather = register_weather_if_present(&ctx, parquet_root).await?;
    let weather_has_oa = if has_weather {
        let df = ctx.sql("SELECT * FROM weather LIMIT 0").await?;
        df.schema().fields().iter().any(|f| f.name() == "oa_t")
    } else {
        false
    };
    let cols = {
        let df = ctx.sql("SELECT * FROM history LIMIT 0").await?;
        df.schema()
            .fields()
            .iter()
            .map(|f| f.name().clone())
            .collect::<HashSet<_>>()
    };

    let pump_role = [
        "chw_pump_status",
        "chw_pump_cmd",
        "pump_status",
        "chiller_status",
    ]
    .into_iter()
    .find(|r| cols.contains(*r));
    let Some(role) = pump_role else {
        return Ok(Vec::new());
    };
    let source_kind = if role.starts_with("chw_pump") {
        "chw_pump"
    } else if role == "chiller_status" {
        "chiller_status"
    } else {
        "chw_pump"
    };
    let join_weather = has_weather && weather_has_oa;
    let on = norm_on_expr(&format!("h.{role}"));
    let oat_expr = if join_weather {
        "COALESCE(h.oa_t, w.oa_t)".to_string()
    } else if cols.contains("oa_t") {
        "h.oa_t".to_string()
    } else {
        return Ok(Vec::new());
    };
    let sql = if join_weather {
        format!(
            "SELECT h.equipment_id, {oat_expr} AS oat \
             FROM history h \
             LEFT JOIN weather w ON h.timestamp_utc = w.timestamp_utc \
             WHERE h.{role} IS NOT NULL AND {on} > 0 AND {oat_expr} IS NOT NULL"
        )
    } else {
        let on_h = norm_on_expr(role);
        format!(
            "SELECT h.equipment_id, {oat_expr} AS oat \
             FROM history h \
             WHERE h.{role} IS NOT NULL AND {on_h} > 0 AND {oat_expr} IS NOT NULL"
        )
    };
    let result = run_sql(&ctx, &sql).await?;
    let mut counts: HashMap<(String, i64), u64> = HashMap::new();
    for row in result.rows {
        let Some(eq) = row.get("equipment_id").and_then(|v| v.as_str()) else {
            continue;
        };
        let u = eq.to_ascii_uppercase();
        if !(u.contains("CHILLER") || u.starts_with("CHW")) {
            continue;
        }
        let Some(oat) = row.get("oat").and_then(|v| v.as_f64()) else {
            continue;
        };
        let clamped = oat.clamp(40.0, 110.0);
        let bin_start = ((clamped / bin_width).floor() * bin_width) as i64;
        *counts.entry((eq.to_string(), bin_start)).or_default() += 1;
    }
    let mut out = Vec::new();
    for ((eq, bin_start), n) in counts {
        let hours = ((n as f64) * poll / 3600.0 * 100.0).round() / 100.0;
        out.push(MechCoolingOatBinRow {
            source: format!("{eq} ({source_kind})"),
            source_kind: source_kind.to_string(),
            equipment_id: eq,
            bin_start,
            bin_label: format!("{bin_start}–{}", bin_start + bin_width as i64),
            hours,
        });
    }
    out.sort_by(|a, b| (a.bin_start, &a.source).cmp(&(b.bin_start, &b.source)));
    Ok(out)
}

pub fn mech_cooling_oat_bins_to_json(rows: &[MechCoolingOatBinRow]) -> Value {
    json!({
        "ok": true,
        "analytics": "mech_cooling_oat_bins",
        "units": { "hours": "h", "bin_start": "°F" },
        "row_count": rows.len(),
        "rows": rows,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use fdd_store::ingest_building;
    use std::path::PathBuf;

    fn golden_fixture() -> Option<(PathBuf, PathBuf)> {
        let fixture = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/analytics_golden_building");
        if !fixture.join("ANALYTICS_GOLDEN_B1/manifest.json").is_file() {
            return None;
        }
        let golden_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/vibe19_analytics_golden");
        Some((fixture, golden_root))
    }

    #[tokio::test]
    async fn motor_hours_matches_vibe19_small_golden() {
        let Some((fixture, golden_root)) = golden_fixture() else {
            eprintln!("skip: analytics_golden_building fixture missing");
            return;
        };
        let tmp = tempfile::TempDir::new().unwrap();
        let parquet = tmp.path().join("parquet");
        ingest_building(&fixture, "ANALYTICS_GOLDEN_B1", &parquet).unwrap();

        let rows = compute_motor_hours(&parquet).await.unwrap();
        assert!(!rows.is_empty(), "expected motor hour rows");

        let golden_path = golden_root.join("motor_hours.csv");
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

    #[tokio::test]
    async fn motor_weekly_matches_vibe19_small_golden() {
        let Some((fixture, golden_root)) = golden_fixture() else {
            eprintln!("skip: analytics_golden_building fixture missing");
            return;
        };
        let tmp = tempfile::TempDir::new().unwrap();
        let parquet = tmp.path().join("parquet");
        let report = ingest_building(&fixture, "ANALYTICS_GOLDEN_B1", &parquet).unwrap();
        assert!(
            report.weather_ingested,
            "weather must ingest for avg_oat_f parity"
        );

        let rows = compute_motor_weekly(&parquet).await.unwrap();
        assert!(!rows.is_empty(), "expected weekly rows");

        let mut rdr = csv::Reader::from_path(golden_root.join("motor_weekly.csv")).unwrap();
        let headers = rdr.headers().unwrap().clone();
        let idx = |name: &str| {
            headers
                .iter()
                .position(|h| h == name)
                .unwrap_or_else(|| panic!("missing {name}"))
        };
        let i_eq = idx("equipment_id");
        let i_sig = idx("signal");
        let i_kind = idx("motor_kind");
        let i_plant = idx("plant_group");
        let i_week = idx("week_label");
        let i_hours = idx("hours");
        let i_oat = idx("avg_oat_f");

        let mut expected = Vec::new();
        for rec in rdr.records() {
            let r = rec.unwrap();
            expected.push((
                r[i_eq].to_string(),
                r[i_sig].to_string(),
                r[i_kind].to_string(),
                r[i_plant].to_string(),
                r[i_week].to_string(),
                r[i_hours].parse::<f64>().unwrap(),
                r[i_oat].parse::<f64>().ok(),
            ));
        }
        expected
            .sort_by(|a, b| (&a.3, &a.4, &a.2, &a.0, &a.1).cmp(&(&b.3, &b.4, &b.2, &b.0, &b.1)));

        assert_eq!(
            rows.len(),
            expected.len(),
            "weekly row count mismatch got={} exp={}",
            rows.len(),
            expected.len()
        );
        for (g, e) in rows.iter().zip(expected.iter()) {
            assert_eq!(g.equipment_id, e.0);
            assert_eq!(g.signal, e.1);
            assert_eq!(g.motor_kind, e.2);
            assert_eq!(g.plant_group, e.3);
            assert_eq!(g.week_label, e.4);
            assert!(
                (g.hours - e.5).abs() < 0.05,
                "{} {} {} hours {} vs {}",
                g.equipment_id,
                g.signal,
                g.week_label,
                g.hours,
                e.5
            );
            match (g.avg_oat_f, e.6) {
                (Some(a), Some(b)) => assert!(
                    (a - b).abs() < 0.15,
                    "{} {} oat {} vs {}",
                    g.equipment_id,
                    g.week_label,
                    a,
                    b
                ),
                (None, None) => {}
                other => panic!("oat mismatch {other:?}"),
            }
        }
    }

    #[tokio::test]
    async fn mech_cooling_oat_bins_matches_vibe19_small_golden() {
        let Some((fixture, golden_root)) = golden_fixture() else {
            eprintln!("skip: analytics_golden_building fixture missing");
            return;
        };
        let tmp = tempfile::TempDir::new().unwrap();
        let parquet = tmp.path().join("parquet");
        ingest_building(&fixture, "ANALYTICS_GOLDEN_B1", &parquet).unwrap();
        let rows = compute_mech_cooling_oat_bins(&parquet).await.unwrap();
        let mut rdr =
            csv::Reader::from_path(golden_root.join("mech_cooling_oat_bins.csv")).unwrap();
        let mut expected = Vec::new();
        for rec in rdr.records() {
            let r = rec.unwrap();
            // bin_label,bin_start,equipment_id,hours,source,source_kind
            expected.push(MechCoolingOatBinRow {
                bin_label: r[0].to_string(),
                bin_start: r[1].parse::<f64>().unwrap() as i64,
                equipment_id: r[2].to_string(),
                hours: r[3].parse::<f64>().unwrap(),
                source: r[4].to_string(),
                source_kind: r[5].to_string(),
            });
        }
        expected.sort_by(|a, b| (a.bin_start, &a.source).cmp(&(b.bin_start, &b.source)));
        assert_eq!(
            rows.len(),
            expected.len(),
            "bin rows {rows:?} vs {expected:?}"
        );
        for (g, e) in rows.iter().zip(expected.iter()) {
            assert_eq!(g.equipment_id, e.equipment_id);
            assert_eq!(g.bin_start, e.bin_start);
            assert_eq!(g.source_kind, e.source_kind);
            assert!(
                (g.hours - e.hours).abs() < 0.05,
                "hours {} vs {}",
                g.hours,
                e.hours
            );
        }
    }
}
