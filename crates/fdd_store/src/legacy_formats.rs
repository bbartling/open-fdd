//! Bounded readers for legacy historian formats eligible for H6 migration.
//!
//! Path identity is established by `migration`; this module only converts file
//! contents into Arrow batches. Ambiguous timestamps, mixed JSON scalar types,
//! nested JSON values, and non-timestamp IPC schemas fail closed rather than
//! silently dropping or inventing data.

use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use arrow::array::{
    ArrayRef, BooleanArray, Float64Array, StringArray, TimestampNanosecondArray,
};
use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use arrow::ipc::reader::FileReader;
use arrow::record_batch::RecordBatch;
use chrono::{DateTime, NaiveDateTime, Utc};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use serde_json::{Map, Value};

use crate::migration::LegacyHistorianFormat;
use crate::parquet_parts::DEFAULT_ROW_GROUP_ROWS;

const JSON_BATCH_ROWS: usize = 5_000;

pub(crate) fn for_each_legacy_batch<F>(
    path: &Path,
    format: LegacyHistorianFormat,
    mut on_batch: F,
) -> Result<u64>
where
    F: FnMut(RecordBatch) -> Result<()>,
{
    match format {
        LegacyHistorianFormat::Parquet => for_each_parquet_batch(path, &mut on_batch),
        LegacyHistorianFormat::Jsonl => for_each_jsonl_batch(path, &mut on_batch),
        LegacyHistorianFormat::Feather => for_each_ipc_batch(path, &mut on_batch),
    }
}

fn for_each_parquet_batch<F>(path: &Path, on_batch: &mut F) -> Result<u64>
where
    F: FnMut(RecordBatch) -> Result<()>,
{
    let file =
        fs::File::open(path).with_context(|| format!("open legacy Parquet {}", path.display()))?;
    let reader = ParquetRecordBatchReaderBuilder::try_new(file)
        .context("read legacy Parquet metadata")?
        .with_batch_size(DEFAULT_ROW_GROUP_ROWS)
        .build()
        .context("build legacy Parquet batch reader")?;
    let mut rows = 0u64;
    for batch in reader {
        let batch = batch.context("read legacy Parquet batch")?;
        rows = checked_add_rows(rows, batch.num_rows())?;
        on_batch(batch)?;
    }
    Ok(rows)
}

fn for_each_ipc_batch<F>(path: &Path, on_batch: &mut F) -> Result<u64>
where
    F: FnMut(RecordBatch) -> Result<()>,
{
    let file = fs::File::open(path)
        .with_context(|| format!("open legacy Arrow/Feather {}", path.display()))?;
    let reader = FileReader::try_new(file, None).context("open legacy Arrow IPC/Feather file")?;
    let mut rows = 0u64;
    for batch in reader {
        let batch = normalize_ipc_timestamp(batch.context("read legacy Arrow IPC batch")?)?;
        rows = checked_add_rows(rows, batch.num_rows())?;
        on_batch(batch)?;
    }
    Ok(rows)
}

fn normalize_ipc_timestamp(batch: RecordBatch) -> Result<RecordBatch> {
    let schema = batch.schema();
    let timestamp_utc = schema.index_of("timestamp_utc").ok();
    let timestamp = schema.index_of("timestamp").ok();
    match (timestamp_utc, timestamp) {
        (Some(_), Some(_)) => bail!(
            "legacy Arrow IPC cannot contain both timestamp and timestamp_utc"
        ),
        (Some(index), None) => {
            ensure_arrow_timestamp(batch.column(index).data_type())?;
            Ok(batch)
        }
        (None, Some(index)) => {
            ensure_arrow_timestamp(batch.column(index).data_type())?;
            let fields = schema
                .fields()
                .iter()
                .enumerate()
                .map(|(field_index, field)| {
                    if field_index == index {
                        Arc::new(Field::new(
                            "timestamp_utc",
                            field.data_type().clone(),
                            field.is_nullable(),
                        ))
                    } else {
                        field.clone()
                    }
                })
                .collect::<Vec<_>>();
            Ok(RecordBatch::try_new(
                Arc::new(Schema::new(fields)),
                batch.columns().to_vec(),
            )?)
        }
        (None, None) => bail!("legacy Arrow IPC requires timestamp or timestamp_utc"),
    }
}

fn ensure_arrow_timestamp(data_type: &DataType) -> Result<()> {
    if matches!(data_type, DataType::Timestamp(_, _)) {
        return Ok(());
    }
    bail!("legacy Arrow IPC timestamp must be an Arrow Timestamp, got {data_type:?}")
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum JsonKind {
    Float64,
    Utf8,
    Boolean,
}

fn for_each_jsonl_batch<F>(path: &Path, on_batch: &mut F) -> Result<u64>
where
    F: FnMut(RecordBatch) -> Result<()>,
{
    let schema = infer_json_schema(path)?;
    let file =
        fs::File::open(path).with_context(|| format!("open legacy JSONL {}", path.display()))?;
    let reader = BufReader::new(file);
    let mut pending = Vec::with_capacity(JSON_BATCH_ROWS);
    let mut rows = 0u64;

    for (line_index, line) in reader.lines().enumerate() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let row = parse_json_object(&line, line_index + 1)?;
        validate_json_timestamp(&row, line_index + 1)?;
        pending.push(row);
        if pending.len() >= JSON_BATCH_ROWS {
            rows = checked_add_rows(rows, pending.len())?;
            on_batch(json_batch(&schema, &pending)?)?;
            pending.clear();
        }
    }
    if !pending.is_empty() {
        rows = checked_add_rows(rows, pending.len())?;
        on_batch(json_batch(&schema, &pending)?)?;
    }
    Ok(rows)
}

