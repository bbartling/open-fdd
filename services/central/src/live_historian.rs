//! H7 live telemetry normalization into the canonical H2 micro-batch writer.
//!
//! Live telemetry is accepted for canonical history only when the MQTTS point
//! carries explicit `building_id`, `equipment_id`, and `role` tags. These tags
//! come from trusted/operator-authored fieldbus metadata; this module never
//! parses BACnet/REST point IDs to invent historian identity.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, bail, Context, Result};
use chrono::{DateTime, Utc};
use datafusion::arrow::array::{
    ArrayRef, BooleanArray, Float64Array, StringArray, TimestampNanosecondArray,
};
use datafusion::arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use datafusion::arrow::record_batch::RecordBatch;
use fdd_core::columns::normalize_role;
use fdd_store::{
    safe_partition_value, HistorianConfig, LocalStorage, MicroBatchFlush, MicroBatchHistorian,
    ParquetPartWriter, StorageUrl,
};
use openfdd_contracts::{Quality, TelemetryEnvelope, TelemetryPoint, ValueKind};

const TAG_BUILDING_ID: &str = "building_id";
const TAG_EQUIPMENT_ID: &str = "equipment_id";
const TAG_ROLE: &str = "role";

type EquipmentKey = (String, String);
type EquipmentRoles = BTreeMap<String, RoleValue>;
type NormalizedBatches = (BTreeMap<EquipmentKey, RecordBatch>, usize, usize);

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LiveHistorianIngest {
    pub eligible_points: usize,
    pub skipped_points: usize,
    pub flushes: usize,
    pub persisted_rows: usize,
    pub latest_persisted_timestamp_utc: Option<DateTime<Utc>>,
}

#[derive(Debug)]
pub struct LiveHistorian {
    batches: MicroBatchHistorian,
    latest_persisted_timestamp_utc: Option<DateTime<Utc>>,
}

impl LiveHistorian {
    /// Build the H7 live writer from the canonical historian config.
    ///
    /// H7 starts with the existing H2 local writer. S3 live writes are not
    /// silently redirected to container disk: object-store cutover must use a
    /// complete-object writer before this constructor accepts an S3 backend.
    pub fn from_env() -> Result<Self> {
        Self::from_config(&HistorianConfig::from_env()?)
    }

    pub fn from_config(config: &HistorianConfig) -> Result<Self> {
        let StorageUrl::File { root } = &config.storage_url else {
            bail!(
                "live canonical historian S3 writes are not enabled yet; refusing ephemeral-disk fallback"
            );
        };
        let writer = ParquetPartWriter::new(LocalStorage::new(root));
        let batches = MicroBatchHistorian::new(
            writer,
            config.flush_rows,
            Duration::from_secs(config.flush_seconds),
        )?;
        Ok(Self {
            batches,
            latest_persisted_timestamp_utc: None,
        })
    }

    pub fn ingest_envelope(&mut self, env: &TelemetryEnvelope) -> Result<LiveHistorianIngest> {
        let (groups, eligible_points, skipped_points) = normalized_batches(env)?;
        let mut report = LiveHistorianIngest {
            eligible_points,
            skipped_points,
            ..LiveHistorianIngest::default()
        };
        for ((building_id, equipment_id), batch) in groups {
            let flushes = self
                .batches
                .push(building_id, equipment_id, batch)
                .context("buffer canonical live historian batch")?;
            self.apply_flushes(&flushes, &mut report)?;
        }
        Ok(report)
    }

    pub fn flush_due(&mut self) -> Result<LiveHistorianIngest> {
        let flushes = self.batches.flush_due()?;
        let mut report = LiveHistorianIngest::default();
        self.apply_flushes(&flushes, &mut report)?;
        Ok(report)
    }

    // H7 will call this from the owning runtime's graceful-shutdown path. Keep
    // the primitive available while that wiring remains an explicit H7 task.
    #[allow(dead_code)]
    pub fn shutdown_flush(&mut self) -> Result<LiveHistorianIngest> {
        let flushes = self.batches.shutdown_flush()?;
        let mut report = LiveHistorianIngest::default();
        self.apply_flushes(&flushes, &mut report)?;
        Ok(report)
    }

    pub fn pending_rows(&self) -> usize {
        self.batches.pending_rows()
    }

    pub fn latest_persisted_timestamp_utc(&self) -> Option<DateTime<Utc>> {
        self.latest_persisted_timestamp_utc
    }

