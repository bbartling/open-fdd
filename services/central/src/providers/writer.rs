//! Push normalized portal samples into the canonical live historian path.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use chrono::Utc;
use openfdd_contracts::{Protocol, Quality, TelemetryEnvelope, TelemetryPoint};
use uuid::Uuid;

use super::types::NormalizedSample;
use crate::state::AppState;

static PROVIDER_SEQUENCE: AtomicU64 = AtomicU64::new(1);

pub fn edge_id_for_building(building_id: &str) -> String {
    format!("provider-{building_id}")
}

pub async fn ingest_samples(
    state: &Arc<AppState>,
    building_id: &str,
    samples: &[NormalizedSample],
) -> anyhow::Result<usize> {
    if samples.is_empty() {
        return Ok(0);
    }
    let edge_id = edge_id_for_building(building_id);
    let scope = format!("tenant=-;building={building_id}");
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
        tags.insert(
            "provider_point_id".into(),
            serde_json::Value::String(sample.provider_point_id.clone()),
        );
        for key in [
            "semantic_point_id",
            "provider_instance_id",
            "model_revision",
            "kind",
            "quantity",
            "canonical_unit",
        ] {
            if let Some(value) = sample.attrs.get(key).and_then(|v| v.as_str()) {
                tags.insert(key.into(), serde_json::Value::String(value.to_string()));
            }
        }
        points.push(TelemetryPoint {
            id: sample.provider_point_id.clone(),
            display_name: None,
            kind: Some(openfdd_contracts::ValueKind::Number),
            value: serde_json::json!(sample.val),
            unit: sample.unit.clone(),
            quality: Quality::Good,
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
        .map_err(|e| anyhow::anyhow!("provider envelope: {e}"))?;
    state.ingest_live(&scope, &envelope).await?;
    Ok(samples.len())
}
