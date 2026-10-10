use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use datafusion::prelude::*;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct QueryResult {
    pub row_count: usize,
    pub columns: Vec<String>,
    pub rows: Vec<serde_json::Value>,
    pub elapsed_ms: u128,
}

pub async fn register_parquet_tree(ctx: &SessionContext, parquet_root: &Path) -> Result<usize> {
    let glob = parquet_root.join("**/*.parquet");
    let glob_str = glob.to_string_lossy().to_string();
    ctx.register_parquet("history", glob_str.as_str(), ParquetReadOptions::default())
        .await
        .with_context(|| format!("register history from {}", glob_str))?;
    Ok(1)
}

/// Register a `weather` table for weather-referencing rules (e.g. OAT-METEO).
///
/// Preference order (OFDD-068):
/// 1. `parquet_root/weather/**/*.parquet` sidecar, when present.
/// 2. Fallback SQL view over `history` rows whose canonical kind is `weather`
///    (`equipment_types.json`, or an `equipment_type` column). Liberty CSV
///    packages land weather in history rather than a sidecar. Id substrings
///    (`weather`, `meteo`, `oat`) are not a kind.
///
/// Returns `true` when a `weather` relation was registered by either path.
/// Register utility CSV tables from `workspace/data/csv_buildings/<building_id>/utilities/`.
///
/// Tables: `utility_monthly`, `utility_interval`, `bas_submeter` (empty view when missing).
pub async fn register_utility_if_present(ctx: &SessionContext, building_id: &str) -> Result<bool> {
    let workspace = std::env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"));
    let util_root = workspace
        .join("data")
        .join("csv_buildings")
        .join(building_id)
        .join("utilities");
    let mut registered = false;

    async fn register_csv_table(ctx: &SessionContext, table: &str, path: &Path) -> Result<bool> {
        if !path.is_file() {
            return Ok(false);
        }
        // DataFusion product sessions do not ship the SQL `read_csv` table
        // function — use the typed register_csv API (Wave I lakeside-read-csv).
        let path_str = path.to_string_lossy().replace('\\', "/");
        ctx.register_csv(
            table,
            path_str.as_str(),
            CsvReadOptions::new().has_header(true),
        )
        .await
        .with_context(|| format!("register_csv {table} from {path_str}"))?;
        Ok(ctx.table(table).await.is_ok())
    }

    if register_csv_table(
        ctx,
        "utility_monthly",
        &util_root.join("electric/monthly_bills.csv"),
    )
    .await?
    {
        registered = true;
    }
    if register_csv_table(
        ctx,
        "utility_interval",
        &util_root.join("electric/utility_interval_15m.csv"),
    )
    .await?
    {
        registered = true;
    }
    if register_csv_table(
        ctx,
        "bas_submeter",
        &util_root.join("electric/bas_submeter_interval.csv"),
    )
    .await?
    {
        registered = true;
    }

    ensure_empty_utility_views(ctx).await?;
    Ok(registered)
}

/// Register zero-row utility relations when optional CSVs are absent so UTIL-* rules
/// plan cleanly (0 fault hours) instead of failing the registry run.
async fn ensure_empty_utility_views(ctx: &SessionContext) -> Result<()> {
    let views: [(&str, &str); 3] = [
        (
            "utility_monthly",
            "CREATE OR REPLACE VIEW utility_monthly AS \
            SELECT CAST(NULL AS VARCHAR) AS account, \
                   CAST(NULL AS VARCHAR) AS billing_period, \
                   CAST(NULL AS DOUBLE) AS kwh, \
                   CAST(NULL AS DOUBLE) AS demand_kw \
            WHERE 1=0",
        ),
        (
            "utility_interval",
            "CREATE OR REPLACE VIEW utility_interval AS \
            SELECT CAST(NULL AS VARCHAR) AS timestamp_utc, \
                   CAST(NULL AS DOUBLE) AS kwh \
            WHERE 1=0",
        ),
        (
            "bas_submeter",
            "CREATE OR REPLACE VIEW bas_submeter AS \
            SELECT CAST(NULL AS VARCHAR) AS timestamp_utc, \
                   CAST(NULL AS DOUBLE) AS kwh \
            WHERE 1=0",
        ),
    ];
    for (name, ddl) in views {
        if ctx.table(name).await.is_err() {
            ctx.sql(ddl)
                .await
                .with_context(|| format!("register empty utility view {name}"))?;
        }
    }
    Ok(())
}