fn infer_json_schema(path: &Path) -> Result<BTreeMap<String, JsonKind>> {
    let file =
        fs::File::open(path).with_context(|| format!("open legacy JSONL {}", path.display()))?;
    let reader = BufReader::new(file);
    let mut schema = BTreeMap::new();
    for (line_index, line) in reader.lines().enumerate() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let row = parse_json_object(&line, line_index + 1)?;
        validate_json_timestamp(&row, line_index + 1)?;
        for (name, value) in &row {
            if matches!(name.as_str(), "timestamp" | "timestamp_utc") || value.is_null() {
                continue;
            }
            let kind = match value {
                Value::Number(number) if number.as_f64().is_some() => JsonKind::Float64,
                Value::String(_) => JsonKind::Utf8,
                Value::Bool(_) => JsonKind::Boolean,
                Value::Number(_) => bail!(
                    "legacy JSONL numeric value is outside Float64 range at line {}",
                    line_index + 1
                ),
                Value::Array(_) | Value::Object(_) => bail!(
                    "legacy JSONL nested value for {name} is not supported at line {}",
                    line_index + 1
                ),
                Value::Null => continue,
            };
            if let Some(existing) = schema.get(name) {
                if *existing != kind {
                    bail!(
                        "legacy JSONL field {name} changes scalar type at line {}",
                        line_index + 1
                    );
                }
            } else {
                schema.insert(name.clone(), kind);
            }
        }
    }
    Ok(schema)
}

fn parse_json_object(line: &str, line_number: usize) -> Result<Map<String, Value>> {
    let value: Value = serde_json::from_str(line)
        .with_context(|| format!("parse legacy JSONL line {line_number}"))?;
    value
        .as_object()
        .cloned()
        .ok_or_else(|| anyhow!("legacy JSONL line {line_number} must be an object"))
}

fn validate_json_timestamp(row: &Map<String, Value>, line_number: usize) -> Result<i64> {
    let timestamp_utc =
        json_timestamp_value(row.get("timestamp_utc"), "timestamp_utc", line_number)?;
    let timestamp = json_timestamp_value(row.get("timestamp"), "timestamp", line_number)?;
    match (timestamp_utc, timestamp) {
        (Some(left), Some(right)) if left != right => {
            bail!("legacy JSONL timestamp and timestamp_utc conflict at line {line_number}")
        }
        (Some(value), _) | (_, Some(value)) => Ok(value),
        (None, None) => bail!("legacy JSONL line {line_number} has no timestamp"),
    }
}

fn json_timestamp_value(
    value: Option<&Value>,
    name: &str,
    line_number: usize,
) -> Result<Option<i64>> {
    let Some(value) = value else {
        return Ok(None);
    };
    let raw = value
        .as_str()
        .ok_or_else(|| anyhow!("legacy JSONL {name} must be a string at line {line_number}"))?;
    parse_timestamp_nanos(raw)
        .map(Some)
        .ok_or_else(|| anyhow!("invalid legacy JSONL {name} at line {line_number}"))
}

fn parse_timestamp_nanos(raw: &str) -> Option<i64> {
    let raw = raw.trim();
    if raw.is_empty() {
        return None;
    }
    if let Ok(timestamp) = DateTime::parse_from_rfc3339(raw) {
        return timestamp.with_timezone(&Utc).timestamp_nanos_opt();
    }
    for format in [
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ] {
        if let Ok(timestamp) = NaiveDateTime::parse_from_str(raw, format) {
            return DateTime::<Utc>::from_naive_utc_and_offset(timestamp, Utc).timestamp_nanos_opt();
        }
    }
    None
}

