//! Sensor health matrix — per-series coverage, flatline, missingness, stats.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sqlx::Row;
use std::collections::BTreeMap;

use super::{
    envelope, envelope_with_engine, finalize_historian, historian, resolve_query_version,
    AnalyticsEnvelope, AnalyticsQuery, AnalyticsRequest, QV_SENSOR_HEALTH,
};

/// Default minimum sample count before flatline flag can fire.
pub const DEFAULT_FLATLINE_MIN_N: usize = 5;
/// Std-dev below this (and n > min_n) → flatline.
pub const DEFAULT_FLATLINE_STD_EPS: f64 = 1e-9;

/// One sensor series sample for inline compute.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SensorPoint {
    pub equipment_id: String,
    pub role: String,
    pub timestamp: DateTime<Utc>,
    /// Null / missing values may be omitted or sent as JSON null (parsed as None).
    #[serde(default)]
    pub value: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SensorSeriesRow {
    pub equipment_id: String,
    pub role: String,
    pub n: u64,
    pub n_finite: u64,
    pub coverage_pct: f64,
    pub missingness: f64,
    pub flatline_flag: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub min: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mean: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub std: Option<f64>,
}

/// Compute per-(equipment_id, role) health stats from inline points.
pub fn compute_sensor_health(
    points: &[SensorPoint],
    flatline_min_n: usize,
    flatline_std_eps: f64,
) -> Vec<SensorSeriesRow> {
    let mut by_key: BTreeMap<(String, String), Vec<Option<f64>>> = BTreeMap::new();
    for p in points {
        by_key
            .entry((p.equipment_id.clone(), p.role.clone()))
            .or_default()
            .push(p.value.filter(|v| v.is_finite()));
    }

    let mut rows = Vec::with_capacity(by_key.len());
    for ((equipment_id, role), vals) in by_key {
        let n = vals.len() as u64;
        let finite: Vec<f64> = vals.into_iter().flatten().collect();
        let n_finite = finite.len() as u64;
        let coverage_pct = if n > 0 {
            100.0 * n_finite as f64 / n as f64
        } else {
            0.0
        };
        let missingness = if n > 0 {
            1.0 - (n_finite as f64 / n as f64)
        } else {
            0.0
        };

        let (min, max, mean, std) = if finite.is_empty() {
            (None, None, None, None)
        } else {
            let min_v = finite.iter().copied().fold(f64::INFINITY, f64::min);
            let max_v = finite.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            let mean_v = finite.iter().sum::<f64>() / finite.len() as f64;
            let var = if finite.len() > 1 {
                finite
                    .iter()
                    .map(|v| {
                        let d = v - mean_v;
                        d * d
                    })
                    .sum::<f64>()
                    / (finite.len() as f64)
            } else {
                0.0
            };
            let std_v = var.sqrt();
            (
                Some(round4(min_v)),
                Some(round4(max_v)),
                Some(round4(mean_v)),
                Some(round6(std_v)),
            )
        };

        let flatline_flag = n_finite as usize > flatline_min_n
            && std.map(|s| s <= flatline_std_eps).unwrap_or(false);

        rows.push(SensorSeriesRow {
            equipment_id,
            role,
            n,
            n_finite,
            coverage_pct: round2(coverage_pct),
            missingness: round4(missingness),
            flatline_flag,
            min,
            max,
            mean,
            std,
        });
    }
    rows
}

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_SENSOR_HEALTH);
    let mut env = envelope(&qv, &req.query, warnings.clone());

    let points = parse_points(req);
    match points {
        Some(pts) if !pts.is_empty() => {
            let mut filtered = pts;
            if let Some(ids) = &req.query.equipment_ids {
                if !ids.is_empty() {
                    filtered.retain(|p| ids.contains(&p.equipment_id));
                }
            }
            let rows =
                compute_sensor_health(&filtered, DEFAULT_FLATLINE_MIN_N, DEFAULT_FLATLINE_STD_EPS);
            env.rows = rows
                .iter()
                .map(|r| serde_json::to_value(r).unwrap_or(json!({})))
                .collect();
            env.equipment = env.rows.clone();
            env.coverage = Some(json!({
                "series_count": env.rows.len(),
                "point_count": filtered.len(),
            }));
            warnings.push(
                "sensor_health: minimal central-analytics-v1 stats (not full DF MemTable port)"
                    .into(),
            );
            env.warnings = warnings;
        }
        _ => {
            warnings.push(
                "no inline series points provided; historian/job sensor-health load is next".into(),
            );
            env.warnings = warnings;
        }
    }
    env
}

