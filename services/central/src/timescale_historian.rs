//! Wave-X Timescale-only live ingest (ADR-010).
//!
//! Replaces Parquet/Arrow micro-batch publication on the product path when
//! `OPENFDD_HISTORIAN=timescale` (default under compose.timescale.yml).
//! Fieldbus BACnet/Modbus drivers are unchanged — MQTTS envelopes land here.

use std::collections::HashMap;
use std::env;

use anyhow::{anyhow, bail, Context, Result};
use chrono::{DateTime, Utc};
use fdd_core::columns::haystack_point_to_role;
use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};
use openfdd_contracts::{TelemetryEnvelope, TelemetryPoint};
use tracing::{info, warn};
use uuid::Uuid;

use crate::live_historian::{LiveHistorianIngest, PersistedMessageGroup};

const TAG_BUILDING_ID: &str = "building_id";
const TAG_EQUIPMENT_ID: &str = "equipment_id";
const TAG_ROLE: &str = "role";
const TAG_EQUIPMENT_TYPE: &str = "equipment_type";
const TAG_EQUIP_TYPE: &str = "equipType";

pub fn historian_is_timescale() -> bool {
    match env::var("OPENFDD_HISTORIAN") {
        Ok(raw) => match raw.to_ascii_lowercase().as_str() {
            "timescale" | "tsdb" | "postgres" | "sql" => true,
            "parquet" | "datafusion" | "legacy" => false,
            other => {
                warn!(%other, "unknown OPENFDD_HISTORIAN; using OPENFDD_DATABASE_URL presence");
                env::var("OPENFDD_DATABASE_URL").is_ok()
            }
        },
        // Product compose sets OPENFDD_DATABASE_URL + overlay. Unit tests without
        // a URL keep the legacy Parquet writer so existing fixtures compile/run.
        Err(_) => env::var("OPENFDD_DATABASE_URL").is_ok(),
    }
}

pub struct TimescaleLiveHistorian {
    rt: tokio::runtime::Runtime,
    tsdb: Tsdb,
    /// Buffered rows awaiting publish_pending / flush (per scope).
    pending: HashMap<String, UpsertBatch>,
    pending_meta: HashMap<String, Vec<PendingMeta>>,
}

struct PendingMeta {
    message_id: Uuid,
    edge_id: String,
    building_id: String,
    equipment_id: String,
    rows: usize,
}

impl TimescaleLiveHistorian {
    pub fn connect() -> Result<Self> {
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .context("timescale writer runtime")?;
        let tsdb = rt
            .block_on(Tsdb::connect_from_env())
            .context("connect OPENFDD_DATABASE_URL")?;
        rt.block_on(tsdb.health_ping())
            .context("timescale health ping")?;
        info!("Wave-X live historian: Timescale-only (no Parquet writer)");
        Ok(Self {
            rt,
            tsdb,
            pending: HashMap::new(),
            pending_meta: HashMap::new(),
        })
    }

    pub fn ingest_envelope(
        &mut self,
        scope: &str,
        env: &TelemetryEnvelope,
    ) -> Result<LiveHistorianIngest> {
        let mut batch = UpsertBatch::default();
        let mut skipped = 0usize;
        let mut eligible = 0usize;
        let mut by_equip: HashMap<(String, String), usize> = HashMap::new();
        let equip_types = equipment_types_in_envelope(env);

        for point in &env.points {
            match point_to_sample(env, point) {
                Ok(Some(row)) => {
                    let key = (
                        row.site_id.clone(),
                        row.equipment_id.clone().unwrap_or_default(),
                    );
                    *by_equip.entry(key).or_default() += 1;
                    batch.push(row);
                    eligible += 1;
                }
                Ok(None) => skipped += 1,
                Err(_) => skipped += 1,
            }
        }

        let mut report = LiveHistorianIngest {
            eligible_points: eligible,
            skipped_points: skipped,
            ..LiveHistorianIngest::default()
        };

        if batch.is_empty() {
            return Ok(report);
        }

        // Immediate publish (no Parquet micro-batch). Receipt = Timescale upsert.
        for ((building_id, equipment_id), rows) in &by_equip {
            if equipment_id.is_empty() {
                continue;
            }
            let et = equip_types
                .get(&(building_id.clone(), equipment_id.clone()))
                .cloned();
            self.rt.block_on(async {
                self.tsdb.ensure_site_building(building_id).await?;
                self.tsdb
                    .upsert_equipment(building_id, equipment_id, et.as_deref())
                    .await?;
                Ok::<(), anyhow::Error>(())
            })?;
            report.persisted_message_groups.push(PersistedMessageGroup {
                message_id: env.message_id,
                scope: scope.to_string(),
                edge_id: env.edge_id.clone(),
                building_id: building_id.clone(),
                equipment_id: equipment_id.clone(),
                rows: *rows,
            });
        }

        let stats = self
            .rt
            .block_on(self.tsdb.upsert_samples_stats(&batch))
            .context("timescale upsert_samples")?;
        report.flushes = 1;
        report.inserted_rows = stats.inserted as usize;
        report.updated_rows = stats.updated as usize;
        report.persisted_rows = stats.persisted() as usize;
        report.persisted_message_ids = vec![env.message_id];
        if let Some(ts) = batch.rows.iter().map(|r| r.ts).max() {
            report.latest_persisted_timestamp_utc = Some(ts);
        }
        Ok(report)
    }

