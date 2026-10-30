//! Wave-X default historian surface — DataFusion retired (ADR-010).

#![expect(
    dead_code,
    reason = "API-parity stubs with historian_datafusion; Timescale product uses timescale_* modules"
)]

use std::path::PathBuf;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use chrono::{DateTime, Utc};

use crate::analytics::{AnalyticsEnvelope, AnalyticsQuery, AnalyticsRequest};

pub const SENSOR_HEALTH_DEFAULT_LOOKBACK_DAYS: i64 = 14;
pub const RUNTIME_DEFAULT_LOOKBACK_DAYS: i64 = 7;
pub const BAS_VS_WEB_DEFAULT_LOOKBACK_DAYS: i64 = RUNTIME_DEFAULT_LOOKBACK_DAYS;
pub const ECONOMIZER_DEFAULT_LOOKBACK_DAYS: i64 = 14;
pub const VAV_HEALTH_DEFAULT_LOOKBACK_DAYS: i64 = 14;
pub const ANALYTICS_MAX_LOOKBACK_DAYS: i64 = 90;
pub const BAS_VS_WEB_QUERY_TIMEOUT: Duration = Duration::from_secs(30);
pub const RUNTIME_RETAIN_FALLBACK_DAYS: i64 = 365;
pub const BAS_VS_WEB_RETAIN_FALLBACK_DAYS: i64 = RUNTIME_RETAIN_FALLBACK_DAYS;
pub const BAS_VS_WEB_ROW_LIMIT_MAX: i64 = 2000;

/// Row cap for bas-vs-web-oat SQL (`LIMIT $7`). Rejects out-of-range values; when
/// omitted the HTTP handler uses [`BAS_VS_WEB_ROW_LIMIT_MAX`] explicitly.
pub fn validated_bas_vs_web_max_points(max_points: Option<usize>) -> Result<i64, String> {
    match max_points {
        None => Ok(BAS_VS_WEB_ROW_LIMIT_MAX),
        Some(0) => Err("max_points must be at least 1 for bas-vs-web-oat".into()),
        Some(n) if n > BAS_VS_WEB_ROW_LIMIT_MAX as usize => Err(format!(
            "max_points exceeds bas-vs-web-oat limit of {BAS_VS_WEB_ROW_LIMIT_MAX}"
        )),
        Some(n) => i64::try_from(n).map_err(|_| "max_points out of range".into()),
    }
}

pub const RUNTIME_QUERY_TIMEOUT: Duration = Duration::from_secs(30);
pub const MECH_DEFAULT_LOOKBACK_DAYS: i64 = 14;
pub const MECH_RETAIN_FALLBACK_DAYS: i64 = 365;
pub const MECH_QUERY_TIMEOUT: Duration = Duration::from_secs(30);
pub const ANOMALY_DEFAULT_LOOKBACK_DAYS: i64 = 14;
pub const ANOMALY_SCREEN_ROLES: &[&str] = &[
    "sat",
    "mat",
    "rat",
    "oa_t",
    "zone_t",
    "chw_supply_t",
    "hw_supply_t",
];

#[derive(Debug, Clone)]
pub struct SqlAnomalyRequest<'a> {
    pub equipment_filter: Option<&'a [String]>,
    pub building_id: Option<&'a str>,
    pub window_rows: u32,
    pub z_threshold: f64,
    pub method: &'a str,
    pub transition_events: bool,
    pub start: Option<DateTime<Utc>>,
    pub end: Option<DateTime<Utc>>,
}

fn retired<T>() -> Result<T> {
    bail!("Wave-X 3.6.0: DataFusion historian retired; use the Timescale analytics path")
}

pub fn parquet_root() -> PathBuf {
    parquet_root_base()
}

pub fn parquet_root_base() -> PathBuf {
    std::env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
        .join("openfdd-compat-retired")
}

pub fn parquet_root_for_context(_ctx: &crate::tenant::TenantContext) -> Result<PathBuf, String> {
    Ok(parquet_root_base())
}

pub fn list_equipment_ids_from_hive(_building_id: &str) -> Vec<String> {
    Vec::new()
}

pub fn plant_group_for_typed(
    _equipment_id: &str,
    _stamped_type: Option<&str>,
) -> Option<&'static str> {
    None
}

pub(crate) fn history_role_numeric_sql(col: &str) -> String {
    format!("CAST({col} AS DOUBLE)")
}