/// Async handler. Inline `series` stays a pure compute. A request without
/// series reads the Timescale `sample` table for the site and optional
/// equipment ids. A historian or database failure is returned to the caller.
/// It is not replaced with an empty successful envelope.
///
/// Defaults `query.start` to the last
/// [`historian::SENSOR_HEALTH_DEFAULT_LOOKBACK_DAYS`] when omitted so large
/// histories cannot hang unbounded. Explicit `query.start`/`query.end` are honored.
pub async fn handle_async(req: &AnalyticsRequest) -> Result<AnalyticsEnvelope> {
    if req.series.is_some() {
        return Ok(handle(req));
    }
    let defaulted_start = req.query.start.is_none();
    let start = req.query.start.or_else(|| {
        Some(Utc::now() - chrono::Duration::days(historian::SENSOR_HEALTH_DEFAULT_LOOKBACK_DAYS))
    });
    let end = req.query.end;
    let Some(mut env) = historian::sensor_health_from_history(
        req.query.equipment_ids.as_deref(),
        req.query.building_id.as_deref(),
        start,
        end,
    )
    .await?
    else {
        anyhow::bail!("sensor health historian returned no result");
    };
    if defaulted_start {
        env.warnings.insert(
            0,
            format!(
                "sensor_health defaulted start to last {} days; pass query.start for a custom window",
                historian::SENSOR_HEALTH_DEFAULT_LOOKBACK_DAYS
            ),
        );
    }
    Ok(finalize_historian(req, env, QV_SENSOR_HEALTH))
}

/// Coverage reason when the historian query succeeds and the window has no rows.
pub const NO_SAMPLES_IN_WINDOW: &str = "no_samples_in_window";

const SENSOR_HEALTH_SQL: &str = r#"
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  count(*)::bigint AS n,
  count(val) FILTER (
    WHERE val = val
      AND val > '-Infinity'::float8
      AND val < 'Infinity'::float8
  )::bigint AS n_finite,
  min(val) FILTER (
    WHERE val = val
      AND val > '-Infinity'::float8
      AND val < 'Infinity'::float8
  ) AS min_val,
  max(val) FILTER (
    WHERE val = val
      AND val > '-Infinity'::float8
      AND val < 'Infinity'::float8
  ) AS max_val,
  avg(val) FILTER (
    WHERE val = val
      AND val > '-Infinity'::float8
      AND val < 'Infinity'::float8
  ) AS mean_val,
  stddev_pop(val) FILTER (
    WHERE val = val
      AND val > '-Infinity'::float8
      AND val < 'Infinity'::float8
  ) AS std_val
FROM sample
WHERE site_id = $1
  AND ts >= $2
  AND ts < $3
  AND split_part(openfdd_key, '.', 2) <> ''
  AND (
    $4::text[] IS NULL
    OR cardinality($4) = 0
    OR split_part(openfdd_key, '.', 1) = ANY ($4)
  )
GROUP BY 1, 2
ORDER BY 1, 2
"#;

