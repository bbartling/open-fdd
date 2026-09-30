//! H7 live telemetry normalization into the canonical H2 micro-batch writer.
//!
//! Live telemetry is accepted for canonical history only when the MQTTS point
//! carries explicit `building_id`, `equipment_id`, and `role` tags. These tags
//! come from trusted/operator-authored fieldbus metadata; this module never
//! parses BACnet/REST point IDs to invent historian identity.

use std::collections::{BTreeMap, HashMap};
use std::env;
use std::fmt;
use std::future::Future;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Context, Result};
use bytes::Bytes;
use chrono::{DateTime, Utc};
use datafusion::arrow::array::{
    ArrayRef, BooleanArray, Float64Array, StringArray, TimestampNanosecondArray,
};
use datafusion::arrow::datatypes::{DataType, Field, Schema, TimeUnit};
use datafusion::arrow::record_batch::RecordBatch;
use fdd_core::columns::normalize_role;
use fdd_store::{
    safe_partition_value, tenant_storage_prefix, tenant_storage_root, CompletePartPublisher,
    HistorianConfig, LocalStorage, MicroBatchFlush, MicroBatchHistorian, ParquetPartWriter,
    StorageUrl,
};
use object_store::aws::AmazonS3Builder;
use object_store::path::Path as ObjectPath;
use object_store::ObjectStore;
use object_store::ObjectStoreExt;
use open_fdd_edge_prototype::equipment_types;
use openfdd_contracts::{Quality, TelemetryEnvelope, TelemetryPoint, ValueKind};
use serde::{Deserialize, Serialize};
use tracing::warn;
use url::Url;
use uuid::Uuid;

const TAG_BUILDING_ID: &str = "building_id";
const TAG_EQUIPMENT_ID: &str = "equipment_id";
const TAG_ROLE: &str = "role";
const TAG_EQUIPMENT_TYPE: &str = "equipment_type";
const TAG_EQUIP_TYPE: &str = "equipType";
const LATEST_TELEMETRY_WATERMARK: &str = "state/live-historian/latest-telemetry.json";

