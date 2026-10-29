//! One-time in-place SI cutover for historian samples (#1284 W2c).

use std::collections::{BTreeMap, HashMap};

use chrono::{DateTime, Utc};
use fdd_core::{
    quantity_for_sql_role, MetricContractError, MetricUnitsContract, METRIC_UNITS_JSON,
};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Row, Transaction};

use crate::ingest_si::{
    resolve_declared_source_unit, PointMapBinding, SampleDeclaredContext,
    QUALITY_UNIT_CONTRACT_MISSING, QUALITY_UNIT_UNDECLARED,
};

pub const SCHEMA_SQL: &str = include_str!("../../../sql/schema/12_si_cutover.sql");

const DEFAULT_CHUNK_ROWS: i64 = 10_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SeriesConversionPlan {
    pub openfdd_key: String,
    pub quantity: String,
    pub from_unit: String,
    pub to_unit: String,
    pub row_count: i64,
    pub checksum: String,
    pub excluded: bool,
    pub unresolved: bool,
    pub already_converted: bool,
    pub min_ts: Option<DateTime<Utc>>,
    pub max_ts: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SiteDryRunReport {
    pub site_id: String,
    pub series_by_quantity_unit: BTreeMap<String, i64>,
    pub rows_to_convert: i64,
    pub unresolved_series: Vec<String>,
    pub excluded_series: Vec<String>,
    pub saved_params_to_convert: i64,
    pub series: Vec<SeriesConversionPlan>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SiteCutoverResult {
    pub site_id: String,
    pub rows_converted: i64,
    pub series_converted: i64,
    pub series_skipped: i64,
    pub params_revisions_written: i64,
}

#[derive(Debug, thiserror::Error)]
pub enum SiCutoverError {
    #[error("database: {0}")]
    Db(#[from] sqlx::Error),
    #[error("contract: {0}")]
    Contract(#[from] MetricContractError),
    #[error("unresolved unit-dependent series remain for site {site_id}: {keys:?}")]
    UnresolvedSeries { site_id: String, keys: Vec<String> },
    #[error("invalid configuration: {0}")]
    Config(String),
}

pub fn chunk_rows_limit() -> i64 {
    std::env::var("OPENFDD_SI_CUTOVER_CHUNK_ROWS")
        .ok()
        .and_then(|v| v.trim().parse().ok())
        .filter(|&n| n > 0)
        .unwrap_or(DEFAULT_CHUNK_ROWS)
}

pub fn contract() -> Result<MetricUnitsContract, MetricContractError> {
    MetricUnitsContract::from_json(METRIC_UNITS_JSON)
}

fn quantity_needs_unit(qty: &str) -> bool {
    !matches!(
        qty,
        "status"
            | "count"
            | "boolean"
            | "occupancy_mode"
            | "dimensionless"
            | "duration_seconds"
            | "duration_minutes"
            | "seconds"
            | "minutes"
    )
}

fn series_checksum(
    site_id: &str,
    openfdd_key: &str,
    from_unit: &str,
    to_unit: &str,
    row_count: i64,
    min_ts: Option<DateTime<Utc>>,
    max_ts: Option<DateTime<Utc>>,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"openfdd-si-cutover-v1");
    hasher.update(site_id.as_bytes());
    hasher.update(b"\n");
    hasher.update(openfdd_key.as_bytes());
    hasher.update(b"\n");
    hasher.update(from_unit.as_bytes());
    hasher.update(b"\n");
    hasher.update(to_unit.as_bytes());
    hasher.update(b"\n");
    hasher.update(row_count.to_le_bytes());
    if let Some(ts) = min_ts {
        hasher.update(ts.timestamp_nanos_opt().unwrap_or(0).to_le_bytes());
    }
    if let Some(ts) = max_ts {
        hasher.update(ts.timestamp_nanos_opt().unwrap_or(0).to_le_bytes());
    }
    hex::encode(hasher.finalize())
}

async fn ledger_has_checksum<'e, E>(
    executor: E,
    site_id: &str,
    openfdd_key: &str,
    checksum: &str,
) -> Result<bool, sqlx::Error>
where
    E: sqlx::Executor<'e, Database = Postgres>,
{
    let found: Option<i32> = sqlx::query_scalar(
        "SELECT 1 FROM unit_migration WHERE site_id = $1 AND openfdd_key = $2 AND checksum = $3",
    )
    .bind(site_id)
    .bind(openfdd_key)
    .bind(checksum)
    .fetch_optional(executor)
    .await?;
    Ok(found.is_some())
}

#[derive(Debug, Clone)]
struct SeriesRow {
    openfdd_key: String,
    role: Option<String>,
    quantity: Option<String>,
    map_unit: Option<String>,
    source_unit: Option<String>,
    excluded: bool,
    row_count: i64,
    sample_unit: Option<String>,
    has_undeclared: bool,
    min_ts: Option<DateTime<Utc>>,
    max_ts: Option<DateTime<Utc>>,
}

async fn load_series_rows(
    pool: &sqlx::PgPool,
    site_id: &str,
) -> Result<Vec<SeriesRow>, sqlx::Error> {
    let point_rows = sqlx::query(
        r#"
        SELECT pm.openfdd_key,
               pm.role,
               pm.quantity,
               pm.unit,
               pm.source_unit,
               COALESCE(pm.si_cutover_exclude, false) AS excluded
        FROM point_map pm
        WHERE pm.site_id = $1
        ORDER BY pm.openfdd_key
        "#,
    )
    .bind(site_id)
    .fetch_all(pool)
    .await?;

    let sample_rows = sqlx::query(
        r#"
        SELECT openfdd_key,
               count(*)::bigint AS row_count,
               max(unit) AS sample_unit,
               bool_or(quality IN ($2, $3)) AS has_undeclared,
               min(ts) AS min_ts,
               max(ts) AS max_ts
        FROM sample
        WHERE site_id = $1
        GROUP BY openfdd_key
        "#,
    )
    .bind(site_id)
    .bind(QUALITY_UNIT_UNDECLARED)
    .bind(QUALITY_UNIT_CONTRACT_MISSING)
    .fetch_all(pool)
    .await?;

    let mut sample_by_key: HashMap<
        String,
        (
            i64,
            Option<String>,
            bool,
            Option<DateTime<Utc>>,
            Option<DateTime<Utc>>,
        ),
    > = HashMap::new();
    for row in sample_rows {
        let key: String = row.try_get("openfdd_key")?;
        sample_by_key.insert(
            key,
            (
                row.try_get::<i64, _>("row_count")?,
                row.try_get("sample_unit")?,
                row.try_get("has_undeclared")?,
                row.try_get("min_ts")?,
                row.try_get("max_ts")?,
            ),
        );
    }

    let mut out = Vec::new();
    for row in point_rows {
        let key: String = row.try_get("openfdd_key")?;
        let (row_count, sample_unit, has_undeclared, min_ts, max_ts) = sample_by_key
            .get(&key)
            .cloned()
            .unwrap_or((0, None, false, None, None));
        out.push(SeriesRow {
            openfdd_key: key,
            role: row.try_get("role")?,
            quantity: row.try_get("quantity")?,
            map_unit: row.try_get("unit")?,
            source_unit: row.try_get("source_unit")?,
            excluded: row.try_get("excluded")?,
            row_count,
            sample_unit,
            has_undeclared,
            min_ts,
            max_ts,
        });
    }

    // Sample-only keys without point_map still need conversion when present.
    for (key, (row_count, sample_unit, has_undeclared, min_ts, max_ts)) in sample_by_key {
        if out.iter().any(|s| s.openfdd_key == key) {
            continue;
        }
        out.push(SeriesRow {
            openfdd_key: key,
            role: None,
            quantity: None,
            map_unit: None,
            source_unit: None,
            excluded: false,
            row_count,
            sample_unit,
            has_undeclared,
            min_ts,
            max_ts,
        });
    }
    out.sort_by(|a, b| a.openfdd_key.cmp(&b.openfdd_key));
    Ok(out)
}

fn resolve_quantity(row: &SeriesRow) -> Option<String> {
    row.quantity
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .or_else(|| {
            row.role
                .as_deref()
                .and_then(quantity_for_sql_role)
                .map(str::to_string)
        })
}

fn resolve_source_unit(row: &SeriesRow) -> Option<String> {
    let map = PointMapBinding {
        unit: row.map_unit.as_deref(),
        source_unit: row.source_unit.as_deref(),
        quantity: row.quantity.as_deref(),
    };
    let ctx = SampleDeclaredContext {
        role: row.role.as_deref(),
        sample_unit: row.sample_unit.as_deref(),
        sample_source_unit: None,
        sample_quantity: row.quantity.as_deref(),
        csv_column_unit: None,
        unit_system: None,
    };
    resolve_declared_source_unit(map, ctx).or_else(|| row.sample_unit.clone())
}

fn plan_series(
    contract: &MetricUnitsContract,
    site_id: &str,
    row: &SeriesRow,
    ledger_skip: bool,
) -> Result<SeriesConversionPlan, MetricContractError> {
    let quantity = match resolve_quantity(row) {
        Some(q) => q,
        None => {
            return Ok(SeriesConversionPlan {
                openfdd_key: row.openfdd_key.clone(),
                quantity: String::new(),
                from_unit: String::new(),
                to_unit: String::new(),
                row_count: row.row_count,
                checksum: String::new(),
                excluded: row.excluded,
                unresolved: false,
                already_converted: true,
                min_ts: row.min_ts,
                max_ts: row.max_ts,
            });
        }
    };

    if !quantity_needs_unit(&quantity) {
        return Ok(SeriesConversionPlan {
            openfdd_key: row.openfdd_key.clone(),
            quantity,
            from_unit: String::new(),
            to_unit: String::new(),
            row_count: row.row_count,
            checksum: String::new(),
            excluded: row.excluded,
            unresolved: false,
            already_converted: true,
            min_ts: row.min_ts,
            max_ts: row.max_ts,
        });
    }

    let canonical = contract.canonical_unit(&quantity)?.to_string();
    if row.row_count == 0 {
        return Ok(SeriesConversionPlan {
            openfdd_key: row.openfdd_key.clone(),
            quantity,
            from_unit: String::new(),
            to_unit: canonical,
            row_count: 0,
            checksum: String::new(),
            excluded: row.excluded,
            unresolved: false,
            already_converted: true,
            min_ts: row.min_ts,
            max_ts: row.max_ts,
        });
    }

    if row.excluded {
        return Ok(SeriesConversionPlan {
            openfdd_key: row.openfdd_key.clone(),
            quantity,
            from_unit: String::new(),
            to_unit: canonical,
            row_count: row.row_count,
            checksum: String::new(),
            excluded: true,
            unresolved: false,
            already_converted: true,
            min_ts: row.min_ts,
            max_ts: row.max_ts,
        });
    }

    let unresolved = row.has_undeclared || resolve_source_unit(row).is_none();
    if unresolved {
        return Ok(SeriesConversionPlan {
            openfdd_key: row.openfdd_key.clone(),
            quantity,
            from_unit: String::new(),
            to_unit: canonical,
            row_count: row.row_count,
            checksum: String::new(),
            excluded: false,
            unresolved: true,
            already_converted: false,
            min_ts: row.min_ts,
            max_ts: row.max_ts,
        });
    }

    let from_unit = resolve_source_unit(row).unwrap_or_default();
    let checksum = series_checksum(
        site_id,
        &row.openfdd_key,
        &from_unit,
        &canonical,
        row.row_count,
        row.min_ts,
        row.max_ts,
    );

    let already = ledger_skip
        || normalize_alias_eq(&from_unit, &canonical)
        || row
            .sample_unit
            .as_deref()
            .is_some_and(|u| normalize_alias_eq(u, &canonical));

    Ok(SeriesConversionPlan {
        openfdd_key: row.openfdd_key.clone(),
        quantity,
        from_unit,
        to_unit: canonical,
        row_count: row.row_count,
        checksum,
        excluded: false,
        unresolved: false,
        already_converted: already,
        min_ts: row.min_ts,
        max_ts: row.max_ts,
    })
}

fn normalize_alias_eq(a: &str, b: &str) -> bool {
    fdd_core::units_contract::normalize_alias(a) == fdd_core::units_contract::normalize_alias(b)
}

pub async fn dry_run_site(
    pool: &sqlx::PgPool,
    site_id: &str,
    saved_params_to_convert: i64,
) -> Result<SiteDryRunReport, SiCutoverError> {
    let contract = contract()?;
    let rows = load_series_rows(pool, site_id).await?;
    let mut report = SiteDryRunReport {
        site_id: site_id.to_string(),
        saved_params_to_convert,
        ..Default::default()
    };

    for row in &rows {
        let ledger_skip = if row.row_count > 0 {
            let plan_probe = plan_series(&contract, site_id, row, false)?;
            if !plan_probe.checksum.is_empty() {
                ledger_has_checksum(pool, site_id, &row.openfdd_key, &plan_probe.checksum).await?
            } else {
                false
            }
        } else {
            false
        };
        let plan = plan_series(&contract, site_id, row, ledger_skip)?;
        if plan.unresolved {
            report.unresolved_series.push(plan.openfdd_key.clone());
        }
        if plan.excluded {
            report.excluded_series.push(plan.openfdd_key.clone());
        }
        if !plan.already_converted && !plan.unresolved && !plan.excluded && plan.row_count > 0 {
            report.rows_to_convert += plan.row_count;
            let bucket = format!("{}|{}", plan.quantity, plan.from_unit);
            *report.series_by_quantity_unit.entry(bucket).or_insert(0) += 1;
        }
        report.series.push(plan);
    }
    report.unresolved_series.sort();
    report.excluded_series.sort();
    Ok(report)
}

async fn convert_series_chunk(
    tx: &mut Transaction<'_, Postgres>,
    contract: &MetricUnitsContract,
    site_id: &str,
    plan: &SeriesConversionPlan,
    chunk: i64,
) -> Result<i64, SiCutoverError> {
    if plan.already_converted || plan.unresolved || plan.excluded || plan.row_count == 0 {
        return Ok(0);
    }

    let samples = sqlx::query(
        r#"
        SELECT ts, val
        FROM sample
        WHERE site_id = $1 AND openfdd_key = $2
          AND (unit IS DISTINCT FROM $3)
        ORDER BY ts
        LIMIT $4
        "#,
    )
    .bind(site_id)
    .bind(&plan.openfdd_key)
    .bind(&plan.to_unit)
    .bind(chunk)
    .fetch_all(&mut **tx)
    .await?;
    if samples.is_empty() {
        return Ok(0);
    }

    let mut updated = 0_i64;
    for row in samples {
        let ts: DateTime<Utc> = row.try_get("ts")?;
        let val: Option<f64> = row.try_get("val")?;
        let Some(raw) = val else {
            continue;
        };
        let converted = contract.convert_to_canonical(&plan.quantity, raw, &plan.from_unit)?;
        sqlx::query(
            r#"
            UPDATE sample
            SET val = $4, unit = $5, quality = NULL
            WHERE site_id = $1 AND openfdd_key = $2 AND ts = $3
            "#,
        )
        .bind(site_id)
        .bind(&plan.openfdd_key)
        .bind(ts)
        .bind(converted)
        .bind(&plan.to_unit)
        .execute(&mut **tx)
        .await?;
        updated += 1;
    }
    Ok(updated)
}

async fn record_ledger(
    tx: &mut Transaction<'_, Postgres>,
    site_id: &str,
    plan: &SeriesConversionPlan,
    started: DateTime<Utc>,
    finished: DateTime<Utc>,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO unit_migration
          (site_id, openfdd_key, from_unit, to_unit, row_count, started_at, finished_at, checksum)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT DO NOTHING
        "#,
    )
    .bind(site_id)
    .bind(&plan.openfdd_key)
    .bind(&plan.from_unit)
    .bind(&plan.to_unit)
    .bind(plan.row_count)
    .bind(started)
    .bind(finished)
    .bind(&plan.checksum)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn bump_data_revision(
    tx: &mut Transaction<'_, Postgres>,
    site_id: &str,
    openfdd_key: &str,
    min_ts: DateTime<Utc>,
    max_ts: DateTime<Utc>,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        "INSERT INTO data_revision (site_id, revision) VALUES ($1, 0) ON CONFLICT DO NOTHING",
    )
    .bind(site_id)
    .execute(&mut **tx)
    .await?;
    let current: i64 =
        sqlx::query_scalar("SELECT revision FROM data_revision WHERE site_id = $1 FOR UPDATE")
            .bind(site_id)
            .fetch_one(&mut **tx)
            .await?;
    let next = current.saturating_add(1);
    sqlx::query("UPDATE data_revision SET revision = $2, updated_at = now() WHERE site_id = $1")
        .bind(site_id)
        .bind(next)
        .execute(&mut **tx)
        .await?;
    sqlx::query(
        r#"
        INSERT INTO sample_changed_range
          (site_id, openfdd_key, revision, range_start, range_end, change_kind)
        VALUES ($1, $2, $3, $4, $5, 'upsert')
        ON CONFLICT DO NOTHING
        "#,
    )
    .bind(site_id)
    .bind(openfdd_key)
    .bind(next)
    .bind(min_ts)
    .bind(max_ts)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

pub async fn invalidate_derived_results(
    tx: &mut Transaction<'_, Postgres>,
    site_id: &str,
) -> Result<(), sqlx::Error> {
    sqlx::query("DELETE FROM fdd_run WHERE site_id = $1")
        .bind(site_id)
        .execute(&mut **tx)
        .await?;
    sqlx::query("DELETE FROM fdd_interval_result WHERE site_id = $1")
        .bind(site_id)
        .execute(&mut **tx)
        .await?;
    sqlx::query("DELETE FROM analytics_result WHERE building_id = $1")
        .bind(site_id)
        .execute(&mut **tx)
        .await?;
    Ok(())
}

pub async fn apply_sample_cutover_tx(
    tx: &mut Transaction<'_, Postgres>,
    dry: &SiteDryRunReport,
) -> Result<SiteCutoverResult, SiCutoverError> {
    if !dry.unresolved_series.is_empty() {
        return Err(SiCutoverError::UnresolvedSeries {
            site_id: dry.site_id.clone(),
            keys: dry.unresolved_series.clone(),
        });
    }
    let contract = contract()?;
    let chunk = chunk_rows_limit();
    let mut result = SiteCutoverResult {
        site_id: dry.site_id.clone(),
        ..Default::default()
    };

    for plan in &dry.series {
        if plan.already_converted || plan.excluded || plan.row_count == 0 {
            result.series_skipped += 1;
            continue;
        }
        let started = Utc::now();
        let mut converted = 0_i64;
        loop {
            let step = convert_series_chunk(tx, &contract, &dry.site_id, plan, chunk).await?;
            if step == 0 {
                break;
            }
            converted += step;
        }
        if converted > 0 {
            if let (Some(min_ts), Some(max_ts)) = (plan.min_ts, plan.max_ts) {
                bump_data_revision(tx, &dry.site_id, &plan.openfdd_key, min_ts, max_ts).await?;
            }
            let finished = Utc::now();
            record_ledger(tx, &dry.site_id, plan, started, finished).await?;
            result.rows_converted += converted;
            result.series_converted += 1;
        } else {
            result.series_skipped += 1;
        }
    }
    Ok(result)
}

pub async fn ensure_si_cutover_schema(pool: &sqlx::PgPool) -> Result<(), sqlx::Error> {
    for stmt in SCHEMA_SQL.split(';') {
        let sql = stmt.trim();
        if sql.is_empty() {
            continue;
        }
        sqlx::query(sql).execute(pool).await?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checksum_stable() {
        let a = series_checksum("S1", "AHU_1.oa_t", "degF", "degC", 10, None, None);
        let b = series_checksum("S1", "AHU_1.oa_t", "degF", "degC", 10, None, None);
        assert_eq!(a, b);
        assert_ne!(
            a,
            series_checksum("S1", "AHU_1.oa_t", "degF", "degC", 11, None, None)
        );
    }

    #[test]
    fn contract_loads() {
        contract().expect("embedded contract");
    }
}