    fn apply_flushes(
        &mut self,
        flushes: &[MicroBatchFlush],
        report: &mut LiveHistorianIngest,
    ) -> Result<()> {
        report.flushes += flushes.len();
        for flush in flushes {
            report.persisted_rows += flush.rows;
            for part in &flush.parts {
                let timestamp = DateTime::parse_from_rfc3339(&part.last_timestamp_utc)
                    .with_context(|| {
                        format!(
                            "parse canonical live part timestamp {}",
                            part.last_timestamp_utc
                        )
                    })?
                    .with_timezone(&Utc);
                self.latest_persisted_timestamp_utc = Some(
                    self.latest_persisted_timestamp_utc
                        .map_or(timestamp, |current| current.max(timestamp)),
                );
            }
        }
        report.latest_persisted_timestamp_utc = self.latest_persisted_timestamp_utc;
        Ok(())
    }
}

#[derive(Debug, Clone)]
enum RoleValue {
    Number(Option<f64>),
    Boolean(Option<bool>),
    Utf8(Option<String>),
}

fn normalized_batches(env: &TelemetryEnvelope) -> Result<NormalizedBatches> {
    let mut grouped: BTreeMap<EquipmentKey, EquipmentRoles> = BTreeMap::new();
    let mut eligible = 0usize;
    let mut skipped = 0usize;

    for point in &env.points {
        let Some((building_id, equipment_id, role)) = point_identity(point)? else {
            skipped += 1;
            continue;
        };
        let Some(value) = role_value(point)? else {
            skipped += 1;
            continue;
        };
        let roles = grouped.entry((building_id, equipment_id)).or_default();
        if roles.insert(role.clone(), value).is_some() {
            bail!("duplicate canonical live role {role} in one equipment envelope");
        }
        eligible += 1;
    }

    let timestamp = env
        .observed_at
        .timestamp_nanos_opt()
        .ok_or_else(|| anyhow!("live telemetry timestamp is outside Arrow nanosecond range"))?;
    let mut out = BTreeMap::new();
    for (identity, roles) in grouped {
        let mut fields = vec![Field::new(
            "timestamp_utc",
            DataType::Timestamp(TimeUnit::Nanosecond, None),
            false,
        )];
        let mut arrays: Vec<ArrayRef> =
            vec![Arc::new(TimestampNanosecondArray::from(vec![timestamp]))];
        for (role, value) in roles {
            match value {
                RoleValue::Number(value) => {
                    fields.push(Field::new(&role, DataType::Float64, true));
                    arrays.push(Arc::new(Float64Array::from(vec![value])));
                }
                RoleValue::Boolean(value) => {
                    fields.push(Field::new(&role, DataType::Boolean, true));
                    arrays.push(Arc::new(BooleanArray::from(vec![value])));
                }
                RoleValue::Utf8(value) => {
                    fields.push(Field::new(&role, DataType::Utf8, true));
                    arrays.push(Arc::new(StringArray::from(vec![value])));
                }
            }
        }
        let batch = RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)?;
        out.insert(identity, batch);
    }
    Ok((out, eligible, skipped))
}

fn point_identity(point: &TelemetryPoint) -> Result<Option<(String, String, String)>> {
    let Some(building_id) = string_tag(point, TAG_BUILDING_ID) else {
        return Ok(None);
    };
    let Some(equipment_id) = string_tag(point, TAG_EQUIPMENT_ID) else {
        return Ok(None);
    };
    let Some(raw_role) = string_tag(point, TAG_ROLE) else {
        return Ok(None);
    };
    let building_id = safe_partition_value(building_id, TAG_BUILDING_ID)?;
    let equipment_id = safe_partition_value(equipment_id, TAG_EQUIPMENT_ID)?;
    let role = normalize_role(raw_role);
    validate_role(&role)?;
    Ok(Some((building_id, equipment_id, role)))
}

fn string_tag<'a>(point: &'a TelemetryPoint, name: &str) -> Option<&'a str> {
    point
        .tags
        .get(name)?
        .as_str()
        .filter(|value| !value.is_empty())
}

fn validate_role(role: &str) -> Result<()> {
    if matches!(
        role,
        "timestamp_utc" | "building_id" | "equipment_id" | "year" | "month"
    ) {
        bail!("reserved canonical historian role {role}");
    }
    let mut chars = role.chars();
    let Some(first) = chars.next() else {
        bail!("canonical historian role cannot be empty");
    };
    if !(first.is_ascii_alphabetic() || first == '_')
        || !chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
    {
        bail!("unsafe canonical historian role {role}");
    }
    Ok(())
}