    pub fn flush_all(&mut self, _graceful: bool) -> Result<LiveHistorianIngest> {
        // Immediate-write path: nothing buffered.
        let scopes: Vec<String> = self.pending.keys().cloned().collect();
        let mut combined = LiveHistorianIngest::default();
        for scope in scopes {
            let part = self.publish_pending(&scope)?;
            merge_report(&mut combined, part);
        }
        Ok(combined)
    }

    pub fn publish_pending(&mut self, scope: &str) -> Result<LiveHistorianIngest> {
        let Some(batch) = self.pending.remove(scope) else {
            return Ok(LiveHistorianIngest::default());
        };
        let meta = self.pending_meta.remove(scope).unwrap_or_default();
        if batch.is_empty() {
            return Ok(LiveHistorianIngest::default());
        }
        let stats = self
            .rt
            .block_on(self.tsdb.upsert_samples_stats(&batch))
            .context("timescale publish_pending")?;
        let mut report = LiveHistorianIngest {
            flushes: 1,
            persisted_rows: stats.persisted() as usize,
            inserted_rows: stats.inserted as usize,
            updated_rows: stats.updated as usize,
            ..LiveHistorianIngest::default()
        };
        for m in meta {
            report.persisted_message_ids.push(m.message_id);
            report.persisted_message_groups.push(PersistedMessageGroup {
                message_id: m.message_id,
                scope: scope.to_string(),
                edge_id: m.edge_id,
                building_id: m.building_id,
                equipment_id: m.equipment_id,
                rows: m.rows,
            });
        }
        Ok(report)
    }
}

fn merge_report(into: &mut LiveHistorianIngest, part: LiveHistorianIngest) {
    into.eligible_points += part.eligible_points;
    into.skipped_points += part.skipped_points;
    into.flushes += part.flushes;
    into.persisted_rows += part.persisted_rows;
    into.inserted_rows += part.inserted_rows;
    into.updated_rows += part.updated_rows;
    into.persisted_message_ids
        .extend(part.persisted_message_ids);
    into.persisted_message_groups
        .extend(part.persisted_message_groups);
    if part.latest_persisted_timestamp_utc > into.latest_persisted_timestamp_utc {
        into.latest_persisted_timestamp_utc = part.latest_persisted_timestamp_utc;
    }
}

/// First equipment-type stamp on each equipment. A mixed envelope must not
/// reuse the first point's type for every later device.
pub(crate) fn equipment_types_in_envelope(
    env: &TelemetryEnvelope,
) -> HashMap<(String, String), String> {
    let mut out = HashMap::new();
    for point in &env.points {
        let building = tag_str(point, TAG_BUILDING_ID).or_else(|| {
            if env.site_id.is_empty() {
                None
            } else {
                Some(env.site_id.clone())
            }
        });
        let Some(building) = building.filter(|s| !s.is_empty()) else {
            continue;
        };
        let Some(equipment) = tag_str(point, TAG_EQUIPMENT_ID).filter(|s| !s.is_empty()) else {
            continue;
        };
        let Some(kind) = tag_str(point, TAG_EQUIPMENT_TYPE)
            .or_else(|| tag_str(point, TAG_EQUIP_TYPE))
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
        else {
            continue;
        };
        out.entry((building, equipment)).or_insert(kind);
    }
    out
}