pub(crate) fn remaining_budget(deadline: tokio::time::Instant, _nominal: Duration) -> Duration {
    deadline.saturating_duration_since(tokio::time::Instant::now())
}

pub fn resolve_analytics_window(
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
    default_lookback_days: i64,
) -> Result<(DateTime<Utc>, Option<DateTime<Utc>>), String> {
    let end_t = end.unwrap_or_else(Utc::now);
    let start_t =
        start.unwrap_or_else(|| end_t - chrono::Duration::days(default_lookback_days.max(1)));
    if start_t >= end_t {
        return Err("query.start must be before query.end".into());
    }
    Ok((start_t, Some(end_t)))
}

pub async fn runtime_from_history(
    equipment_filter: Option<&[String]>,
    max_gap_seconds: f64,
    building_id: Option<&str>,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (equipment_filter, max_gap_seconds, building_id, start, end);
    retired()
}

pub async fn sensor_health_from_history(
    equipment_filter: Option<&[String]>,
    building_id: Option<&str>,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<Option<AnalyticsEnvelope>> {
    if !crate::timescale_historian::historian_is_timescale() {
        let _ = (equipment_filter, building_id, start, end);
        return retired();
    }
    let Some(building_id) = building_id.map(str::trim).filter(|id| !id.is_empty()) else {
        bail!("building_id is required to load sensor health");
    };
    let tsdb = fdd_tsdb::Tsdb::connect_from_env().await?;
    let env = crate::analytics::sensor_health::load_from_history(
        tsdb.pool(),
        building_id,
        equipment_filter,
        start,
        end,
    )
    .await?;
    Ok(Some(env))
}

pub async fn sensor_stats_from_history(
    equipment_filter: Option<&[String]>,
    building_id: Option<&str>,
    fan_state: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (equipment_filter, building_id, fan_state);
    retired()
}

pub async fn setpoints_from_history(
    equipment_filter: Option<&[String]>,
    building_id: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (equipment_filter, building_id);
    retired()
}

pub async fn diurnal_from_history(
    equipment_filter: Option<&[String]>,
    building_id: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (equipment_filter, building_id);
    retired()
}

pub async fn topology_from_history(building_id: Option<&str>) -> Result<Option<AnalyticsEnvelope>> {
    let _ = building_id;
    retired()
}

pub async fn schedule_from_history(
    equipment_filter: Option<&[String]>,
    max_gap_seconds: f64,
    building_id: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (equipment_filter, max_gap_seconds, building_id);
    retired()
}

pub async fn economizer_from_history(
    equipment_filter: Option<&[String]>,
    dt_min_f: f64,
    building_id: Option<&str>,
    max_points: usize,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (
        equipment_filter,
        dt_min_f,
        building_id,
        max_points,
        start,
        end,
    );
    retired()
}

pub async fn mech_cooling_evidence_warnings(building_id: Option<&str>) -> Result<Vec<String>> {
    let _ = building_id;
    retired()
}

pub async fn mech_oat_bins_from_history(
    equipment_filter: Option<&[String]>,
    max_gap_seconds: f64,
    building_id: Option<&str>,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (equipment_filter, max_gap_seconds, building_id, start, end);
    retired()
}

pub async fn bas_vs_web_from_history(
    equipment_filter: Option<&[String]>,
    max_points: usize,
    building_id: Option<&str>,
    preferred_tenant: Option<&str>,
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = preferred_tenant;
    if !crate::timescale_historian::historian_is_timescale() {
        return retired();
    }
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(None);
    };
    let tsdb = fdd_tsdb::Tsdb::connect_from_env()
        .await
        .context("timescale connect for bas-vs-web-oat")?;
    let mut equipment_ids = equipment_filter
        .map(|ids| ids.iter().map(|s| s.to_string()).collect::<Vec<_>>())
        .unwrap_or_default();
    equipment_ids.retain(|id| !id.trim().is_empty());
    equipment_ids.sort();
    equipment_ids.dedup();
    let scope = crate::timescale_analytics::AnalyticsSqlScope {
        start,
        end,
        equipment_ids,
    };
    let limit = validated_bas_vs_web_max_points(Some(max_points))
        .map_err(|msg| anyhow::anyhow!("bas-vs-web-oat max_points: {msg}"))?;
    let value = crate::timescale_analytics::bas_vs_web_oat(&tsdb, bid, &scope, limit)
        .await
        .context("bas_vs_web_oat timescale")?;
    let req = AnalyticsRequest {
        query: AnalyticsQuery {
            building_id: Some(bid.to_string()),
            start,
            end,
            equipment_ids: equipment_filter.map(|ids| ids.to_vec()),
            ..Default::default()
        },
        ..Default::default()
    };
    Ok(Some(
        crate::timescale_analytics::envelope_from_dispatch_value("bas-vs-web-oat-v4", &req, value),
    ))
}