/// Aggregate current `sample` rows for one site.
///
/// `equipment_ids` is an exact id list. A shorter id does not select a longer one.
/// An empty list reads every equipment id on the site. A database error is
/// returned. Zero rows in the window is an empty envelope with
/// [`NO_SAMPLES_IN_WINDOW`], not an error and not a fabricated series.
pub async fn load_from_history(
    pool: &sqlx::PgPool,
    building_id: &str,
    equipment_ids: Option<&[String]>,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<AnalyticsEnvelope> {
    let building_id = building_id.trim();
    if building_id.is_empty() {
        anyhow::bail!("building_id is required to load sensor health");
    }
    let (start_t, end_t) = historian::resolve_analytics_window(
        start,
        end,
        historian::SENSOR_HEALTH_DEFAULT_LOOKBACK_DAYS,
    )
    .map_err(|err| anyhow::anyhow!(err))?;
    let Some(end_t) = end_t else {
        anyhow::bail!("sensor health window is missing an end");
    };
    if start_t >= end_t {
        anyhow::bail!("query.start must be before query.end");
    }
    let ids = exact_equipment_ids(equipment_ids);
    let id_bind = if ids.is_empty() { None } else { Some(ids) };
    let rows = sqlx::query(SENSOR_HEALTH_SQL)
        .bind(building_id)
        .bind(start_t)
        .bind(end_t)
        .bind(id_bind.clone())
        .fetch_all(pool)
        .await
        .context("sensor health historian query failed")?;

    let mut series = Vec::with_capacity(rows.len());
    let mut point_count: u64 = 0;
    for row in &rows {
        let series_row = series_row_from_sql(row)?;
        point_count = point_count.saturating_add(series_row.n);
        series.push(series_row);
    }
    let empty = series.is_empty();
    let mut warnings = Vec::new();
    if empty {
        warnings.push("no samples in the requested window".to_string());
    }
    let mut env = envelope_with_engine(
        QV_SENSOR_HEALTH,
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            equipment_ids: id_bind.clone(),
            start: Some(start_t),
            end: Some(end_t),
            ..Default::default()
        },
        warnings,
        "timescale-sql",
    );
    let mut encoded = Vec::with_capacity(series.len());
    for row in &series {
        let mut value =
            serde_json::to_value(row).context("sensor health row could not be encoded")?;
        if let Some(obj) = value.as_object_mut() {
            obj.insert("building_id".to_string(), json!(building_id));
        }
        encoded.push(value);
    }
    env.rows = encoded;
    env.equipment = env.rows.clone();
    let mut coverage = json!({
        "series_count": env.rows.len(),
        "point_count": point_count,
        "source": "timescale_sample",
        "building_id": building_id,
        "window_start": start_t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        "window_end": end_t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
    });
    if empty {
        coverage["reason"] = json!(NO_SAMPLES_IN_WINDOW);
    }
    if let Some(ids) = &id_bind {
        coverage["equipment_ids"] = json!(ids);
    }
    env.coverage = Some(coverage);
    Ok(env)
}

fn exact_equipment_ids(equipment_ids: Option<&[String]>) -> Vec<String> {
    let mut ids: Vec<String> = equipment_ids
        .unwrap_or(&[])
        .iter()
        .map(|id| id.trim().to_string())
        .filter(|id| !id.is_empty())
        .collect();
    ids.sort();
    ids.dedup();
    ids
}

fn series_row_from_sql(row: &sqlx::postgres::PgRow) -> Result<SensorSeriesRow> {
    let n = count_column(row, "n")?;
    let n_finite = count_column(row, "n_finite")?;
    let coverage_pct = if n > 0 {
        round2(100.0 * n_finite as f64 / n as f64)
    } else {
        0.0
    };
    let missingness = if n > 0 {
        round4(1.0 - (n_finite as f64 / n as f64))
    } else {
        0.0
    };
    let min = finite_stat(row, "min_val", round4)?;
    let max = finite_stat(row, "max_val", round4)?;
    let mean = finite_stat(row, "mean_val", round4)?;
    let std = finite_stat(row, "std_val", round6)?;
    let flatline_flag = n_finite > DEFAULT_FLATLINE_MIN_N as u64
        && std.is_some_and(|value| value <= DEFAULT_FLATLINE_STD_EPS);
    Ok(SensorSeriesRow {
        equipment_id: row
            .try_get::<String, _>("equipment_id")
            .context("sensor health equipment_id")?,
        role: row
            .try_get::<String, _>("role")
            .context("sensor health role")?,
        n,
        n_finite,
        coverage_pct,
        missingness,
        flatline_flag,
        min,
        max,
        mean,
        std,
    })
}

fn count_column(row: &sqlx::postgres::PgRow, name: &str) -> Result<u64> {
    let value = row
        .try_get::<i64, _>(name)
        .with_context(|| format!("sensor health {name}"))?;
    u64::try_from(value).with_context(|| format!("sensor health {name} is negative"))
}

fn finite_stat(
    row: &sqlx::postgres::PgRow,
    name: &str,
    round: fn(f64) -> f64,
) -> Result<Option<f64>> {
    let value = row
        .try_get::<Option<f64>, _>(name)
        .with_context(|| format!("sensor health {name}"))?;
    Ok(value.filter(|stat| stat.is_finite()).map(round))
}

