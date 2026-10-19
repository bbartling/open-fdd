//! Push normalized portal samples into the canonical live historian path.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use chrono::{SecondsFormat, Utc};
use openfdd_contracts::{Protocol, Quality, TelemetryEnvelope, TelemetryPoint};
use uuid::Uuid;

use super::error::ProviderError;
use super::types::NormalizedSample;
use crate::live_historian::LiveHistorianIngest;
use crate::state::AppState;

static PROVIDER_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProviderIngestReceipt {
    pub submitted: usize,
    pub eligible: usize,
    pub skipped: usize,
    pub persisted_rows: usize,
    pub inserted_rows: usize,
    pub updated_rows: usize,
}

impl ProviderIngestReceipt {
    pub fn from_report(submitted: usize, report: &LiveHistorianIngest) -> Self {
        Self {
            submitted,
            eligible: report.eligible_points,
            skipped: report.skipped_points,
            persisted_rows: report.persisted_rows,
            inserted_rows: report.inserted_rows,
            updated_rows: report.updated_rows,
        }
    }
}

pub fn edge_id_for_building(building_id: &str) -> String {
    format!("provider-{building_id}")
}

pub async fn ingest_samples(
    state: &Arc<AppState>,
    building_id: &str,
    provider_instance_id: &str,
    samples: &[NormalizedSample],
) -> Result<ProviderIngestReceipt, ProviderError> {
    if samples.is_empty() {
        return Ok(ProviderIngestReceipt {
            submitted: 0,
            eligible: 0,
            skipped: 0,
            persisted_rows: 0,
            inserted_rows: 0,
            updated_rows: 0,
        });
    }
    let edge_id = edge_id_for_building(building_id);
    // Extra `provider=` segment is ignored by tenant parsing and keeps connection
    // ownership on the ingest scope. Sample PK stays the SQL role projection.
    let scope = format!("tenant=-;building={building_id};provider={provider_instance_id}");
    let seq = PROVIDER_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let mut points = Vec::with_capacity(samples.len());
    for sample in samples {
        let mut tags = serde_json::Map::new();
        tags.insert(
            "building_id".into(),
            serde_json::Value::String(sample.building_id.clone()),
        );
        tags.insert(
            "equipment_id".into(),
            serde_json::Value::String(sample.equipment_id.clone()),
        );
        tags.insert(
            "role".into(),
            serde_json::Value::String(sample.role.clone()),
        );
        tags.insert(
            "provider_instance_id".into(),
            serde_json::Value::String(sample.provider_instance_id.clone()),
        );
        tags.insert(
            "provider_point_id".into(),
            serde_json::Value::String(sample.provider_point_id.clone()),
        );
        tags.insert(
            "source_ts".into(),
            serde_json::Value::String(sample.ts.to_rfc3339_opts(SecondsFormat::AutoSi, true)),
        );
        if let Some(et) = sample.equip_type.as_deref().filter(|s| !s.is_empty()) {
            tags.insert(
                "equipType".into(),
                serde_json::Value::String(et.to_string()),
            );
            tags.insert(
                "equipment_type".into(),
                serde_json::Value::String(et.to_string()),
            );
        }
        if let Some(unit) = sample.unit.as_deref().filter(|s| !s.is_empty()) {
            tags.insert(
                "source_unit".into(),
                serde_json::Value::String(unit.to_string()),
            );
        }
        let quality = match sample.source_quality.as_deref() {
            Some("uncertain") => {
                tags.insert(
                    "source_quality".into(),
                    serde_json::Value::String("uncertain".into()),
                );
                Quality::Uncertain
            }
            Some("bad") => {
                tags.insert(
                    "source_quality".into(),
                    serde_json::Value::String("bad".into()),
                );
                Quality::Bad
            }
            Some("stale") => {
                tags.insert(
                    "source_quality".into(),
                    serde_json::Value::String("stale".into()),
                );
                Quality::Stale
            }
            Some("good") => {
                tags.insert(
                    "source_quality".into(),
                    serde_json::Value::String("good".into()),
                );
                Quality::Good
            }
            _ => Quality::Good,
        };
        points.push(TelemetryPoint {
            id: sample.provider_point_id.clone(),
            display_name: None,
            kind: Some(openfdd_contracts::ValueKind::Number),
            value: serde_json::json!(sample.val),
            unit: sample.unit.clone(),
            quality,
            observed_at: Some(sample.ts),
            tags,
        });
    }
    let observed_at = samples.iter().map(|s| s.ts).max().unwrap_or_else(Utc::now);
    let mut envelope = TelemetryEnvelope::new(building_id, edge_id, Protocol::Rest, seq, points);
    envelope.observed_at = observed_at;
    envelope.message_id = Uuid::new_v4();
    envelope
        .validate()
        .map_err(|_| ProviderError::new(super::error::ProviderErrorCode::InvalidSample))?;
    let report = state.ingest_live(&scope, &envelope).await.map_err(|err| {
        tracing::warn!(
            code = "persistence",
            connection_lost = crate::timescale_historian::historian_error_drops_connection(&err),
            "provider sample persist failed"
        );
        ProviderError::persistence()
    })?;
    Ok(ProviderIngestReceipt::from_report(samples.len(), &report))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn receipt_uses_persisted_rows_not_input_length() {
        let report = LiveHistorianIngest {
            eligible_points: 4,
            skipped_points: 1,
            persisted_rows: 3,
            inserted_rows: 2,
            updated_rows: 1,
            ..LiveHistorianIngest::default()
        };
        let receipt = ProviderIngestReceipt::from_report(10, &report);
        assert_eq!(receipt.submitted, 10);
        assert_eq!(receipt.persisted_rows, 3);
        assert_eq!(receipt.inserted_rows, 2);
        assert_eq!(receipt.updated_rows, 1);
        assert_ne!(receipt.persisted_rows, receipt.submitted);
    }
}