fn role_value(point: &TelemetryPoint) -> Result<Option<RoleValue>> {
    let good = matches!(point.quality, Quality::Good | Quality::Uncertain);
    match point.kind {
        Some(ValueKind::Number) => Ok(Some(RoleValue::Number(if good {
            point.value.as_f64()
        } else {
            None
        }))),
        Some(ValueKind::Bool) => Ok(Some(RoleValue::Boolean(if good {
            point.value.as_bool()
        } else {
            None
        }))),
        Some(ValueKind::String) => Ok(Some(RoleValue::Utf8(if good {
            point.value.as_str().map(str::to_string)
        } else {
            None
        }))),
        Some(ValueKind::Null) => Ok(None),
        None if point.value.is_number() => Ok(Some(RoleValue::Number(if good {
            point.value.as_f64()
        } else {
            None
        }))),
        None if point.value.is_boolean() => Ok(Some(RoleValue::Boolean(if good {
            point.value.as_bool()
        } else {
            None
        }))),
        None if point.value.is_string() => Ok(Some(RoleValue::Utf8(if good {
            point.value.as_str().map(str::to_string)
        } else {
            None
        }))),
        None if point.value.is_null() => Ok(None),
        _ => bail!("live canonical historian only accepts scalar point values"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use openfdd_contracts::Protocol;
    use serde_json::json;
    use tempfile::TempDir;

    fn point(role: &str, value: serde_json::Value) -> TelemetryPoint {
        TelemetryPoint {
            id: "bacnet:5007:analog-input:1".into(),
            display_name: Some(role.into()),
            kind: Some(ValueKind::Number),
            value,
            unit: None,
            quality: Quality::Good,
            tags: json!({
                "building_id": "BUILDING_100",
                "equipment_id": "AHU_1",
                "role": role,
            })
            .as_object()
            .cloned()
            .unwrap(),
        }
    }

    fn envelope(points: Vec<TelemetryPoint>) -> TelemetryEnvelope {
        let mut env = TelemetryEnvelope::new("site-a", "edge-1", Protocol::Bacnet, 1, points);
        env.observed_at = DateTime::parse_from_rfc3339("2026-08-21T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        env
    }

    #[test]
    fn metadata_tags_define_identity_without_parsing_point_id() {
        let env = envelope(vec![point("discharge-air-temp", json!(55.0))]);
        let (groups, eligible, skipped) = normalized_batches(&env).unwrap();
        assert_eq!(eligible, 1);
        assert_eq!(skipped, 0);
        let batch = groups
            .get(&("BUILDING_100".into(), "AHU_1".into()))
            .unwrap();
        assert!(batch.schema().index_of("sat").is_ok());
        assert!(batch
            .schema()
            .index_of("bacnet:5007:analog-input:1")
            .is_err());
    }

    #[test]
    fn untagged_point_is_not_canonicalized() {
        let mut p = point("sat", json!(55.0));
        p.tags.remove("equipment_id");
        let (groups, eligible, skipped) = normalized_batches(&envelope(vec![p])).unwrap();
        assert!(groups.is_empty());
        assert_eq!(eligible, 0);
        assert_eq!(skipped, 1);
    }

    #[test]
    fn bad_quality_preserves_schema_as_null() {
        let mut p = point("sat", json!(55.0));
        p.quality = Quality::Bad;
        let (groups, _, _) = normalized_batches(&envelope(vec![p])).unwrap();
        let batch = groups.values().next().unwrap();
        assert_eq!(batch.schema().field(1).name(), "sat");
        assert_eq!(batch.column(1).null_count(), 1);
    }

    #[test]
    fn local_live_writer_flushes_to_canonical_partition() {
        let tmp = TempDir::new().unwrap();
        let config = HistorianConfig {
            storage_url: StorageUrl::File {
                root: tmp.path().to_path_buf(),
            },
            flush_rows: 1,
            flush_seconds: 60,
            target_file_mb: 128,
            compaction_min_files: 8,
            compaction_enabled: true,
            query_memory_mb: 512,
            spill_directory: None,
            legacy_parquet_root: None,
        };
        let mut live = LiveHistorian::from_config(&config).unwrap();
        let report = live
            .ingest_envelope(&envelope(vec![point("sat", json!(55.0))]))
            .unwrap();
        assert_eq!(report.persisted_rows, 1);
        assert_eq!(report.flushes, 1);
        assert_eq!(
            report.latest_persisted_timestamp_utc.unwrap().to_rfc3339(),
            "2026-08-21T12:00:00+00:00"
        );
        let partition = tmp
            .path()
            .join("history/building_id=BUILDING_100/equipment_id=AHU_1/year=2026/month=08");
        assert_eq!(std::fs::read_dir(partition).unwrap().count(), 1);
    }

    #[test]
    fn s3_does_not_fall_back_to_ephemeral_local_disk() {
        let config = HistorianConfig {
            storage_url: StorageUrl::S3 {
                bucket: "history".into(),
                prefix: String::new(),
            },
            flush_rows: 1,
            flush_seconds: 60,
            target_file_mb: 128,
            compaction_min_files: 8,
            compaction_enabled: true,
            query_memory_mb: 512,
            spill_directory: None,
            legacy_parquet_root: None,
        };
        assert!(LiveHistorian::from_config(&config).is_err());
    }
}