pub async fn register_weather_if_present(
    ctx: &SessionContext,
    parquet_root: &Path,
) -> Result<bool> {
    register_weather_for_building(ctx, parquet_root, None).await
}

/// Same as [`register_weather_if_present`], limited to one building's type map.
pub async fn register_weather_for_building(
    ctx: &SessionContext,
    parquet_root: &Path,
    building_id: Option<&str>,
) -> Result<bool> {
    let weather_dir = parquet_root.join("weather");
    if weather_dir.is_dir() {
        let glob = weather_dir.join("**/*.parquet");
        let glob_str = glob.to_string_lossy().to_string();
        if ctx
            .register_parquet("weather", glob_str.as_str(), ParquetReadOptions::default())
            .await
            .is_ok()
        {
            return Ok(true);
        }
    }
    register_weather_view_from_history(ctx, parquet_root, building_id).await
}

/// Recognized weather stamp. Matches `equipment_types::canonical_kind` for `weather`.
fn stamp_is_weather(raw: &str) -> bool {
    let key: String = raw
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect();
    key == "weather"
}

fn type_map_paths(parquet_root: &Path, building_id: Option<&str>) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) {
        if !bid.contains("..") && !bid.contains('/') && !bid.contains('\\') {
            paths.push(
                parquet_root
                    .join(format!("building={bid}"))
                    .join("equipment_types.json"),
            );
            paths.push(parquet_root.join("equipment_types.json"));
        }
        return paths;
    }
    paths.push(parquet_root.join("equipment_types.json"));
    if let Ok(rd) = std::fs::read_dir(parquet_root) {
        for ent in rd.flatten() {
            let path = ent.path();
            if path.is_dir() {
                paths.push(path.join("equipment_types.json"));
            }
        }
    }
    paths
}

fn weather_ids_from_type_files(parquet_root: &Path, building_id: Option<&str>) -> Vec<String> {
    let mut ids = BTreeSet::new();
    for path in type_map_paths(parquet_root, building_id) {
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        let Ok(map) = serde_json::from_str::<serde_json::Map<String, serde_json::Value>>(&text)
        else {
            continue;
        };
        for (id, value) in map {
            let Some(stamp) = value.as_str() else {
                continue;
            };
            if stamp_is_weather(stamp) {
                ids.insert(id);
            }
        }
    }
    ids.into_iter().collect()
}

async fn weather_ids_from_history_column(ctx: &SessionContext) -> Vec<String> {
    let Ok(table) = ctx.table("history").await else {
        return Vec::new();
    };
    let Some(col) = table.schema().fields().iter().find_map(|f| {
        let name = f.name();
        if name.eq_ignore_ascii_case("equipment_type") || name.eq_ignore_ascii_case("equiptype") {
            Some(name.clone())
        } else {
            None
        }
    }) else {
        return Vec::new();
    };
    if !col.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Vec::new();
    }
    let sql = format!(
        "SELECT DISTINCT equipment_id, {col} AS equipment_type FROM history WHERE {col} IS NOT NULL"
    );
    let Ok(result) = run_sql(ctx, &sql).await else {
        return Vec::new();
    };
    let mut ids = Vec::new();
    for row in result.rows {
        let eq = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let stamp = row
            .get("equipment_type")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if !eq.is_empty() && stamp_is_weather(stamp) {
            ids.push(eq.to_string());
        }
    }
    ids
}