pub async fn inspect_from_history(
    building_id: Option<&str>,
    equipment_id: &str,
    columns: Option<&[String]>,
    max_points: usize,
    preferred_tenant: Option<&str>,
    scope: &crate::timescale_analytics::AnalyticsSqlScope,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = preferred_tenant;
    if crate::timescale_historian::historian_is_timescale() {
        let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
            return Ok(None);
        };
        return crate::timescale_product::inspect_equipment(
            bid,
            equipment_id,
            columns,
            max_points,
            scope,
        )
        .await;
    }
    retired()
}

pub async fn rcx_timeseries_from_history(
    building_id: Option<&str>,
    role_col: &str,
    overlay_col: Option<&str>,
    pair_return_col: Option<&str>,
    eq_kinds: &[&str],
    filter_fan_on: bool,
    read: &crate::timescale_product::RcxQuery,
) -> Result<Option<AnalyticsEnvelope>> {
    if crate::timescale_historian::historian_is_timescale() {
        let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
            return Ok(None);
        };
        return crate::timescale_product::rcx_timeseries(
            bid,
            role_col,
            overlay_col,
            pair_return_col,
            eq_kinds,
            filter_fan_on,
            read,
        )
        .await;
    }
    retired()
}

pub async fn rcx_oat_scatter_from_history(
    building_id: Option<&str>,
    y_col: &str,
    eq_kinds: &[&str],
    prefer_wetbulb: bool,
    read: &crate::timescale_product::RcxQuery,
) -> Result<Option<AnalyticsEnvelope>> {
    if crate::timescale_historian::historian_is_timescale() {
        let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
            return Ok(None);
        };
        return crate::timescale_product::rcx_oat_scatter(
            bid,
            y_col,
            eq_kinds,
            prefer_wetbulb,
            read,
        )
        .await;
    }
    retired()
}

pub async fn rcx_box_from_history(
    building_id: Option<&str>,
    role_col: &str,
    eq_kinds: &[&str],
    filter_fan_on: bool,
    read: &crate::timescale_product::RcxQuery,
) -> Result<Option<AnalyticsEnvelope>> {
    if crate::timescale_historian::historian_is_timescale() {
        let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
            return Ok(None);
        };
        return crate::timescale_product::rcx_box(bid, role_col, eq_kinds, filter_fan_on, read)
            .await;
    }
    retired()
}

pub async fn rcx_zone_comfort_rank_from_history(
    building_id: Option<&str>,
    eq_kinds: &[&str],
    comfort_low_c: f64,
    comfort_high_c: f64,
    scope: &crate::timescale_analytics::AnalyticsSqlScope,
) -> Result<Option<AnalyticsEnvelope>> {
    if crate::timescale_historian::historian_is_timescale() {
        let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
            return Ok(None);
        };
        return crate::timescale_product::rcx_zone_comfort_rank(
            bid,
            eq_kinds,
            comfort_low_c,
            comfort_high_c,
            scope,
        )
        .await;
    }
    retired()
}

pub async fn rcx_metering_from_history(
    building_id: Option<&str>,
    role_col: &str,
    eq_kinds: &[&str],
    kind: &str,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (building_id, role_col, eq_kinds, kind);
    retired()
}

pub async fn descriptive_counts_from_history(
    query_version: &str,
    equipment_filter: Option<&[String]>,
    note: &str,
    building_id: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (query_version, equipment_filter, note, building_id);
    retired()
}

pub async fn descriptive_counts_from_history_filtered(
    query_version: &str,
    equipment_filter: Option<&[String]>,
    note: &str,
    building_id: Option<&str>,
    cohort_kinds: Option<&[&str]>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = (
        query_version,
        equipment_filter,
        note,
        building_id,
        cohort_kinds,
    );
    retired()
}

pub async fn sql_anomaly_from_history(
    req: SqlAnomalyRequest<'_>,
) -> Result<Option<AnalyticsEnvelope>> {
    let _ = req;
    retired()
}