type EquipmentKey = (String, String);
type EquipmentRoles = BTreeMap<String, RoleValue>;
type NormalizedBatches = (
    BTreeMap<EquipmentKey, RecordBatch>,
    usize,
    usize,
    Vec<DuplicateRole>,
);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DuplicateRole {
    pub building_id: String,
    pub equipment_id: String,
    pub role: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LiveHistorianIngest {
    pub eligible_points: usize,
    pub skipped_points: usize,
    pub flushes: usize,
    pub persisted_rows: usize,
    pub latest_persisted_timestamp_utc: Option<DateTime<Utc>>,
    /// Later points with a canonical role already present in the same equipment
    /// envelope. The first point wins deterministically; unique points remain valid.
    pub duplicate_roles: Vec<DuplicateRole>,
    /// Message ids whose rows were included in an atomically published part.
    /// A receipt stays pending until its id appears here, including time and
    /// shutdown flushes.
    pub persisted_message_ids: Vec<Uuid>,
    /// Exact message/equipment provenance for each published row group. A
    /// message is complete only after every eligible equipment group is
    /// published, even when one group flushes earlier than the others.
    pub persisted_message_groups: Vec<PersistedMessageGroup>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersistedMessageGroup {
    pub message_id: Uuid,
    pub scope: String,
    pub edge_id: String,
    pub building_id: String,
    pub equipment_id: String,
    pub rows: usize,
}

#[derive(Clone, Debug)]
struct BufferedProvenance {
    message_id: Uuid,
    edge_id: String,
    building_id: String,
    equipment_id: String,
    rows: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct LatestTelemetryWatermark {
    latest_persisted_timestamp_utc: DateTime<Utc>,
}

#[derive(Debug, Clone)]
enum WatermarkStore {
    Local(LocalStorage),
    S3(S3PartPublisher),
}

impl WatermarkStore {
    fn read(&self) -> Result<Option<DateTime<Utc>>> {
        let bytes = match self {
            Self::Local(storage) => {
                let path = Path::new(LATEST_TELEMETRY_WATERMARK);
                if !storage.exists(path)? {
                    return Ok(None);
                }
                storage.read(path)?
            }
            Self::S3(storage) => {
                match storage.get_optional(Path::new(LATEST_TELEMETRY_WATERMARK))? {
                    Some(bytes) => bytes,
                    None => return Ok(None),
                }
            }
        };
        let watermark: LatestTelemetryWatermark =
            serde_json::from_slice(&bytes).context("decode live historian telemetry watermark")?;
        Ok(Some(watermark.latest_persisted_timestamp_utc))
    }

    fn write(&self, timestamp: DateTime<Utc>) -> Result<()> {
        let bytes = serde_json::to_vec_pretty(&LatestTelemetryWatermark {
            latest_persisted_timestamp_utc: timestamp,
        })?;
        match self {
            Self::Local(storage) => {
                storage.write_atomic(Path::new(LATEST_TELEMETRY_WATERMARK), &bytes)
            }
            Self::S3(storage) => storage.put_bytes(Path::new(LATEST_TELEMETRY_WATERMARK), &bytes),
        }
    }
}

#[derive(Clone)]
struct S3PartPublisher {
    store: Arc<dyn ObjectStore>,
    prefix: String,
}

impl fmt::Debug for S3PartPublisher {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("S3PartPublisher")
            .field("prefix", &self.prefix)
            .field("store", &"[object-store]")
            .finish()
    }
}

impl S3PartPublisher {
    fn from_env(bucket: &str, prefix: &str) -> Result<Self> {
        Ok(Self {
            store: build_s3_store(bucket)?,
            prefix: prefix.trim_matches('/').to_string(),
        })
    }

    fn put_bytes(&self, relative_path: &Path, bytes: &[u8]) -> Result<()> {
        let location = object_path(&self.prefix, relative_path)?;
        let payload = Bytes::copy_from_slice(bytes).into();
        run_object_store(self.store.put(&location, payload))
            .with_context(|| format!("publish complete S3 historian object {location}"))?;
        Ok(())
    }

    fn get_optional(&self, relative_path: &Path) -> Result<Option<Vec<u8>>> {
        let location = object_path(&self.prefix, relative_path)?;
        let result = match run_object_store(self.store.get(&location)) {
            Ok(result) => result,
            Err(error) if is_object_not_found(&error) => return Ok(None),
            Err(error) => return Err(error).with_context(|| format!("read S3 object {location}")),
        };
        let bytes = run_object_store(result.bytes())
            .with_context(|| format!("read S3 object body {location}"))?;
        Ok(Some(bytes.to_vec()))
    }
}

impl CompletePartPublisher for S3PartPublisher {
    fn publish_complete(&self, relative_path: &Path, bytes: &[u8]) -> Result<()> {
        self.put_bytes(relative_path, bytes)
    }
}

fn is_object_not_found(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<object_store::Error>()
        .is_some_and(|error| matches!(error, object_store::Error::NotFound { .. }))
}

fn run_object_store<F, T>(future: F) -> Result<T>
where
    F: Future<Output = object_store::Result<T>>,
{
    // Production publication runs on the dedicated `openfdd-live-writer` thread,
    // which has no Tokio context. That path builds a private current-thread
    // runtime below. `block_in_place` stays only for a caller that is already
    // on a multi-thread runtime and is not inside `spawn_blocking`.
    if let Ok(handle) = tokio::runtime::Handle::try_current() {
        match handle.runtime_flavor() {
            tokio::runtime::RuntimeFlavor::MultiThread => {
                return tokio::task::block_in_place(|| handle.block_on(future)).map_err(Into::into);
            }
            tokio::runtime::RuntimeFlavor::CurrentThread => {
                bail!("S3 live historian requires a multi-thread Tokio runtime");
            }
            _ => bail!("unsupported Tokio runtime flavor for S3 live historian"),
        }
    }
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .context("build object-store runtime")?;
    runtime.block_on(future).map_err(Into::into)
}

fn build_s3_store(bucket: &str) -> Result<Arc<dyn ObjectStore>> {
    let endpoint = nonempty_env("OPENFDD_S3_ENDPOINT");
    let region = nonempty_env("OPENFDD_S3_REGION");
    let access_key_id = nonempty_env("OPENFDD_S3_ACCESS_KEY_ID");
    let secret_access_key = nonempty_env("OPENFDD_S3_SECRET_ACCESS_KEY");
    let session_token = nonempty_env("OPENFDD_S3_SESSION_TOKEN");
    let allow_http = match env::var("OPENFDD_S3_ALLOW_HTTP") {
        Ok(raw) => parse_bool("OPENFDD_S3_ALLOW_HTTP", &raw)?,
        Err(_) => false,
    };
    let virtual_hosted = match env::var("OPENFDD_S3_URL_STYLE") {
        Ok(raw) => match raw.trim().to_ascii_lowercase().as_str() {
            "path" | "path_style" | "path-style" => false,
            "virtual" | "virtual_hosted" | "virtual-hosted" => true,
            _ => bail!("OPENFDD_S3_URL_STYLE must be 'path' or 'virtual'"),
        },
        Err(_) => match env::var("OPENFDD_S3_VIRTUAL_HOSTED_STYLE") {
            Ok(raw) => parse_bool("OPENFDD_S3_VIRTUAL_HOSTED_STYLE", &raw)?,
            Err(_) => false,
        },
    };

    match (&access_key_id, &secret_access_key) {
        (Some(_), None) | (None, Some(_)) => bail!(
            "OPENFDD_S3_ACCESS_KEY_ID and OPENFDD_S3_SECRET_ACCESS_KEY must be configured together"
        ),
        _ => {}
    }
    if session_token.is_some() && access_key_id.is_none() {
        bail!(
            "OPENFDD_S3_SESSION_TOKEN requires explicit OPENFDD_S3_ACCESS_KEY_ID and OPENFDD_S3_SECRET_ACCESS_KEY"
        );
    }
    if session_token.is_some() && allow_http {
        bail!("OPENFDD_S3_SESSION_TOKEN cannot be combined with OPENFDD_S3_ALLOW_HTTP=true");
    }

    let mut builder = AmazonS3Builder::from_env()
        .with_bucket_name(bucket)
        .with_virtual_hosted_style_request(virtual_hosted)
        .with_allow_http(allow_http);
    if let Some(region) = region {
        builder = builder.with_region(region);
    }
    if let Some(endpoint) = endpoint {
        let parsed = Url::parse(&endpoint).context("parse OPENFDD_S3_ENDPOINT")?;
        if !parsed.username().is_empty() || parsed.password().is_some() {
            bail!("OPENFDD_S3_ENDPOINT must not embed credentials");
        }
        match parsed.scheme() {
            "https" => {}
            "http" if allow_http => {}
            "http" => {
                bail!("HTTP S3 endpoint requires OPENFDD_S3_ALLOW_HTTP=true (local/test only)")
            }
            _ => bail!("OPENFDD_S3_ENDPOINT must use http:// or https://"),
        }
        if parsed.host_str().is_none() {
            bail!("OPENFDD_S3_ENDPOINT requires a host");
        }
        builder = builder.with_endpoint(endpoint_for_style(&endpoint, bucket, virtual_hosted)?);
    }
    if let (Some(key), Some(secret)) = (access_key_id, secret_access_key) {
        builder = builder
            .with_access_key_id(key)
            .with_secret_access_key(secret);
    }
    if let Some(token) = session_token {
        builder = builder.with_token(token);
    }
    Ok(Arc::new(
        builder
            .build()
            .context("build S3-compatible live historian store")?,
    ))
}

fn endpoint_for_style(endpoint: &str, bucket: &str, virtual_hosted: bool) -> Result<String> {
    let endpoint = endpoint.trim().trim_end_matches('/');
    let mut parsed = Url::parse(endpoint).context("parse OPENFDD_S3_ENDPOINT")?;
    let host = parsed
        .host_str()
        .ok_or_else(|| anyhow!("OPENFDD_S3_ENDPOINT requires a host"))?;
    if !virtual_hosted || host == bucket || host.starts_with(&format!("{bucket}.")) {
        return Ok(endpoint.to_string());
    }
    let bucket_host = format!("{bucket}.{host}");
    parsed
        .set_host(Some(&bucket_host))
        .map_err(|_| anyhow!("cannot apply virtual-hosted S3 bucket to endpoint"))?;
    Ok(parsed.as_str().trim_end_matches('/').to_string())
}

fn object_path(prefix: &str, relative_path: &Path) -> Result<ObjectPath> {
    if relative_path.is_absolute() {
        bail!("S3 historian object path must be relative");
    }
    let relative = relative_path.to_string_lossy().replace('\\', "/");
    if relative.split('/').any(|segment| segment == "..") {
        bail!("S3 historian object path traversal rejected");
    }
    let prefix = prefix.trim_matches('/');
    let key = if prefix.is_empty() {
        relative
    } else {
        format!("{prefix}/{relative}")
    };
    Ok(ObjectPath::from(key))
}

fn nonempty_env(name: &str) -> Option<String> {
    env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

/// `tenant=` value from a trusted scope (`tenant={tid};building={bid}`).
///
/// `-` is the legacy placeholder used when a topic or local binding has no
/// tenant. It is not a tenant id.
fn scope_tenant_segment(scope: &str) -> Option<String> {
    scope.split(';').find_map(|part| {
        let value = part.trim().strip_prefix("tenant=")?;
        Some(value.trim().to_string())
    })
}

fn concrete_tenant(value: Option<&str>) -> Option<String> {
    let value = value?.trim();
    if value.is_empty() || value == "-" {
        None
    } else {
        Some(value.to_string())
    }
}

/// Multi-tenant storage partition for one trusted scope.
///
/// The scope tenant wins. A legacy `tenant=-` (or missing) scope may still
/// use `OPENFDD_TENANT_ID`, which is how local fieldbus binds a deployment.
/// Empty and `-` are rejected so a hub without a process-global tenant does
/// not collapse every site into one partition.
fn tenant_id_for_multi_tenant_scope(scope: &str) -> Result<String> {
    if let Some(tenant_id) = concrete_tenant(scope_tenant_segment(scope).as_deref()) {
        return Ok(tenant_id);
    }
    if let Some(tenant_id) = concrete_tenant(nonempty_env("OPENFDD_TENANT_ID").as_deref()) {
        return Ok(tenant_id);
    }
    bail!("trusted scope tenant required in multi-tenant mode")
}

fn parse_bool(name: &str, raw: &str) -> Result<bool> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => bail!("{name} must be a boolean"),
    }
}

#[derive(Debug)]
pub struct LiveHistorian {
    scope: String,
    batches: MicroBatchHistorian,
    watermark_store: WatermarkStore,
    latest_persisted_timestamp_utc: Option<DateTime<Utc>>,
    parquet_root: Option<PathBuf>,
    pending_type_stamps: BTreeMap<EquipmentKey, String>,
    /// Token attached to a buffered batch. Resolved only from a flush report
    /// that lists that token, including time-threshold and shutdown flushes.
    provenance: HashMap<u64, BufferedProvenance>,
    next_provenance_token: u64,
}

impl LiveHistorian {
    /// Build the H7 live writer from the canonical historian config.
    ///
    /// Local storage publishes with crash-safe rename. S3-compatible storage
    /// publishes complete Parquet payloads directly through object_store; S3
    /// never falls back to ephemeral container disk as canonical history.
    /// Build from deployment configuration while applying the trusted tenant
    /// partition used by local HTTP and MQTT delivery alike.
    ///
    /// When multi-tenant mode is on, the tenant id comes from the scope
    /// (`tenant={tid};building={bid}`), not from a process-global
    /// `OPENFDD_TENANT_ID`. A legacy `tenant=-` scope may still fall back to
    /// that env var for local fieldbus.
    pub fn from_env_scoped_for(scope: &str) -> Result<Self> {
        let mut config = HistorianConfig::from_env()?;
        if crate::tenant::multi_tenant_enabled() {
            let tenant_id = tenant_id_for_multi_tenant_scope(scope)?;
            config.storage_url = match config.storage_url {
                StorageUrl::File { root } => StorageUrl::File {
                    root: tenant_storage_root(&root, Some(&tenant_id))?,
                },
                StorageUrl::S3 { bucket, prefix } => {
                    let tenant_prefix = tenant_storage_prefix(Some(&tenant_id))?;
                    StorageUrl::S3 {
                        bucket,
                        prefix: if prefix.is_empty() {
                            tenant_prefix
                        } else {
                            format!("{prefix}/{tenant_prefix}")
                        },
                    }
                }
            };
        }
        Self::from_config_with_scope(&config, scope)
    }

    #[cfg(test)]
    pub fn from_config(config: &HistorianConfig) -> Result<Self> {
        Self::from_config_with_scope(config, "")
    }

    fn from_config_with_scope(config: &HistorianConfig, scope: &str) -> Result<Self> {
        let (writer, watermark_store) = match &config.storage_url {
            StorageUrl::File { root } => {
                let storage = LocalStorage::new(root);
                (
                    ParquetPartWriter::new(storage.clone()),
                    WatermarkStore::Local(storage),
                )
            }
            StorageUrl::S3 { bucket, prefix } => {
                let publisher = S3PartPublisher::from_env(bucket, prefix)?;
                (
                    ParquetPartWriter::with_publisher(Arc::new(publisher.clone())),
                    WatermarkStore::S3(publisher),
                )
            }
        };
        let batches = MicroBatchHistorian::new(
            writer,
            config.flush_rows,
            Duration::from_secs(config.flush_seconds),
        )?;
        let latest_persisted_timestamp_utc = watermark_store.read()?;
        let parquet_root = match &config.storage_url {
            StorageUrl::File { root } => Some(root.clone()),
            StorageUrl::S3 { .. } => None,
        };
        Ok(Self {
            scope: scope.to_string(),
            batches,
            watermark_store,
            latest_persisted_timestamp_utc,
            parquet_root,
            pending_type_stamps: BTreeMap::new(),
            provenance: HashMap::new(),
            next_provenance_token: 1,
        })
    }

    pub fn ingest_envelope(&mut self, env: &TelemetryEnvelope) -> Result<LiveHistorianIngest> {
        collect_type_stamps(env, &mut self.pending_type_stamps);
        let (groups, eligible_points, skipped_points, duplicate_roles) = normalized_batches(env)?;
        let mut report = LiveHistorianIngest {
            eligible_points,
            skipped_points,
            duplicate_roles,
            ..LiveHistorianIngest::default()
        };
        for ((building_id, equipment_id), batch) in groups {
            let token = self.next_provenance_token;
            self.next_provenance_token = self.next_provenance_token.saturating_add(1);
            self.provenance.insert(
                token,
                BufferedProvenance {
                    message_id: env.message_id,
                    edge_id: env.edge_id.clone(),
                    building_id: building_id.clone(),
                    equipment_id: equipment_id.clone(),
                    rows: batch.num_rows(),
                },
            );
            let flushes =
                self.batches
                    .push_with_token(building_id, equipment_id, batch, Some(token));
            let flushes = match flushes {
                Ok(flushes) => flushes,
                Err(error) => {
                    self.provenance.remove(&token);
                    return Err(error.context("buffer canonical live historian batch"));
                }
            };
            if let Err(error) = self.apply_flushes(&flushes, &mut report) {
                self.provenance.remove(&token);
                return Err(error);
            }
        }
        Ok(report)
    }

    pub fn flush_due(&mut self) -> Result<LiveHistorianIngest> {
        self.flush_due_at(Instant::now())
    }

    /// Publish every batch still buffered for this historian, ignoring the
    /// row and time thresholds. Local HTTP ingest calls this before it
    /// acknowledges a sample so a single row is durable without waiting for
    /// the MQTT micro-batch interval.
    pub fn publish_pending(&mut self) -> Result<LiveHistorianIngest> {
        let flushes = self.batches.shutdown_flush()?;
        let mut report = LiveHistorianIngest::default();
        self.apply_flushes(&flushes, &mut report)?;
        Ok(report)
    }

    fn flush_due_at(&mut self, now: Instant) -> Result<LiveHistorianIngest> {
        let flushes = self.batches.flush_due_at(now)?;
        let mut report = LiveHistorianIngest::default();
        self.apply_flushes(&flushes, &mut report)?;
        Ok(report)
    }

    pub fn shutdown_flush(&mut self) -> Result<LiveHistorianIngest> {
        let flushes = self.batches.shutdown_flush()?;
        let mut report = LiveHistorianIngest::default();
        self.apply_flushes(&flushes, &mut report)?;
        if let Some(timestamp) = self.latest_persisted_timestamp_utc {
            self.watermark_store
                .write(timestamp)
                .context("persist live historian telemetry watermark during shutdown")?;
        }
        Ok(report)
    }

    #[cfg(test)]
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
            let mut resolved = Vec::with_capacity(flush.provenance.len());
            for item in &flush.provenance {
                let Some(token) = item.token else {
                    bail!("published historian batch is missing receipt provenance");
                };
                let Some(note) = self.provenance.get(&token) else {
                    bail!("published historian batch {token} has no receipt provenance");
                };
                if note.rows != item.rows
                    || note.building_id != flush.building_id
                    || note.equipment_id != flush.equipment_id
                {
                    bail!("published historian batch does not match its receipt provenance");
                }
                resolved.push((token, note.clone()));
            }
            let proven_rows: usize = resolved.iter().map(|(_, note)| note.rows).sum();
            if proven_rows != flush.rows {
                bail!(
                    "published flush of {} rows does not match receipt provenance of {proven_rows} rows",
                    flush.rows
                );
            }
            for (token, _) in &resolved {
                self.provenance.remove(token);
            }
            report.persisted_rows += flush.rows;
            for (_, note) in resolved {
                report
                    .persisted_message_ids
                    .extend(std::iter::repeat_n(note.message_id, note.rows));
                report.persisted_message_groups.push(PersistedMessageGroup {
                    message_id: note.message_id,
                    scope: self.scope.clone(),
                    edge_id: note.edge_id,
                    building_id: note.building_id,
                    equipment_id: note.equipment_id,
                    rows: note.rows,
                });
            }
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
        if !flushes.is_empty() {
            if let Some(root) = self.budget_root().map(std::path::Path::to_path_buf) {
                if let Err(error) = fdd_store::enforce_budget_throttled(&root, 60) {
                    warn!(%error, "local data budget enforcement failed");
                }
            }
            self.persist_type_stamps();
            if let Some(timestamp) = self.latest_persisted_timestamp_utc {
                // The immutable Parquet objects are canonical. A watermark write
                // failure must never make successfully persisted telemetry look
                // unpersisted or trigger duplicate re-ingest. Keep the in-memory
                // max and retry the watermark on the next flush/shutdown.
                if let Err(error) = self.watermark_store.write(timestamp) {
                    warn!(%error, %timestamp, "live historian telemetry watermark update failed; canonical Parquet remains persisted");
                }
            }
        }
        report.latest_persisted_timestamp_utc = self.latest_persisted_timestamp_utc;
        Ok(())
    }

    /// Hub pool for the 100 GiB budget. A multi-tenant writer root is
    /// `{hub}/tenants/{id}`; eviction has to see the whole pool.
    fn budget_root(&self) -> Option<&std::path::Path> {
        let root = self.parquet_root.as_deref()?;
        let name = root.file_name().and_then(|s| s.to_str())?;
        let parent = root.parent()?;
        if parent.file_name().and_then(|s| s.to_str()) == Some("tenants")
            && !name.is_empty()
            && name != "."
            && name != ".."
        {
            return parent.parent();
        }
        Some(root)
    }

    fn persist_type_stamps(&mut self) {
        let Some(root) = self.parquet_root.as_deref() else {
            self.pending_type_stamps.clear();
            return;
        };
        let pending = std::mem::take(&mut self.pending_type_stamps);
        let mut by_building: BTreeMap<String, BTreeMap<String, String>> = BTreeMap::new();
        for ((building_id, equipment_id), stamp) in pending {
            if stamp.trim().is_empty() {
                continue;
            }
            by_building
                .entry(building_id)
                .or_default()
                .insert(equipment_id, stamp);
        }
        for (building_id, stamps) in by_building {
            let mut merged = equipment_types::load_type_map(root, Some(building_id.as_str()));
            merged.extend(stamps);
            if let Err(error) = equipment_types::write_type_map(root, &building_id, &merged) {
                warn!(%error, building_id, "live historian equipment type registry update failed");
            }
        }
    }
}