/// Register a `weather` view from history rows whose canonical kind is weather.
/// Returns `false` when `history` is missing or no weather stamp is present.
async fn register_weather_view_from_history(
    ctx: &SessionContext,
    parquet_root: &Path,
    building_id: Option<&str>,
) -> Result<bool> {
    if ctx.table("history").await.is_err() {
        return Ok(false);
    }
    let mut ids = weather_ids_from_type_files(parquet_root, building_id);
    ids.extend(weather_ids_from_history_column(ctx).await);
    ids.sort();
    ids.dedup();
    if ids.is_empty() {
        return Ok(false);
    }
    let list = ids
        .iter()
        .map(|id| format!("'{}'", id.replace('\'', "''")))
        .collect::<Vec<_>>()
        .join(", ");
    let create = format!(
        "CREATE OR REPLACE VIEW weather AS SELECT * FROM history WHERE equipment_id IN ({list})"
    );
    match ctx.sql(&create).await {
        Ok(df) => {
            let _ = df.collect().await;
            Ok(ctx.table("weather").await.is_ok())
        }
        Err(_) => Ok(false),
    }
}

/// Execute SQL and materialize JSON rows with a hard JSON-side byte budget.
///
/// Streams Arrow batches (no unbounded `collect()`). Fail-closed when the
/// measured JSON payload would exceed `OPENFDD_RESULT_MAX_BYTES` (#1179).
/// Interactive callers that only need Arrow should prefer [`run_sql_bounded`]
/// or `crate::query::stream_sql`.
pub async fn run_sql(ctx: &SessionContext, sql: &str) -> Result<QueryResult> {
    run_sql_with_cancel(ctx, sql, None).await
}

/// Execute SQL with an optional explicit cancel token raced against stream waits
/// (Soft-OPEN 370 T1b / M70-02). Dropping the stream on cancel releases engine
/// reservations; ambient `memory_abort_requested` remains a secondary fallback.
pub async fn run_sql_with_cancel(
    ctx: &SessionContext,
    sql: &str,
    cancel: Option<std::sync::Arc<std::sync::atomic::AtomicBool>>,
) -> Result<QueryResult> {
    use futures::FutureExt;
    use futures::StreamExt;
    use std::sync::atomic::Ordering;

    let cancelled = || {
        cancel.as_ref().is_some_and(|c| c.load(Ordering::SeqCst))
            || fdd_resources::memory_abort_requested()
    };
    if cancelled() {
        anyhow::bail!("SQL cancelled by in-flight memory watchdog (OPENFDD memory abort policy)");
    }

    let started = std::time::Instant::now();
    let max_bytes = crate::query::query_stage_max_bytes_from_env()?;
    let mut stream = crate::query::stream_sql(ctx, sql).await?;
    let mut rows = Vec::new();
    let mut columns = Vec::new();
    let mut json_bytes = 0usize;
    loop {
        if cancelled() {
            drop(stream);
            anyhow::bail!(
                "SQL cancelled by in-flight memory watchdog (OPENFDD memory abort policy)"
            );
        }
        let next = {
            let wait = stream.next();
            tokio::pin!(wait);
            tokio::select! {
                biased;
                _ = async {
                    loop {
                        if cancelled() {
                            break;
                        }
                        tokio::time::sleep(std::time::Duration::from_millis(25)).await;
                    }
                }.fuse() => {
                    drop(stream);
                    anyhow::bail!(
                        "SQL cancelled by in-flight memory watchdog (OPENFDD memory abort policy)"
                    );
                }
                item = &mut wait => item,
            }
        };
        let Some(next) = next else {
            break;
        };
        let batch = next?;
        let schema = batch.schema();
        if columns.is_empty() {
            columns = schema.fields().iter().map(|f| f.name().clone()).collect();
        }
        for row_idx in 0..batch.num_rows() {
            if cancelled() {
                drop(stream);
                anyhow::bail!(
                    "SQL cancelled by in-flight memory watchdog (OPENFDD memory abort policy)"
                );
            }
            let mut obj = serde_json::Map::new();
            for (col_idx, field) in schema.fields().iter().enumerate() {
                let col = batch.column(col_idx);
                let val = format_cell(col, row_idx);
                obj.insert(field.name().clone(), val);
            }
            let value = serde_json::Value::Object(obj);
            let encoded = serde_json::to_vec(&value).unwrap_or_default();
            json_bytes = json_bytes.saturating_add(encoded.len());
            if json_bytes > max_bytes {
                anyhow::bail!(
                    "SQL JSON result exceeds byte budget of {max_bytes} (OPENFDD_RESULT_MAX_BYTES); narrow the query — refusing silent truncation"
                );
            }
            rows.push(value);
        }
    }
    Ok(QueryResult {
        row_count: rows.len(),
        columns,
        rows,
        elapsed_ms: started.elapsed().as_millis(),
    })
}