/// Connection-class failures drop the historian so the next command reconnects.
/// Constraint and data errors keep the pool.
pub fn historian_error_drops_connection(err: &anyhow::Error) -> bool {
    for cause in err.chain() {
        if let Some(tsdb) = cause.downcast_ref::<fdd_tsdb::TsdbError>() {
            return tsdb_error_is_connection_loss(tsdb);
        }
        let text = cause.to_string().to_ascii_lowercase();
        if text.contains("connection refused")
            || text.contains("connection reset")
            || text.contains("pool timed out")
            || text.contains("broken pipe")
            || text.contains("server closed the connection")
            || text.contains("timescale_unavailable")
        {
            return true;
        }
    }
    false
}

fn tsdb_error_is_connection_loss(err: &fdd_tsdb::TsdbError) -> bool {
    match err {
        fdd_tsdb::TsdbError::MissingDatabaseUrl => true,
        fdd_tsdb::TsdbError::Sqlx(inner) => sqlx_is_connection_loss(inner),
    }
}

fn sqlx_is_connection_loss(err: &sqlx::Error) -> bool {
    matches!(
        err,
        sqlx::Error::PoolTimedOut
            | sqlx::Error::PoolClosed
            | sqlx::Error::Io(_)
            | sqlx::Error::Tls(_)
            | sqlx::Error::Protocol(_)
            | sqlx::Error::WorkerCrashed
    )
}

pub(crate) struct TimescaleConnectGate<T> {
    inner: Option<T>,
}

impl<T> TimescaleConnectGate<T> {
    pub(crate) fn new() -> Self {
        Self { inner: None }
    }

    pub(crate) fn is_connected(&self) -> bool {
        self.inner.is_some()
    }

    pub(crate) fn insert(&mut self, historian: T) {
        self.inner = Some(historian);
    }

    pub(crate) fn get_mut(&mut self) -> Option<&mut T> {
        self.inner.as_mut()
    }

    pub(crate) fn disconnect(&mut self) {
        self.inner = None;
    }
}

fn tag_str(point: &TelemetryPoint, key: &str) -> Option<String> {
    point.tags.get(key).and_then(|v| match v {
        serde_json::Value::String(s) => Some(s.clone()),
        serde_json::Value::Number(n) => Some(n.to_string()),
        serde_json::Value::Bool(b) => Some(b.to_string()),
        _ => None,
    })
}

fn point_value_f64(point: &TelemetryPoint) -> Option<f64> {
    match &point.value {
        serde_json::Value::Number(n) => n.as_f64(),
        serde_json::Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        serde_json::Value::String(s) => s.parse().ok(),
        _ => None,
    }
}

fn point_to_sample(env: &TelemetryEnvelope, point: &TelemetryPoint) -> Result<Option<SampleRow>> {
    let building_id = tag_str(point, TAG_BUILDING_ID)
        .or_else(|| {
            if env.site_id.is_empty() {
                None
            } else {
                Some(env.site_id.clone())
            }
        })
        .ok_or_else(|| anyhow!("missing building_id"))?;
    let equipment_id =
        tag_str(point, TAG_EQUIPMENT_ID).ok_or_else(|| anyhow!("missing equipment_id"))?;
    let role_raw = tag_str(point, TAG_ROLE).ok_or_else(|| anyhow!("missing role"))?;
    let role = haystack_point_to_role(&role_raw);
    if role.is_empty() {
        bail!("empty role");
    }
    let Some(val) = point_value_f64(point) else {
        return Ok(None);
    };
    let ts: DateTime<Utc> = point.observed_at.unwrap_or(env.observed_at);
    let openfdd_key = format!("{equipment_id}.{role}");
    let mut row = SampleRow::new(ts, building_id, openfdd_key, Some(val));
    row.equipment_id = Some(equipment_id);
    row.role = Some(role);
    row.unit = point.unit.clone();
    row.haystack_id = Some(point.id.clone());
    if let Some(quality) = tag_str(point, "source_quality") {
        if !matches!(quality.as_str(), "good" | "uncertain" | "bad" | "stale") {
            return Ok(None);
        }
        row.quality = Some(quality);
    }
    Ok(Some(row))
}