enum WriterCommand {
    Ingest {
        scope: String,
        envelope: TelemetryEnvelope,
        reply: tokio::sync::oneshot::Sender<Result<LiveHistorianIngest>>,
    },
    Flush {
        graceful: bool,
        reply: tokio::sync::oneshot::Sender<Result<LiveHistorianIngest>>,
    },
    PublishPending {
        scope: String,
        reply: tokio::sync::oneshot::Sender<Result<LiveHistorianIngest>>,
    },
    #[cfg(test)]
    Probe {
        reply: tokio::sync::oneshot::Sender<bool>,
    },
    Shutdown,
}

/// Owns every canonical live historian and performs Parquet publication on one
/// blocking thread. Request handlers await the reply; they do not publish from
/// the async runtime or the shared Tokio blocking pool.
pub struct LiveWriter {
    tx: std::sync::mpsc::Sender<WriterCommand>,
    thread: Option<std::thread::JoinHandle<()>>,
}

impl LiveWriter {
    pub fn start() -> Self {
        let (tx, rx) = std::sync::mpsc::channel();
        let thread = std::thread::Builder::new()
            .name("openfdd-live-writer".into())
            .spawn(move || writer_loop(rx))
            .expect("openfdd live writer thread");
        Self {
            tx,
            thread: Some(thread),
        }
    }