fn json_batch(
    schema: &BTreeMap<String, JsonKind>,
    rows: &[Map<String, Value>],
) -> Result<RecordBatch> {
    let timestamps = rows
        .iter()
        .enumerate()
        .map(|(index, row)| validate_json_timestamp(row, index + 1))
        .collect::<Result<Vec<_>>>()?;
    let mut fields = vec![Field::new(
        "timestamp_utc",
        DataType::Timestamp(TimeUnit::Nanosecond, None),
        false,
    )];
    let mut arrays: Vec<ArrayRef> = vec![Arc::new(TimestampNanosecondArray::from(timestamps))];

    for (name, kind) in schema {
        match kind {
            JsonKind::Float64 => {
                fields.push(Field::new(name, DataType::Float64, true));
                let values = rows
                    .iter()
                    .map(|row| match row.get(name) {
                        None | Some(Value::Null) => Ok(None),
                        Some(Value::Number(number)) => number.as_f64().map(Some).ok_or_else(|| {
                            anyhow!("legacy JSONL field {name} is outside Float64 range")
                        }),
                        Some(_) => bail!("legacy JSONL field {name} changed scalar type"),
                    })
                    .collect::<Result<Vec<_>>>()?;
                arrays.push(Arc::new(Float64Array::from(values)));
            }
            JsonKind::Utf8 => {
                fields.push(Field::new(name, DataType::Utf8, true));
                let values = rows
                    .iter()
                    .map(|row| match row.get(name) {
                        None | Some(Value::Null) => Ok(None),
                        Some(Value::String(value)) => Ok(Some(value.as_str())),
                        Some(_) => bail!("legacy JSONL field {name} changed scalar type"),
                    })
                    .collect::<Result<Vec<_>>>()?;
                arrays.push(Arc::new(StringArray::from(values)));
            }
            JsonKind::Boolean => {
                fields.push(Field::new(name, DataType::Boolean, true));
                let values = rows
                    .iter()
                    .map(|row| match row.get(name) {
                        None | Some(Value::Null) => Ok(None),
                        Some(Value::Bool(value)) => Ok(Some(*value)),
                        Some(_) => bail!("legacy JSONL field {name} changed scalar type"),
                    })
                    .collect::<Result<Vec<_>>>()?;
                arrays.push(Arc::new(BooleanArray::from(values)));
            }
        }
    }

    Ok(RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)?)
}

fn checked_add_rows(current: u64, rows: usize) -> Result<u64> {
    current
        .checked_add(u64::try_from(rows).context("legacy batch row count overflow")?)
        .ok_or_else(|| anyhow!("legacy source row count overflow"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow::array::Array;
    use arrow::ipc::writer::FileWriter;
    use tempfile::TempDir;

    #[test]
    fn jsonl_conversion_preserves_scalar_columns_and_normalizes_timestamp() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("history.jsonl");
        fs::write(
            &path,
            concat!(
                "{\"timestamp\":\"2026-08-20T12:00:00Z\",\"equipment_id\":\"AHU_1\",\"sat\":55.0,\"source\":\"bacnet\",\"is_simulated\":false}\n",
                "{\"timestamp\":\"2026-08-20T12:05:00Z\",\"equipment_id\":\"AHU_1\",\"sat\":56.0,\"source\":\"bacnet\",\"is_simulated\":false}\n"
            ),
        )
        .unwrap();
        let mut batches = Vec::new();
        let rows = for_each_legacy_batch(&path, LegacyHistorianFormat::Jsonl, |batch| {
            batches.push(batch);
            Ok(())
        })
        .unwrap();
        assert_eq!(rows, 2);
        assert_eq!(batches.len(), 1);
        let batch = &batches[0];
        assert_eq!(batch.num_rows(), 2);
        assert!(matches!(
            batch
                .schema()
                .field_with_name("timestamp_utc")
                .unwrap()
                .data_type(),
            DataType::Timestamp(_, _)
        ));
        assert_eq!(batch.column_by_name("sat").unwrap().len(), 2);
        assert_eq!(batch.column_by_name("source").unwrap().len(), 2);
        assert_eq!(batch.column_by_name("is_simulated").unwrap().len(), 2);
    }

    #[test]
    fn mixed_json_scalar_type_fails_closed() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("history.jsonl");
        fs::write(
            &path,
            concat!(
                "{\"timestamp\":\"2026-08-20T12:00:00Z\",\"sat\":55.0}\n",
                "{\"timestamp\":\"2026-08-20T12:05:00Z\",\"sat\":\"bad\"}\n"
            ),
        )
        .unwrap();
        let error = for_each_legacy_batch(&path, LegacyHistorianFormat::Jsonl, |_| Ok(()))
            .unwrap_err();
        assert!(error.to_string().contains("changes scalar type"));
    }

    #[test]
    fn arrow_ipc_timestamp_is_renamed_without_row_loss() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("history.arrow");
        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "timestamp",
                DataType::Timestamp(TimeUnit::Millisecond, None),
                false,
            ),
            Field::new("equipment_id", DataType::Utf8, false),
        ]));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(arrow::array::TimestampMillisecondArray::from(vec![
                    1_i64, 2_i64,
                ])),
                Arc::new(StringArray::from(vec!["AHU_1", "AHU_1"])),
            ],
        )
        .unwrap();
        let file = fs::File::create(&path).unwrap();
        let mut writer = FileWriter::try_new(file, &schema).unwrap();
        writer.write(&batch).unwrap();
        writer.finish().unwrap();

        let mut output = Vec::new();
        let rows = for_each_legacy_batch(&path, LegacyHistorianFormat::Feather, |batch| {
            output.push(batch);
            Ok(())
        })
        .unwrap();
        assert_eq!(rows, 2);
        assert_eq!(output.len(), 1);
        assert!(output[0].schema().index_of("timestamp_utc").is_ok());
        assert!(output[0].schema().index_of("timestamp").is_err());
    }
}
