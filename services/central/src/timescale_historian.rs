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
            let et = env
                .points
                .iter()
                .find_map(|p| tag_str(p, TAG_EQUIPMENT_TYPE).or_else(|| tag_str(p, TAG_EQUIP_TYPE)))
                .filter(|s| !s.is_empty());
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

        let n = self
            .rt
            .block_on(self.tsdb.upsert_samples(&batch))
            .context("timescale upsert_samples")?;
        report.flushes = 1;
        report.persisted_rows = n as usize;
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
        let n = self
            .rt
            .block_on(self.tsdb.upsert_samples(&batch))
            .context("timescale publish_pending")?;
        let mut report = LiveHistorianIngest {
            flushes: 1,
            persisted_rows: n as usize,
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
    into.persisted_message_ids
        .extend(part.persisted_message_ids);
    into.persisted_message_groups
        .extend(part.persisted_message_groups);
    if part.latest_persisted_timestamp_utc > into.latest_persisted_timestamp_utc {
        into.latest_persisted_timestamp_utc = part.latest_persisted_timestamp_utc;
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
    Ok(Some(row))
}