    pub async fn ingest(
        &self,
        scope: &str,
        envelope: &TelemetryEnvelope,
    ) -> Result<LiveHistorianIngest> {
        let (reply_tx, reply_rx) = tokio::sync::oneshot::channel();
        self.tx
            .send(WriterCommand::Ingest {
                scope: scope.to_string(),
                envelope: envelope.clone(),
                reply: reply_tx,
            })
            .map_err(|_| anyhow!("live historian writer stopped"))?;
        reply_rx
            .await
            .map_err(|_| anyhow!("live historian writer dropped the reply"))?
    }

    pub async fn flush(&self, graceful: bool) -> Result<LiveHistorianIngest> {
        let (reply_tx, reply_rx) = tokio::sync::oneshot::channel();
        self.tx
            .send(WriterCommand::Flush {
                graceful,
                reply: reply_tx,
            })
            .map_err(|_| anyhow!("live historian writer stopped"))?;
        reply_rx
            .await
            .map_err(|_| anyhow!("live historian writer dropped the reply"))?
    }

    pub async fn publish_pending(&self, scope: &str) -> Result<LiveHistorianIngest> {
        let (reply_tx, reply_rx) = tokio::sync::oneshot::channel();
        self.tx
            .send(WriterCommand::PublishPending {
                scope: scope.to_string(),
                reply: reply_tx,
            })
            .map_err(|_| anyhow!("live historian writer stopped"))?;
        reply_rx
            .await
            .map_err(|_| anyhow!("live historian writer dropped the reply"))?
    }