/// Execute SQL with a hard materialized-row limit for interactive callers.
pub async fn run_sql_bounded(
    ctx: &SessionContext,
    sql: &str,
    max_rows: usize,
) -> Result<QueryResult> {
    let started = std::time::Instant::now();
    let batches = crate::query::collect_sql_bounded(ctx, sql, max_rows).await?;
    Ok(query_result_from_batches(&batches, started))
}

/// Read a SQL file and execute it through the compatibility unbounded path.
pub async fn run_sql_file(ctx: &SessionContext, path: &Path) -> Result<QueryResult> {
    let sql = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    run_sql(ctx, &sql).await
}

/// Read a SQL file and execute it with a hard materialized-row limit.
pub async fn run_sql_file_bounded(
    ctx: &SessionContext,
    path: &Path,
    max_rows: usize,
) -> Result<QueryResult> {
    let sql = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    run_sql_bounded(ctx, &sql, max_rows).await
}

/// Convert collected Arrow batches into the stable JSON-facing query result.
fn query_result_from_batches(
    batches: &[datafusion::arrow::record_batch::RecordBatch],
    started: std::time::Instant,
) -> QueryResult {
    let mut rows = Vec::new();
    let mut columns = Vec::new();
    for batch in batches {
        let schema = batch.schema();
        if columns.is_empty() {
            columns = schema.fields().iter().map(|f| f.name().clone()).collect();
        }
        for row_idx in 0..batch.num_rows() {
            let mut obj = serde_json::Map::new();
            for (col_idx, field) in schema.fields().iter().enumerate() {
                let col = batch.column(col_idx);
                let val = format_cell(col, row_idx);
                obj.insert(field.name().clone(), val);
            }
            rows.push(serde_json::Value::Object(obj));
        }
    }
    QueryResult {
        row_count: rows.len(),
        columns,
        rows,
        elapsed_ms: started.elapsed().as_millis(),
    }
}

fn format_cell(col: &datafusion::arrow::array::ArrayRef, idx: usize) -> serde_json::Value {
    use chrono::{TimeZone, Utc};
    use datafusion::arrow::array::*;
    use datafusion::arrow::datatypes::{DataType, TimeUnit};
    if col.is_null(idx) {
        return serde_json::Value::Null;
    }
    match col.data_type() {
        DataType::Utf8 => {
            let a = col.as_any().downcast_ref::<StringArray>().unwrap();
            serde_json::Value::String(a.value(idx).to_string())
        }
        DataType::Utf8View => {
            let a = col.as_any().downcast_ref::<StringViewArray>().unwrap();
            serde_json::Value::String(a.value(idx).to_string())
        }
        DataType::LargeUtf8 => {
            let a = col.as_any().downcast_ref::<LargeStringArray>().unwrap();
            serde_json::Value::String(a.value(idx).to_string())
        }
        DataType::Float64 => {
            let a = col.as_any().downcast_ref::<Float64Array>().unwrap();
            serde_json::json!(a.value(idx))
        }
        DataType::Float32 => {
            let a = col.as_any().downcast_ref::<Float32Array>().unwrap();
            serde_json::json!(a.value(idx) as f64)
        }
        DataType::Int64 => {
            let a = col.as_any().downcast_ref::<Int64Array>().unwrap();
            serde_json::json!(a.value(idx))
        }
        DataType::Int32 => {
            let a = col.as_any().downcast_ref::<Int32Array>().unwrap();
            serde_json::json!(a.value(idx))
        }
        DataType::Boolean => {
            let a = col.as_any().downcast_ref::<BooleanArray>().unwrap();
            serde_json::json!(a.value(idx))
        }
        DataType::Timestamp(unit, _) => {
            let nanos: i64 = match unit {
                TimeUnit::Second => col
                    .as_any()
                    .downcast_ref::<TimestampSecondArray>()
                    .map(|a| a.value(idx).saturating_mul(1_000_000_000))
                    .unwrap_or(0),
                TimeUnit::Millisecond => col
                    .as_any()
                    .downcast_ref::<TimestampMillisecondArray>()
                    .map(|a| a.value(idx).saturating_mul(1_000_000))
                    .unwrap_or(0),
                TimeUnit::Microsecond => col
                    .as_any()
                    .downcast_ref::<TimestampMicrosecondArray>()
                    .map(|a| a.value(idx).saturating_mul(1_000))
                    .unwrap_or(0),
                TimeUnit::Nanosecond => col
                    .as_any()
                    .downcast_ref::<TimestampNanosecondArray>()
                    .map(|a| a.value(idx))
                    .unwrap_or(0),
            };
            let secs = nanos.div_euclid(1_000_000_000);
            let nsec = nanos.rem_euclid(1_000_000_000) as u32;
            let dt = Utc
                .timestamp_opt(secs, nsec)
                .single()
                .unwrap_or_else(|| Utc.timestamp_opt(0, 0).unwrap());
            serde_json::Value::String(dt.to_rfc3339())
        }
        DataType::Date32 => {
            let a = col.as_any().downcast_ref::<Date32Array>().unwrap();
            let days = i64::from(a.value(idx));
            let dt = Utc
                .timestamp_opt(days.saturating_mul(86_400), 0)
                .single()
                .unwrap_or_else(|| Utc.timestamp_opt(0, 0).unwrap());
            serde_json::Value::String(dt.date_naive().to_string())
        }
        _ => {
            // Last resort: avoid Arrow Debug dumps (e.g. PrimitiveArray<…>) in JSON.
            serde_json::Value::Null
        }
    }
}

