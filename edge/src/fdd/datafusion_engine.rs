//! Apache Arrow + DataFusion SQL FDD execution (no PyArrow).

use crate::fdd::confirmation::oa_t_out_of_range;
use crate::historian::bench_telemetry::TelemetrySample;
use arrow::array::{Array, BooleanArray, Float64Array, RecordBatch, TimestampMicrosecondArray};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use chrono::{DateTime, TimeZone, Utc};
use datafusion::prelude::SessionContext;
use std::sync::Arc;

pub const TABLE_NAME: &str = "bench5007_telemetry";

#[derive(Clone, Debug)]
pub struct RuleLimits {
    pub high_limit: f64,
    pub low_limit: f64,
}

#[derive(Clone, Debug)]
pub struct DataFusionRunMeta {
    pub engine: String,
    pub table: String,
    pub sql: String,
    pub target_partitions: usize,
    pub batch_rows: usize,
    pub batch_columns: usize,
    pub execution_path: String,
}

#[derive(Clone, Debug)]
pub struct FaultRawRow {
    pub ts: DateTime<Utc>,
    pub point_value: f64,
    pub fault_raw: bool,
}

pub fn target_partitions() -> usize {
    std::env::var("OPENFDD_DATAFUSION_TARGET_PARTITIONS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or_else(|| std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4))
}

pub async fn run_fault_raw_sql(
    batch: RecordBatch,
    column: &str,
    limits: &RuleLimits,
) -> Result<(RecordBatch, DataFusionRunMeta), String> {
    let partitions = target_partitions();
    let config = datafusion::prelude::SessionConfig::new()
        .with_target_partitions(partitions);
    let ctx = SessionContext::new_with_config(config);
    ctx.register_batch(TABLE_NAME, batch.clone())
        .map_err(|e| e.to_string())?;

    let sql = format!(
        "SELECT ts, {column} AS point_value, \
         CASE WHEN {column} > {} OR {column} < {} THEN true ELSE false END AS fault_raw \
         FROM {TABLE_NAME} WHERE {column} IS NOT NULL ORDER BY ts",
        limits.high_limit, limits.low_limit
    );

    let df = ctx.sql(&sql).await.map_err(|e| e.to_string())?;
    let batches = df.collect().await.map_err(|e| e.to_string())?;
    let out = batches.into_iter().next().ok_or("DataFusion returned no batches")?;

    let meta = DataFusionRunMeta {
        engine: "Apache Arrow + DataFusion SQL (Rust)".to_string(),
        table: TABLE_NAME.to_string(),
        sql,
        target_partitions: partitions,
        batch_rows: batch.num_rows(),
        batch_columns: batch.num_columns(),
        execution_path: "RecordBatch -> SessionContext::register_batch -> DataFusion SQL".to_string(),
    };

    Ok((out, meta))
}

pub fn rows_from_fault_batch(batch: &RecordBatch) -> Result<Vec<FaultRawRow>, String> {
    if batch.num_rows() == 0 {
        return Ok(Vec::new());
    }
    let ts_arr = batch
        .column(0)
        .as_any()
        .downcast_ref::<TimestampMicrosecondArray>()
        .ok_or("missing ts column")?;
    let val_arr = batch
        .column(1)
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or("missing point_value column")?;
    let raw_arr = batch
        .column(2)
        .as_any()
        .downcast_ref::<BooleanArray>()
        .ok_or("missing fault_raw column")?;

    let mut rows = Vec::with_capacity(batch.num_rows());
    for i in 0.. batch.num_rows() {
        if val_arr.is_null(i) {
            continue;
        }
        let micros = ts_arr.value(i);
        let ts = DateTime::from_timestamp_micros(micros).ok_or("invalid timestamp")?;
        rows.push(FaultRawRow {
            ts,
            point_value: val_arr.value(i),
            fault_raw: raw_arr.value(i),
        });
    }
    Ok(rows)
}

pub fn evaluate_rule_on_samples(
    samples: &[TelemetrySample],
    point_column: &str,
    limits: &RuleLimits,
) -> Result<Vec<FaultRawRow>, String> {
    let batch = crate::historian::bench_telemetry::samples_to_record_batch(samples)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| e.to_string())?;
    let (out_batch, _meta) = runtime
        .block_on(run_fault_raw_sql(batch, point_column, limits))?;
    rows_from_fault_batch(&out_batch)
}

pub fn sanity_check_limits(value: f64, limits: &RuleLimits) -> bool {
    oa_t_out_of_range(value, limits.high_limit, limits.low_limit)
}

pub fn fault_result_schema() -> Schema {
    Schema::new(vec![
        Field::new(
            "ts",
            DataType::Timestamp(TimeUnit::Microsecond, None),
            false,
        ),
        Field::new("point_value", DataType::Float64, true),
        Field::new("fault_raw", DataType::Boolean, false),
    ])
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::historian::bench_telemetry::TelemetrySample;

    fn sample(minute: i64, oa_t: f64) -> TelemetrySample {
        TelemetrySample {
            ts: Utc::now() + chrono::Duration::minutes(minute),
            device_instance: 5007,
            oa_t: Some(oa_t),
            oa_h: None,
            duct_t: None,
            stat_zn_t: None,
            source: "simulated".to_string(),
            poll_cycle_id: minute as u64,
        }
    }

    #[test]
    fn datafusion_returns_fault_column() {
        let limits = RuleLimits {
            high_limit: 50.0,
            low_limit: -50.0,
        };
        let rows = evaluate_rule_on_samples(&[sample(0, 70.0)], "oa_t", &limits).unwrap();
        assert_eq!(rows.len(), 1);
        assert!(rows[0].fault_raw);
    }

    #[test]
    fn datafusion_no_fault_for_wide_limits() {
        let limits = RuleLimits {
            high_limit: 150.0,
            low_limit: -50.0,
        };
        let rows = evaluate_rule_on_samples(&[sample(0, 70.0)], "oa_t", &limits).unwrap();
        assert!(!rows[0].fault_raw);
    }
}