    #[cfg(test)]
    pub async fn runs_without_tokio_context(&self) -> Result<bool> {
        let (reply_tx, reply_rx) = tokio::sync::oneshot::channel();
        self.tx
            .send(WriterCommand::Probe { reply: reply_tx })
            .map_err(|_| anyhow!("live historian writer stopped"))?;
        reply_rx
            .await
            .map_err(|_| anyhow!("live historian writer dropped the reply"))
    }
}

impl Drop for LiveWriter {
    fn drop(&mut self) {
        let _ = self.tx.send(WriterCommand::Shutdown);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

fn writer_loop(rx: std::sync::mpsc::Receiver<WriterCommand>) {
    let mut historians: HashMap<String, LiveHistorian> = HashMap::new();
    while let Ok(command) = rx.recv() {
        match command {
            WriterCommand::Shutdown => break,
            WriterCommand::Ingest {
                scope,
                envelope,
                reply,
            } => {
                let _ = reply.send(ingest_scoped(&mut historians, &scope, &envelope));
            }
            WriterCommand::Flush { graceful, reply } => {
                let _ = reply.send(flush_all(&mut historians, graceful));
            }
            WriterCommand::PublishPending { scope, reply } => {
                let _ = reply.send(publish_pending_scope(&mut historians, &scope));
            }
            #[cfg(test)]
            WriterCommand::Probe { reply } => {
                let _ = reply.send(tokio::runtime::Handle::try_current().is_err());
            }
        }
    }
}

fn ingest_scoped(
    historians: &mut HashMap<String, LiveHistorian>,
    scope: &str,
    envelope: &TelemetryEnvelope,
) -> Result<LiveHistorianIngest> {
    if !historians.contains_key(scope) {
        let writer = LiveHistorian::from_env_scoped_for(scope)?;
        historians.insert(scope.to_string(), writer);
    }
    let Some(writer) = historians.get_mut(scope) else {
        bail!("live historian writer missing after insert");
    };
    writer.ingest_envelope(envelope)
}

fn publish_pending_scope(
    historians: &mut HashMap<String, LiveHistorian>,
    scope: &str,
) -> Result<LiveHistorianIngest> {
    let Some(historian) = historians.get_mut(scope) else {
        return Ok(LiveHistorianIngest::default());
    };
    historian.publish_pending()
}

fn flush_all(
    historians: &mut HashMap<String, LiveHistorian>,
    graceful: bool,
) -> Result<LiveHistorianIngest> {
    let mut combined = LiveHistorianIngest::default();
    for historian in historians.values_mut() {
        let report = if graceful {
            historian.shutdown_flush()?
        } else {
            historian.flush_due()?
        };
        combined.flushes += report.flushes;
        combined.persisted_rows += report.persisted_rows;
        combined
            .persisted_message_ids
            .extend(report.persisted_message_ids);
        combined
            .persisted_message_groups
            .extend(report.persisted_message_groups);
        combined.latest_persisted_timestamp_utc = combined
            .latest_persisted_timestamp_utc
            .max(report.latest_persisted_timestamp_utc);
    }
    Ok(combined)
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
    let mut duplicates = Vec::new();

    for point in &env.points {
        let Some((building_id, equipment_id, role)) = point_identity(point)? else {
            skipped += 1;
            continue;
        };
        let Some(value) = role_value(point)? else {
            skipped += 1;
            continue;
        };
        let roles = grouped
            .entry((building_id.clone(), equipment_id.clone()))
            .or_default();
        if roles.contains_key(&role) {
            duplicates.push(DuplicateRole {
                building_id,
                equipment_id,
                role,
            });
            skipped += 1;
            continue;
        }
        roles.insert(role, value);
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
    Ok((out, eligible, skipped, duplicates))
}

fn collect_type_stamps(env: &TelemetryEnvelope, out: &mut BTreeMap<EquipmentKey, String>) {
    for point in &env.points {
        let Some(building_id) = string_tag(point, TAG_BUILDING_ID) else {
            continue;
        };
        let Some(equipment_id) = string_tag(point, TAG_EQUIPMENT_ID) else {
            continue;
        };
        let Ok(building_id) = safe_partition_value(building_id, TAG_BUILDING_ID) else {
            continue;
        };
        let Ok(equipment_id) = safe_partition_value(equipment_id, TAG_EQUIPMENT_ID) else {
            continue;
        };
        if let Some(stamp) = equipment_type_stamp(point) {
            out.insert((building_id, equipment_id), stamp);
        }
    }
}

fn equipment_type_stamp(point: &TelemetryPoint) -> Option<String> {
    string_tag(point, TAG_EQUIPMENT_TYPE)
        .or_else(|| string_tag(point, TAG_EQUIP_TYPE))
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
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

fn non_finite_quality_marker(point: &TelemetryPoint) -> bool {
    point
        .tags
        .get("non_finite_quality")
        .and_then(|value| value.as_bool())
        == Some(true)
}

fn numeric_role_value(point: &TelemetryPoint, good: bool) -> Option<f64> {
    if good {
        point.value.as_f64()
    } else if non_finite_quality_marker(point) {
        // Arrow/Parquet can represent NaN even though JSON cannot represent the
        // originating BACnet Inf/NaN. Only that marker is a range fault.
        // Other bad poll results stay null so a circuit-open or BACnet error
        // class does not become an SV-RANGE hit.
        Some(f64::NAN)
    } else {
        None
    }
}

fn role_value(point: &TelemetryPoint) -> Result<Option<RoleValue>> {
    let good = matches!(point.quality, Quality::Good | Quality::Uncertain);
    match point.kind {
        Some(ValueKind::Number) => Ok(Some(RoleValue::Number(numeric_role_value(point, good)))),
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
        None if point.value.is_number() => {
            Ok(Some(RoleValue::Number(numeric_role_value(point, good))))
        }
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
    use datafusion::arrow::array::Array;
    use datafusion::prelude::SessionContext;
    use fdd_rules::{rule_params, substitute_sql};
    use fdd_sql::{register_historian_building, run_sql};
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
        let env = envelope(vec![point("sat", json!(55.0))]);
        let (groups, eligible, skipped, duplicates) = normalized_batches(&env).unwrap();
        assert_eq!(eligible, 1);
        assert_eq!(skipped, 0);
        assert!(duplicates.is_empty());
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
        let (groups, eligible, skipped, _) = normalized_batches(&envelope(vec![p])).unwrap();
        assert!(groups.is_empty());
        assert_eq!(eligible, 0);
        assert_eq!(skipped, 1);
    }

    fn mark_non_finite(point: &mut TelemetryPoint) {
        point.tags.insert("non_finite_quality".into(), json!(true));
    }

    #[test]
    fn bad_numeric_quality_preserves_schema_as_nan_marker() {
        let mut p = point("sat", json!(55.0));
        p.quality = Quality::Bad;
        mark_non_finite(&mut p);
        let (groups, _, _, _) = normalized_batches(&envelope(vec![p])).unwrap();
        let batch = groups.values().next().unwrap();
        assert_eq!(batch.schema().field(1).name(), "sat");
        let values = batch
            .column(1)
            .as_any()
            .downcast_ref::<Float64Array>()
            .unwrap();
        assert!(values.value(0).is_nan());
    }

    #[test]
    fn generic_bad_quality_stays_null_instead_of_a_range_marker() {
        let mut p = point("sat", json!(55.0));
        p.quality = Quality::Bad;
        let (groups, eligible, _, _) = normalized_batches(&envelope(vec![p])).unwrap();
        assert_eq!(eligible, 1);
        let batch = groups.values().next().unwrap();
        let values = batch
            .column(1)
            .as_any()
            .downcast_ref::<Float64Array>()
            .unwrap();
        assert!(values.is_null(0));
    }

    async fn sv_range_fault_hours(sample: TelemetryPoint) -> f64 {
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
        live.ingest_envelope(&envelope(vec![sample])).unwrap();

        let ctx = SessionContext::new();
        register_historian_building(&ctx, tmp.path(), "BUILDING_100")
            .await
            .unwrap();
        let optional = [
            "oa_t",
            "mat",
            "zone_t",
            "rat",
            "chw_supply_t",
            "chw_return_t",
            "hw_supply_t",
            "hw_return_t",
            "oa_h",
            "duct_static",
            "fan_status",
            "fan_cmd",
            "pump_status",
            "chw_pump_cmd",
            "chiller_status",
            "kwh",
            "electric_kw",
            "electric_kwh",
        ];
        let nulls = optional
            .iter()
            .map(|role| format!("CAST(NULL AS DOUBLE) AS {role}"))
            .collect::<Vec<_>>()
            .join(", ");
        let enriched = ctx
            .sql(&format!("SELECT history.*, {nulls} FROM history"))
            .await
            .unwrap();
        ctx.deregister_table("history").unwrap();
        ctx.register_table("history", enriched.into_view()).unwrap();

        let sql = std::fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../sql_rules/sv_range.sql"),
        )
        .unwrap();
        let mut params = rule_params(300.0, 0);
        params.insert("RANGE_SCALE_TEMPERATURE".into(), "1".into());
        params.insert("RANGE_SCALE_HUMIDITY".into(), "1".into());
        params.insert("RANGE_SCALE_PRESSURE".into(), "1".into());
        let sql = substitute_sql(&sql, &params);
        let result = run_sql(&ctx, &sql).await.unwrap();
        result.rows[0]
            .get("fault_hours")
            .and_then(|value| value.as_f64())
            .unwrap()
    }

    #[tokio::test]
    async fn bad_quality_flows_through_historian_nan_to_sv_range() {
        let mut bad = point("sat", json!(55.0));
        bad.quality = Quality::Bad;
        mark_non_finite(&mut bad);
        assert_eq!(sv_range_fault_hours(bad).await, 300.0 / 3600.0);
    }

    #[tokio::test]
    async fn generic_poll_error_does_not_sv_range_fault() {
        let mut bad = point("sat", json!(55.0));
        bad.quality = Quality::Bad;
        assert_eq!(sv_range_fault_hours(bad).await, 0.0);
    }

    #[test]
    fn duplicate_role_drops_later_point_and_keeps_unique_points() {
        let env = envelope(vec![
            point("occ_mode", json!(1.0)),
            point("occ_mode", json!(0.0)),
            point("sat", json!(55.0)),
        ]);
        let (groups, eligible, skipped, duplicates) = normalized_batches(&env).unwrap();
        assert_eq!(eligible, 2);
        assert_eq!(skipped, 1);
        assert_eq!(duplicates.len(), 1);
        assert_eq!(duplicates[0].building_id, "BUILDING_100");
        assert_eq!(duplicates[0].equipment_id, "AHU_1");
        assert_eq!(duplicates[0].role, "occ_mode");
        let batch = groups.values().next().unwrap();
        assert!(batch.schema().index_of("occ_mode").is_ok());
        assert!(batch.schema().index_of("sat").is_ok());
    }

    #[test]
    fn local_live_writer_flushes_and_persists_watermark() {
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
        let mut point = point("sat", json!(55.0));
        point
            .tags
            .insert("equipment_type".into(), json!("zone_other"));
        let env = envelope(vec![point]);
        let message_id = env.message_id;
        let report = live.ingest_envelope(&env).unwrap();
        assert_eq!(report.persisted_rows, 1);
        assert_eq!(report.flushes, 1);
        assert_eq!(report.persisted_message_ids, vec![message_id]);
        let types_path = tmp
            .path()
            .join("building=BUILDING_100/equipment_types.json");
        let types: BTreeMap<String, String> =
            serde_json::from_str(&std::fs::read_to_string(types_path).unwrap()).unwrap();
        assert_eq!(types.get("AHU_1").map(String::as_str), Some("zone_other"));
        assert_eq!(
            report.latest_persisted_timestamp_utc.unwrap().to_rfc3339(),
            "2026-08-21T12:00:00+00:00"
        );
        let partition = tmp
            .path()
            .join("history/building_id=BUILDING_100/equipment_id=AHU_1/year=2026/month=08");
        assert_eq!(std::fs::read_dir(partition).unwrap().count(), 1);
        assert!(tmp.path().join(LATEST_TELEMETRY_WATERMARK).is_file());

        let restarted = LiveHistorian::from_config(&config).unwrap();
        assert_eq!(
            restarted
                .latest_persisted_timestamp_utc()
                .unwrap()
                .to_rfc3339(),
            "2026-08-21T12:00:00+00:00"
        );
    }

    #[test]
    fn s3_object_key_keeps_configured_prefix_and_canonical_path() {
        let key = object_path(
            "tenant-a",
            Path::new(
                "history/building_id=BUILDING_100/equipment_id=AHU_1/year=2026/month=08/part-x.parquet",
            ),
        )
        .unwrap();
        assert_eq!(
            key.as_ref(),
            "tenant-a/history/building_id=BUILDING_100/equipment_id=AHU_1/year=2026/month=08/part-x.parquet"
        );
    }

    fn tagged_point(equipment_id: &str, role: &str, value: f64) -> TelemetryPoint {
        TelemetryPoint {
            id: format!("point-{equipment_id}-{role}"),
            display_name: Some(role.into()),
            kind: Some(ValueKind::Number),
            value: json!(value),
            unit: None,
            quality: Quality::Good,
            tags: json!({
                "building_id": "building-local",
                "equipment_id": equipment_id,
                "role": role,
            })
            .as_object()
            .cloned()
            .unwrap(),
        }
    }

    fn envelope_for(edge_id: &str, points: Vec<TelemetryPoint>) -> TelemetryEnvelope {
        let mut env =
            TelemetryEnvelope::new("building-local", edge_id, Protocol::Bacnet, 1, points);
        env.observed_at = DateTime::parse_from_rfc3339("2026-08-21T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        env
    }

    #[test]
    fn time_flush_provenance_lists_only_published_batches() {
        let tmp = TempDir::new().unwrap();
        let config = HistorianConfig {
            storage_url: StorageUrl::File {
                root: tmp.path().to_path_buf(),
            },
            flush_rows: 10,
            flush_seconds: 60,
            target_file_mb: 128,
            compaction_min_files: 8,
            compaction_enabled: true,
            query_memory_mb: 512,
            spill_directory: None,
            legacy_parquet_root: None,
        };
        let mut live =
            LiveHistorian::from_config_with_scope(&config, "tenant=-;building=building-local")
                .unwrap();
        let first = envelope_for("edge-a", vec![tagged_point("equipment-a", "sat", 55.0)]);
        let second = envelope_for("edge-b", vec![tagged_point("equipment-b", "sat", 56.0)]);
        let first_id = first.message_id;
        let second_id = second.message_id;
        assert!(live
            .ingest_envelope(&first)
            .unwrap()
            .persisted_message_groups
            .is_empty());
        assert!(live
            .ingest_envelope(&second)
            .unwrap()
            .persisted_message_groups
            .is_empty());
        let report = live
            .flush_due_at(std::time::Instant::now() + std::time::Duration::from_secs(120))
            .unwrap();
        let mut groups = report.persisted_message_groups;
        groups.sort_by_key(|group| group.edge_id.clone());
        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].message_id, first_id);
        assert_eq!(groups[0].edge_id, "edge-a");
        assert_eq!(groups[0].equipment_id, "equipment-a");
        assert_eq!(groups[0].rows, 1);
        assert_eq!(groups[0].scope, "tenant=-;building=building-local");
        assert_eq!(groups[1].message_id, second_id);
        assert_eq!(groups[1].edge_id, "edge-b");
        assert_eq!(report.persisted_rows, 2);

        let third = envelope_for("edge-c", vec![tagged_point("equipment-c", "sat", 57.0)]);
        let third_id = third.message_id;
        assert!(live
            .ingest_envelope(&third)
            .unwrap()
            .persisted_message_groups
            .is_empty());
        let later = live.shutdown_flush().unwrap();
        assert_eq!(later.persisted_message_groups.len(), 1);
        assert_eq!(later.persisted_message_groups[0].message_id, third_id);
        assert_eq!(later.persisted_message_groups[0].edge_id, "edge-c");
    }

    #[tokio::test]
    async fn dedicated_writer_publishes_outside_the_tokio_runtime() {
        let writer = LiveWriter::start();
        assert!(writer.runs_without_tokio_context().await.unwrap());
    }

    /// #1064: a multi-tenant hub has no process-global tenant. The trusted
    /// scope (`tenant={tid};building={bid}`) is the partition.
    #[test]
    fn multi_tenant_scope_partitions_without_process_tenant_env() {
        with_scoped_storage(
            &[
                ("OPENFDD_MULTI_TENANT", Some("1")),
                ("OPENFDD_TENANT_ID", None),
            ],
            |root| {
                let mut live =
                    LiveHistorian::from_env_scoped_for("tenant=acme;building=ACME").unwrap();
                let report = live
                    .ingest_envelope(&scoped_envelope("ACME", "unit-1"))
                    .unwrap();
                assert!(report.persisted_rows >= 1);
                assert_eq!(report.flushes, 1);
                assert_eq!(
                    live.parquet_root.as_deref(),
                    Some(root.join("tenants/acme").as_path())
                );
                let partition = root.join(
                    "tenants/acme/history/building_id=ACME/equipment_id=unit-1/year=2026/month=08",
                );
                assert_eq!(std::fs::read_dir(&partition).unwrap().count(), 1);
                assert_eq!(live.budget_root(), Some(root));
                assert!(!root.join("history").exists());
            },
        );
    }

    #[test]
    fn multi_tenant_scope_tenant_wins_over_process_env() {
        with_scoped_storage(
            &[
                ("OPENFDD_MULTI_TENANT", Some("1")),
                ("OPENFDD_TENANT_ID", Some("other-tenant")),
            ],
            |root| {
                let live = LiveHistorian::from_env_scoped_for("tenant=acme;building=ACME").unwrap();
                assert_eq!(
                    live.parquet_root.as_deref(),
                    Some(root.join("tenants/acme").as_path())
                );
            },
        );
    }

    #[test]
    fn multi_tenant_legacy_dash_scope_uses_process_tenant() {
        with_scoped_storage(
            &[
                ("OPENFDD_MULTI_TENANT", Some("1")),
                ("OPENFDD_TENANT_ID", Some("site-tenant")),
            ],
            |root| {
                let mut live =
                    LiveHistorian::from_env_scoped_for("tenant=-;building=building-local").unwrap();
                let report = live
                    .ingest_envelope(&scoped_envelope("building-local", "unit-1"))
                    .unwrap();
                assert!(report.persisted_rows >= 1);
                assert_eq!(
                    live.parquet_root.as_deref(),
                    Some(root.join("tenants/site-tenant").as_path())
                );
            },
        );
    }

    #[test]
    fn multi_tenant_rejects_empty_or_dash_scope_without_tenant() {
        with_scoped_storage(
            &[
                ("OPENFDD_MULTI_TENANT", Some("1")),
                ("OPENFDD_TENANT_ID", None),
            ],
            |_root| {
                for scope in [
                    "tenant=-;building=ACME",
                    "tenant=;building=ACME",
                    "building=ACME",
                ] {
                    let error = LiveHistorian::from_env_scoped_for(scope).unwrap_err();
                    let message = format!("{error:#}");
                    assert!(
                        message.contains("trusted scope tenant"),
                        "scope {scope} produced {message}"
                    );
                }
            },
        );
    }

    #[test]
    fn single_tenant_dash_scope_stays_on_hub_root() {
        with_scoped_storage(
            &[
                ("OPENFDD_MULTI_TENANT", Some("0")),
                ("OPENFDD_TENANT_ID", None),
            ],
            |root| {
                let mut live =
                    LiveHistorian::from_env_scoped_for("tenant=-;building=building-local").unwrap();
                let report = live
                    .ingest_envelope(&scoped_envelope("building-local", "unit-1"))
                    .unwrap();
                assert!(report.persisted_rows >= 1);
                assert_eq!(live.parquet_root.as_deref(), Some(root));
                assert!(!root.join("tenants").exists());
            },
        );
    }

    fn scoped_envelope(building_id: &str, equipment_id: &str) -> TelemetryEnvelope {
        let mut env = TelemetryEnvelope::new(
            "site-scope",
            "edge-1",
            Protocol::Bacnet,
            1,
            vec![TelemetryPoint {
                id: "point-1".into(),
                display_name: Some("sat".into()),
                kind: Some(ValueKind::Number),
                value: json!(55.0),
                unit: None,
                quality: Quality::Good,
                tags: json!({
                    "building_id": building_id,
                    "equipment_id": equipment_id,
                    "role": "sat",
                })
                .as_object()
                .cloned()
                .unwrap(),
            }],
        );
        env.observed_at = DateTime::parse_from_rfc3339("2026-08-21T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        env
    }

    /// Apply `OPENFDD_*` for one test, then put the previous values back.
    ///
    /// The shared env lock serializes this with other modules that mutate the
    /// same process variables. Restore runs on drop, including panic.
    fn with_scoped_storage(extra: &[(&'static str, Option<&str>)], body: impl FnOnce(&Path)) {
        let tmp = TempDir::new().unwrap();
        let storage = format!("file://{}", tmp.path().display());
        let mut pairs: Vec<(&'static str, Option<&str>)> = vec![
            ("OPENFDD_STORAGE_URL", Some(storage.as_str())),
            ("OPENFDD_PARQUET_FLUSH_ROWS", Some("1")),
            ("OPENFDD_PARQUET_FLUSH_SECONDS", Some("3600")),
            ("OPENFDD_PARQUET_ROOT", None),
        ];
        pairs.extend_from_slice(extra);
        let _env = ScopedEnv::apply(&pairs);
        body(tmp.path());
    }

    struct ScopedEnv {
        _lock: std::sync::MutexGuard<'static, ()>,
        saved: Vec<(&'static str, Option<String>)>,
    }

    impl ScopedEnv {
        fn apply(pairs: &[(&'static str, Option<&str>)]) -> Self {
            let lock = crate::test_env_lock::lock_env();
            let saved = pairs
                .iter()
                .map(|(key, _)| (*key, std::env::var(key).ok()))
                .collect();
            for (key, value) in pairs {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
            Self { _lock: lock, saved }
        }
    }

    impl Drop for ScopedEnv {
        fn drop(&mut self) {
            for (key, value) in self.saved.drain(..) {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
        }
    }
}