fn parse_points(req: &AnalyticsRequest) -> Option<Vec<SensorPoint>> {
    let series = req.series.as_ref()?;
    let arr = if let Some(a) = series.as_array() {
        a.clone()
    } else {
        let a = series.get("points").and_then(|v| v.as_array())?;
        a.clone()
    };
    let mut out = Vec::new();
    for v in arr {
        if let Ok(p) = serde_json::from_value::<SensorPoint>(v) {
            out.push(p);
        }
    }
    Some(out)
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}
fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}
fn round6(x: f64) -> f64 {
    (x * 1_000_000.0).round() / 1_000_000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts(secs: i64) -> DateTime<Utc> {
        Utc.timestamp_opt(secs, 0).unwrap()
    }

    fn pt(eq: &str, role: &str, t: i64, v: Option<f64>) -> SensorPoint {
        SensorPoint {
            equipment_id: eq.into(),
            role: role.into(),
            timestamp: ts(t),
            value: v,
        }
    }

    #[test]
    fn coverage_and_stats_for_varied_series() {
        let pts = vec![
            pt("AHU-1", "sat", 0, Some(55.0)),
            pt("AHU-1", "sat", 300, Some(56.0)),
            pt("AHU-1", "sat", 600, Some(54.0)),
            pt("AHU-1", "sat", 900, None),
        ];
        let rows = compute_sensor_health(&pts, 5, 1e-9);
        assert_eq!(rows.len(), 1);
        let r = &rows[0];
        assert_eq!(r.n, 4);
        assert_eq!(r.n_finite, 3);
        assert!((r.coverage_pct - 75.0).abs() < 1e-9);
        assert!((r.missingness - 0.25).abs() < 1e-9);
        assert!(!r.flatline_flag);
        assert_eq!(r.min, Some(54.0));
        assert_eq!(r.max, Some(56.0));
        assert!((r.mean.unwrap() - 55.0).abs() < 1e-9);
    }

    #[test]
    fn flatline_when_std_near_zero_and_n_gt_min() {
        let pts: Vec<_> = (0..8)
            .map(|i| pt("SEN-1", "zone_t", i * 300, Some(72.0)))
            .collect();
        let rows = compute_sensor_health(&pts, 5, 1e-9);
        assert!(rows[0].flatline_flag);
        assert_eq!(rows[0].std, Some(0.0));
    }

    #[test]
    fn no_flatline_when_n_le_min() {
        let pts: Vec<_> = (0..4)
            .map(|i| pt("SEN-1", "zone_t", i * 300, Some(72.0)))
            .collect();
        let rows = compute_sensor_health(&pts, 5, 1e-9);
        assert!(!rows[0].flatline_flag);
    }

    #[test]
    fn handle_groups_series() {
        let req = AnalyticsRequest {
            series: Some(json!({
                "points": [
                    {"equipment_id": "AHU-1", "role": "sat", "timestamp": "2024-01-01T00:00:00Z", "value": 55.0},
                    {"equipment_id": "AHU-1", "role": "mat", "timestamp": "2024-01-01T00:00:00Z", "value": 60.0}
                ]
            })),
            ..Default::default()
        };
        let env = handle(&req);
        assert_eq!(env.query_version, QV_SENSOR_HEALTH);
        assert_eq!(env.rows.len(), 2);
        assert_eq!(env.engine, super::super::ENGINE);
    }

    #[tokio::test]
    async fn inline_series_does_not_query_the_historian() {
        let req = AnalyticsRequest {
            series: Some(json!({
                "points": [
                    {"equipment_id": "EQ_1", "role": "sat", "timestamp": "2024-01-01T00:00:00Z", "value": 55.0}
                ]
            })),
            ..Default::default()
        };
        let env = handle_async(&req).await.expect("inline series");
        assert_eq!(env.rows.len(), 1);
        assert_eq!(env.engine, super::super::ENGINE);
        assert!(env
            .warnings
            .iter()
            .all(|warning| !warning.contains("no samples in the requested window")));
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "OPENFDD_HISTORIAN is process-global while this failure path is asserted"
    )]
    #[tokio::test]
    async fn retired_historian_is_an_error_not_an_empty_success() {
        let _lock = crate::test_env_lock::lock_env();
        let _env = EnvRestore::capture(&["OPENFDD_HISTORIAN", "OPENFDD_DATABASE_URL"]);
        let _pool = PoolReset;
        std::env::set_var("OPENFDD_HISTORIAN", "parquet");
        std::env::remove_var("OPENFDD_DATABASE_URL");
        fdd_tsdb::clear_shared_pool();
        let err = handle_async(&history_request("w5shretired", None, None, None))
            .await
            .expect_err("retired historian");
        let message = err.to_string();
        assert!(
            message.contains("retired") || message.contains("historian"),
            "{message}"
        );
        assert!(!message.contains("no inline series"));
        assert!(!message.contains("no samples in the requested window"));
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "OPENFDD_* env is process-global while this historian fixture is connected"
    )]
    #[tokio::test]
    async fn timescale_history_empty_window_and_injected_error() {
        let explicit = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        let url = explicit
            .clone()
            .unwrap_or_else(|| "postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd".into());
        let pool = match sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
        {
            Ok(pool) => pool,
            Err(err) if explicit.is_some() => {
                panic!("OPENFDD_TEST_DATABASE_URL connect failed: {err}")
            }
            Err(err) => {
                eprintln!("skip: postgres fixture unavailable: {err}");
                return;
            }
        };

        let _lock = crate::test_env_lock::lock_env();
        let _env = EnvRestore::capture(&[
            "OPENFDD_DATABASE_URL",
            "OPENFDD_HISTORIAN",
            "OPENFDD_TIMESCALE_ACQUIRE_SECS",
        ]);
        let _pool = PoolReset;
        std::env::set_var("OPENFDD_DATABASE_URL", &url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        fdd_tsdb::clear_shared_pool();

        let token = uuid::Uuid::new_v4().simple().to_string();
        let site = format!("w5sh{}", &token[..8]);
        let other = format!("w5so{}", &token[..8]);
        assert_disposable(&site);
        assert_disposable(&other);
        let _cleanup = SiteCleanup {
            url: url.clone(),
            sites: vec![site.clone(), other.clone()],
        };
        ensure_sensor_schema(&pool).await;
        delete_site(&pool, &site).await;
        delete_site(&pool, &other).await;

        let start = chrono::Utc
            .with_ymd_and_hms(2026, 6, 1, 0, 0, 0)
            .single()
            .expect("start");
        let end = chrono::Utc
            .with_ymd_and_hms(2026, 6, 2, 0, 0, 0)
            .single()
            .expect("end");
        let varied = [70.0, 71.0, 72.0, 70.0, 71.0, 72.0, 70.0];
        for (index, value) in varied.iter().enumerate() {
            insert_sample(
                &pool,
                &site,
                "UNIT_1.sat",
                start + chrono::Duration::minutes(index as i64),
                Some(*value),
            )
            .await;
        }
        insert_sample(
            &pool,
            &site,
            "UNIT_1.sat",
            start + chrono::Duration::minutes(varied.len() as i64),
            None,
        )
        .await;
        for index in 0..8 {
            insert_sample(
                &pool,
                &site,
                "UNIT_1.fan_status",
                start + chrono::Duration::minutes(index),
                Some(1.0),
            )
            .await;
        }
        insert_sample(
            &pool,
            &site,
            "UNIT_10.sat",
            start + chrono::Duration::minutes(1),
            Some(80.0),
        )
        .await;
        insert_sample(
            &pool,
            &other,
            "UNIT_1.sat",
            start + chrono::Duration::minutes(1),
            Some(90.0),
        )
        .await;
        let recent = chrono::Utc::now() - chrono::Duration::hours(1);
        insert_sample(&pool, &site, "UNIT_1.zone_t", recent, Some(68.0)).await;
        insert_sample(
            &pool,
            &site,
            "UNIT_1.oa_t",
            chrono::Utc::now() - chrono::Duration::days(40),
            Some(50.0),
        )
        .await;

        let populated = crate::timescale_analytics::respond_query(
            "sensor-health",
            QV_SENSOR_HEALTH,
            &history_request(&site, Some(vec!["UNIT_1".into()]), Some(start), Some(end)),
        )
        .await
        .expect("populated history");
        assert!(populated.get("ok").is_none() || populated["ok"] != json!(false));
        let rows = populated["rows"].as_array().expect("rows");
        assert_eq!(rows.len(), 2, "{populated}");
        let sat = rows
            .iter()
            .find(|row| row["role"] == "sat")
            .expect("sat row");
        let flat = rows
            .iter()
            .find(|row| row["role"] == "fan_status")
            .expect("flatline row");
        assert_eq!(sat["equipment_id"], "UNIT_1");
        assert_eq!(sat["building_id"], site);
        assert_eq!(sat["n"], 8);
        assert_eq!(sat["n_finite"], 7);
        assert_eq!(sat["coverage_pct"], 87.5);
        assert_eq!(sat["missingness"], 0.125);
        assert_eq!(sat["flatline_flag"], false);
        assert_eq!(sat["mean"], 70.8571);
        assert_eq!(flat["flatline_flag"], true);
        assert_eq!(flat["std"], 0.0);
        assert_eq!(flat["coverage_pct"], 100.0);
        assert!(rows.iter().all(|row| row["equipment_id"] == "UNIT_1"));
        assert!(rows
            .iter()
            .all(|row| row["role"] != "oa_t" && row["role"] != "zone_t"));
        let warnings = warning_text(&populated);
        assert!(!warnings.contains("no inline series"));
        assert!(!warnings.contains("historian/job"));
        assert_eq!(populated["engine"], "timescale-sql");
        assert_eq!(populated["coverage"]["source"], "timescale_sample");
        assert!(populated["coverage"].get("reason").is_none());

        let outside = crate::timescale_analytics::respond_query(
            "sensor-health",
            QV_SENSOR_HEALTH,
            &history_request(
                &site,
                Some(vec!["UNIT_1".into()]),
                Some(chrono::Utc.with_ymd_and_hms(2020, 1, 1, 0, 0, 0).unwrap()),
                Some(chrono::Utc.with_ymd_and_hms(2020, 1, 2, 0, 0, 0).unwrap()),
            ),
        )
        .await
        .expect("empty window is a successful query");
        assert_eq!(outside["rows"].as_array().map(Vec::len), Some(0));
        assert_eq!(outside["coverage"]["reason"], NO_SAMPLES_IN_WINDOW);
        assert_eq!(outside["coverage"]["series_count"], 0);
        let outside_warnings = warning_text(&outside);
        assert!(outside_warnings.contains("no samples in the requested window"));
        assert!(!outside_warnings.contains("no inline series"));
        assert!(!outside_warnings.contains("historian/job"));
        assert!(outside.get("ok").is_none() || outside["ok"] != json!(false));

        let current = handle_async(&history_request(
            &site,
            Some(vec!["UNIT_1".into()]),
            None,
            None,
        ))
        .await
        .expect("default lookback");
        let roles: Vec<&str> = current
            .rows
            .iter()
            .filter_map(|row| row["role"].as_str())
            .collect();
        assert!(roles.contains(&"zone_t"), "{roles:?}");
        assert!(!roles.contains(&"oa_t"), "{roles:?}");
        assert!(current
            .warnings
            .iter()
            .any(|warning| warning.contains("defaulted start")));
        assert!(!current
            .warnings
            .iter()
            .any(|warning| warning.contains("no inline series")));

        let closed = sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .connect(&url)
            .await
            .expect("closed-pool fixture");
        closed.close().await;
        let query_err = load_from_history(
            &closed,
            &site,
            Some(&["UNIT_1".to_string()]),
            Some(start),
            Some(end),
        )
        .await
        .expect_err("closed pool");
        let query_message = query_err.to_string();
        assert!(
            query_message.contains("sensor health historian query failed"),
            "{query_message}"
        );
        assert!(!query_message.contains("no inline series"));
        assert!(!query_message.contains("no samples in the requested window"));

        std::env::set_var("OPENFDD_TIMESCALE_ACQUIRE_SECS", "2");
        std::env::set_var(
            "OPENFDD_DATABASE_URL",
            "postgresql://openfdd:openfdd@127.0.0.1:1/openfdd",
        );
        fdd_tsdb::clear_shared_pool();
        let handler_err = crate::timescale_analytics::respond_query(
            "sensor-health",
            QV_SENSOR_HEALTH,
            &history_request(&site, Some(vec!["UNIT_1".into()]), Some(start), Some(end)),
        )
        .await
        .expect_err("injected historian connection error");
        assert_ne!(handler_err.0, axum::http::StatusCode::OK);
        assert_eq!(handler_err.1["ok"], json!(false));
        let handler_message = handler_err.1["error"].as_str().unwrap_or_default();
        assert!(!handler_message.is_empty());
        assert!(handler_err.1.get("rows").is_none());
        assert!(!handler_message.contains("no inline series"));
        assert!(!handler_message.contains("no samples in the requested window"));
    }

    fn history_request(
        building_id: &str,
        equipment_ids: Option<Vec<String>>,
        start: Option<chrono::DateTime<chrono::Utc>>,
        end: Option<chrono::DateTime<chrono::Utc>>,
    ) -> AnalyticsRequest {
        AnalyticsRequest {
            query: AnalyticsQuery {
                building_id: Some(building_id.to_string()),
                equipment_ids,
                start,
                end,
                ..Default::default()
            },
            ..Default::default()
        }
    }

    fn warning_text(body: &serde_json::Value) -> String {
        body["warnings"]
            .as_array()
            .map(|warnings| {
                warnings
                    .iter()
                    .filter_map(|warning| warning.as_str())
                    .collect::<Vec<_>>()
                    .join("\n")
            })
            .unwrap_or_default()
    }

    fn assert_disposable(id: &str) {
        let upper = id.to_ascii_uppercase();
        assert!(upper != "BUILDING_50" && upper != "BOSSPI");
        assert!(!upper.contains("BUILDING_50") && !upper.contains("BOSSPI"));
    }

    async fn ensure_sensor_schema(pool: &sqlx::PgPool) {
        for statement in [
            "CREATE TABLE IF NOT EXISTS site (
                site_id text PRIMARY KEY,
                dis text,
                timezone text NOT NULL DEFAULT 'UTC',
                enabled boolean NOT NULL DEFAULT true,
                created_at timestamptz NOT NULL DEFAULT now()
            )",
            "CREATE TABLE IF NOT EXISTS sample (
                ts timestamptz NOT NULL,
                site_id text NOT NULL,
                openfdd_key text NOT NULL,
                haystack_id text,
                val double precision,
                unit text,
                quality text,
                PRIMARY KEY (site_id, openfdd_key, ts)
            )",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS haystack_id text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS unit text",
            "ALTER TABLE sample ADD COLUMN IF NOT EXISTS quality text",
        ] {
            sqlx::query(statement)
                .execute(pool)
                .await
                .expect("fixture schema");
        }
    }

    async fn insert_sample(
        pool: &sqlx::PgPool,
        site: &str,
        openfdd_key: &str,
        ts: chrono::DateTime<chrono::Utc>,
        val: Option<f64>,
    ) {
        sqlx::query(
            "INSERT INTO sample(ts, site_id, openfdd_key, val)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (site_id, openfdd_key, ts) DO UPDATE SET val = EXCLUDED.val",
        )
        .bind(ts)
        .bind(site)
        .bind(openfdd_key)
        .bind(val)
        .execute(pool)
        .await
        .expect("sample");
    }

    async fn delete_site(pool: &sqlx::PgPool, site: &str) {
        sqlx::query("DELETE FROM sample WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await
            .expect("delete samples");
    }

    struct EnvRestore {
        saved: Vec<(&'static str, Option<String>)>,
    }

    impl EnvRestore {
        fn capture(keys: &[&'static str]) -> Self {
            Self {
                saved: keys
                    .iter()
                    .map(|key| (*key, std::env::var(key).ok()))
                    .collect(),
            }
        }
    }

    impl Drop for EnvRestore {
        fn drop(&mut self) {
            for (key, value) in self.saved.drain(..) {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
        }
    }

    struct PoolReset;

    impl Drop for PoolReset {
        fn drop(&mut self) {
            fdd_tsdb::clear_shared_pool();
        }
    }

    struct SiteCleanup {
        url: String,
        sites: Vec<String>,
    }

    impl Drop for SiteCleanup {
        fn drop(&mut self) {
            let url = self.url.clone();
            let sites: Vec<String> = self
                .sites
                .drain(..)
                .filter(|id| {
                    let upper = id.to_ascii_uppercase();
                    upper != "BUILDING_50"
                        && upper != "BOSSPI"
                        && !upper.contains("BUILDING_50")
                        && !upper.contains("BOSSPI")
                })
                .collect();
            if sites.is_empty() {
                return;
            }
            let _ = std::thread::spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("cleanup runtime");
                runtime.block_on(async move {
                    let Ok(pool) = sqlx::postgres::PgPoolOptions::new()
                        .max_connections(1)
                        .connect(&url)
                        .await
                    else {
                        return;
                    };
                    for site in sites {
                        let _ = sqlx::query("DELETE FROM sample WHERE site_id = $1")
                            .bind(site)
                            .execute(&pool)
                            .await;
                    }
                    pool.close().await;
                });
            })
            .join();
        }
    }
}