#[cfg(test)]
mod utility_csv_tests {
    use super::*;
    use std::io::Write;
    use std::sync::{Mutex, MutexGuard};

    static WORKSPACE_LOCK: Mutex<()> = Mutex::new(());

    struct WorkspaceGuard {
        _lock: MutexGuard<'static, ()>,
        prev: Option<String>,
    }

    impl WorkspaceGuard {
        fn set(path: &Path) -> Self {
            let lock = WORKSPACE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
            let prev = std::env::var("OPENFDD_WORKSPACE").ok();
            std::env::set_var("OPENFDD_WORKSPACE", path);
            Self { _lock: lock, prev }
        }
    }

    impl Drop for WorkspaceGuard {
        fn drop(&mut self) {
            match &self.prev {
                Some(v) => std::env::set_var("OPENFDD_WORKSPACE", v),
                None => std::env::remove_var("OPENFDD_WORKSPACE"),
            }
        }
    }

    #[tokio::test]
    async fn register_utility_interval_empty_view_when_csv_missing() {
        let tmp = tempfile::tempdir().unwrap();
        let _ws = WorkspaceGuard::set(tmp.path());
        let ctx = SessionContext::new();
        register_utility_if_present(&ctx, "NO_UTIL_CSV")
            .await
            .expect("register utility placeholders");
        assert!(ctx.table("utility_interval").await.is_ok());
        let df = ctx.sql("SELECT * FROM utility_interval").await.unwrap();
        let batches = df.collect().await.unwrap();
        assert!(batches.iter().all(|b| b.num_rows() == 0));
    }

    #[tokio::test]
    async fn register_utility_csv_without_read_csv_sql() {
        let tmp = tempfile::tempdir().unwrap();
        let util = tmp
            .path()
            .join("data/csv_buildings/TEST_BLDG/utilities/electric");
        std::fs::create_dir_all(&util).unwrap();
        let mut f = std::fs::File::create(util.join("monthly_bills.csv")).unwrap();
        writeln!(f, "account,billing_period,kwh,demand_kw").unwrap();
        writeln!(f, "a1,2026-01,100,10").unwrap();
        let _ws = WorkspaceGuard::set(tmp.path());
        let ctx = SessionContext::new();
        let ok = register_utility_if_present(&ctx, "TEST_BLDG")
            .await
            .expect("register utility");
        assert!(
            ok,
            "expected utility_monthly CSV registration under {}",
            util.display()
        );
        assert!(ctx.table("utility_monthly").await.is_ok());
    }
}