#[cfg(test)]
mod tests {
    use chrono::{DateTime, Utc};
    use openfdd_contracts::{Protocol, Quality, TelemetryEnvelope, TelemetryPoint, ValueKind};

    use super::{
        equipment_types_in_envelope, historian_error_drops_connection, point_to_sample,
        TimescaleConnectGate,
    };

    fn point(
        building: &str,
        equipment: &str,
        role: &str,
        equip_type: &str,
        quality: Option<&str>,
    ) -> TelemetryPoint {
        let mut tags = serde_json::Map::new();
        tags.insert("building_id".into(), serde_json::json!(building));
        tags.insert("equipment_id".into(), serde_json::json!(equipment));
        tags.insert("role".into(), serde_json::json!(role));
        tags.insert("equipment_type".into(), serde_json::json!(equip_type));
        if let Some(q) = quality {
            tags.insert("source_quality".into(), serde_json::json!(q));
        }
        TelemetryPoint {
            id: format!("{equipment}-{role}"),
            display_name: None,
            kind: Some(ValueKind::Number),
            value: serde_json::json!(1.0),
            unit: Some("°F".into()),
            quality: Quality::Good,
            observed_at: Some(
                DateTime::parse_from_rfc3339("2026-10-18T12:00:00.123456Z")
                    .unwrap()
                    .with_timezone(&Utc),
            ),
            tags,
        }
    }

    #[test]
    fn mixed_batch_keeps_each_equipment_type() {
        let mut env = TelemetryEnvelope::new(
            "SITE",
            "edge",
            Protocol::Rest,
            1,
            vec![
                point("SITE", "VAV_1", "zone_t", "vav", None),
                point("SITE", "AHU_1", "sat", "ahu", Some("uncertain")),
                point("SITE", "WEATHER", "oa_t", "weather", Some("good")),
                point("SITE", "AHU_1", "mat", "zone_other", None),
            ],
        );
        env.points.swap(0, 2);
        let types = equipment_types_in_envelope(&env);
        assert_eq!(
            types
                .get(&("SITE".into(), "VAV_1".into()))
                .map(String::as_str),
            Some("vav")
        );
        assert_eq!(
            types
                .get(&("SITE".into(), "AHU_1".into()))
                .map(String::as_str),
            Some("ahu")
        );
        assert_eq!(
            types
                .get(&("SITE".into(), "WEATHER".into()))
                .map(String::as_str),
            Some("weather")
        );
    }

    #[test]
    fn sample_keeps_source_time_unit_and_quality() {
        let env = TelemetryEnvelope::new(
            "SITE",
            "edge",
            Protocol::Rest,
            1,
            vec![point("SITE", "AHU_1", "sat", "ahu", Some("uncertain"))],
        );
        let row = point_to_sample(&env, &env.points[0]).unwrap().unwrap();
        assert_eq!(row.ts.timestamp_subsec_micros(), 123_456);
        assert_eq!(row.unit.as_deref(), Some("°F"));
        assert_eq!(row.quality.as_deref(), Some("uncertain"));
        assert_eq!(row.equipment_id.as_deref(), Some("AHU_1"));
    }

    #[test]
    fn connect_gate_retries_after_drop() {
        let mut gate = TimescaleConnectGate::new();
        assert!(!gate.is_connected());
        gate.insert("historian");
        assert!(gate.is_connected());
        gate.disconnect();
        assert!(!gate.is_connected());
        gate.insert("reconnected");
        assert_eq!(gate.get_mut().copied(), Some("reconnected"));
    }

    #[test]
    fn connection_loss_classifier_ignores_constraint_text() {
        let data = anyhow::anyhow!("duplicate key value violates unique constraint");
        assert!(!historian_error_drops_connection(&data));
        let lost = anyhow::anyhow!("connection refused");
        assert!(historian_error_drops_connection(&lost));
    }
}
