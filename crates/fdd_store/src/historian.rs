//! Canonical Open-FDD historian storage contract.
//!
//! Parquet is the durable historian format. Arrow remains the in-memory format,
//! and DataFusion remains the query engine. This module intentionally keeps the
//! Phase-1 contract small: URL/config parsing, safe Hive partition paths, and a
//! crash-safe local filesystem backend. S3/object-store execution is layered on
//! the same contract in the next implementation phase rather than leaking
//! provider-specific calls through ingest/query code.

use std::env;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use anyhow::{anyhow, bail, Context, Result};
use chrono::{DateTime, Datelike, Utc};
use serde::Serialize;

pub const DEFAULT_FLUSH_ROWS: usize = 5_000;
pub const DEFAULT_FLUSH_SECONDS: u64 = 60;
pub const DEFAULT_TARGET_FILE_MB: u64 = 128;
pub const DEFAULT_COMPACTION_MIN_FILES: usize = 8;
pub const DEFAULT_QUERY_MEMORY_MB: u64 = 512;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "backend", rename_all = "snake_case")]
pub enum StorageUrl {
    File { root: PathBuf },
    S3 { bucket: String, prefix: String },
}

impl StorageUrl {
    /// Parse the generic Open-FDD storage URL.
    ///
    /// Supported forms:
    /// - `file:///data/openfdd`
    /// - `/data/openfdd` (backwards-compatible plain local path)
    /// - `s3://bucket`
    /// - `s3://bucket/optional/prefix`
    pub fn parse(raw: &str) -> Result<Self> {
        let raw = raw.trim();
        if raw.is_empty() {
            bail!("storage URL cannot be empty");
        }
        if let Some(rest) = raw.strip_prefix("file://") {
            if rest.is_empty() {
                bail!("file:// storage URL requires a path");
            }
            return Ok(Self::File {
                root: PathBuf::from(rest),
            });
        }
        if let Some(rest) = raw.strip_prefix("s3://") {
            let mut parts = rest.splitn(2, '/');
            let bucket = parts.next().unwrap_or_default().trim();
            if bucket.is_empty() {
                bail!("s3:// storage URL requires a bucket");
            }
            validate_segment(bucket, "bucket")?;
            let prefix = parts
                .next()
                .unwrap_or_default()
                .trim_matches('/')
                .to_string();
            if prefix.split('/').any(|p| p == "..") {
                bail!("s3 storage prefix cannot contain '..'");
            }
            return Ok(Self::S3 {
                bucket: bucket.to_string(),
                prefix,
            });
        }
        if raw.contains("://") {
            bail!("unsupported storage URL scheme: {raw}");
        }
        Ok(Self::File {
            root: PathBuf::from(raw),
        })
    }

    pub fn display_redacted(&self) -> String {
        match self {
            Self::File { root } => format!("file://{}", root.display()),
            Self::S3 { bucket, prefix } if prefix.is_empty() => format!("s3://{bucket}"),
            Self::S3 { bucket, prefix } => format!("s3://{bucket}/{prefix}"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HistorianConfig {
    pub storage_url: StorageUrl,
    pub flush_rows: usize,
    pub flush_seconds: u64,
    pub target_file_mb: u64,
    pub compaction_min_files: usize,
    pub compaction_enabled: bool,
    pub query_memory_mb: u64,
    pub spill_directory: Option<PathBuf>,
    /// Set when configuration was inherited from the pre-canonical
    /// `OPENFDD_PARQUET_ROOT` path. This is surfaced for migration diagnostics;
    /// it is not silently rewritten into the new partition layout.
    pub legacy_parquet_root: Option<PathBuf>,
}

/// Local filesystem root for package-ingest / analytics PathBuf helpers.
///
/// Precedence matches live historian config for local paths:
/// 1. `OPENFDD_STORAGE_URL` when it is `file://…` or a plain path
/// 2. legacy `OPENFDD_PARQUET_ROOT`
///
/// Returns `None` when unset, when `OPENFDD_STORAGE_URL` is `s3://…` (callers
/// keep PathBuf-only fallbacks), or when the storage URL cannot be parsed.
pub fn local_file_root_from_env() -> Option<PathBuf> {
    if let Ok(raw) = env::var("OPENFDD_STORAGE_URL") {
        match StorageUrl::parse(&raw) {
            Ok(StorageUrl::File { root }) => return Some(root),
            Ok(StorageUrl::S3 { .. }) | Err(_) => {}
        }
    }
    env::var("OPENFDD_PARQUET_ROOT")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
}

impl HistorianConfig {
    pub fn from_env() -> Result<Self> {
        let (storage_url, legacy_parquet_root) = if let Ok(raw) = env::var("OPENFDD_STORAGE_URL") {
            (StorageUrl::parse(&raw)?, None)
        } else if let Ok(raw) = env::var("OPENFDD_PARQUET_ROOT") {
            let path = PathBuf::from(raw);
            (StorageUrl::File { root: path.clone() }, Some(path))
        } else {
            let workspace = env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
            let root = PathBuf::from(workspace).join("data/openfdd");
            (StorageUrl::File { root }, None)
        };

        Ok(Self {
            storage_url,
            flush_rows: env_usize("OPENFDD_PARQUET_FLUSH_ROWS", DEFAULT_FLUSH_ROWS)?,
            flush_seconds: env_u64("OPENFDD_PARQUET_FLUSH_SECONDS", DEFAULT_FLUSH_SECONDS)?,
            target_file_mb: env_u64("OPENFDD_PARQUET_TARGET_FILE_MB", DEFAULT_TARGET_FILE_MB)?,
            compaction_min_files: env_usize(
                "OPENFDD_COMPACTION_MIN_FILES",
                DEFAULT_COMPACTION_MIN_FILES,
            )?,
            compaction_enabled: env_bool("OPENFDD_COMPACTION_ENABLED", true)?,
            query_memory_mb: env_u64("OPENFDD_QUERY_MEMORY_MB", DEFAULT_QUERY_MEMORY_MB)?,
            spill_directory: env::var("OPENFDD_DATAFUSION_SPILL_DIR")
                .ok()
                .filter(|s| !s.trim().is_empty())
                .map(PathBuf::from),
            legacy_parquet_root,
        })
    }
}

fn env_u64(name: &str, default: u64) -> Result<u64> {
    match env::var(name) {
        Ok(v) => v
            .parse::<u64>()
            .with_context(|| format!("{name} must be a positive integer"))
            .and_then(|n| {
                if n == 0 {
                    bail!("{name} must be greater than zero")
                }
                Ok(n)
            }),
        Err(_) => Ok(default),
    }
}

fn env_usize(name: &str, default: usize) -> Result<usize> {
    let n = env_u64(name, default as u64)?;
    usize::try_from(n).map_err(|_| anyhow!("{name} is too large"))
}

fn env_bool(name: &str, default: bool) -> Result<bool> {
    let Ok(raw) = env::var(name) else {
        return Ok(default);
    };
    match raw.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => bail!("{name} must be true/false"),
    }
}

/// Canonical relative partition path for equipment telemetry.
pub fn history_partition_path(
    building_id: &str,
    equipment_id: &str,
    ts: DateTime<Utc>,
) -> Result<PathBuf> {
    let building = safe_partition_value(building_id, "building_id")?;
    let equipment = safe_partition_value(equipment_id, "equipment_id")?;
    Ok(PathBuf::from("history")
        .join(format!("building_id={building}"))
        .join(format!("equipment_id={equipment}"))
        .join(format!("year={:04}", ts.year()))
        .join(format!("month={:02}", ts.month())))
}

/// Canonical relative partition path for weather telemetry.
pub fn weather_partition_path(building_id: &str, ts: DateTime<Utc>) -> Result<PathBuf> {
    let building = safe_partition_value(building_id, "building_id")?;
    Ok(PathBuf::from("weather")
        .join(format!("building_id={building}"))
        .join(format!("year={:04}", ts.year()))
        .join(format!("month={:02}", ts.month())))
}

pub fn safe_partition_value(value: &str, field: &str) -> Result<String> {
    let value = value.trim();
    if value.is_empty() {
        bail!("{field} cannot be empty");
    }
    validate_segment(value, field)?;
    Ok(value.to_string())
}

/// Wave L — resolve a tenant-partitioned historian root.
///
/// - `tenant_id = None` → return `base` unchanged (single-tenant / flag OFF).
/// - `tenant_id = Some(tid)` → `{base}/tenants/{tid}` with the same relative
///   Hive layout underneath (`history/building_id=…`, …).
///
/// Isolation is **path / provider scoping**, not `WHERE tenant_id` over a shared
/// registered mega-table. Rejects unsafe tenant ids (same rules as Hive segments).
pub fn tenant_storage_root(base: &Path, tenant_id: Option<&str>) -> Result<PathBuf> {
    let Some(raw) = tenant_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(base.to_path_buf());
    };
    let tid = safe_partition_value(raw, "tenant_id")?;
    Ok(base.join("tenants").join(tid))
}

/// Relative historian prefix under a storage root (empty when single-tenant root).
pub fn tenant_storage_prefix(tenant_id: Option<&str>) -> Result<String> {
    let Some(raw) = tenant_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(String::new());
    };
    let tid = safe_partition_value(raw, "tenant_id")?;
    Ok(format!("tenants/{tid}"))
}

/// Where a building-scoped Parquet read resolved under Wave U V7 dual-read.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BuildingReadSource {
    /// `{hub}/tenants/{tid}/…`
    TenantPartition,
    /// Hub-root `building=*` / `history/building_id=*` (pre-migrate layout).
    HubRoot,
}

/// Resolved storage root for [`register_historian_building`]-style callers.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BuildingReadRoot {
    pub root: PathBuf,
    pub source: BuildingReadSource,
    /// Tenant id when [`BuildingReadSource::TenantPartition`].
    pub tenant_id: Option<String>,
}

/// True when `storage_root` has canonical Hive and/or legacy sidecar Parquet for `building_id`.
pub fn building_history_present(storage_root: &Path, building_id: &str) -> bool {
    let Ok(bid) = safe_partition_value(building_id.trim(), "building_id") else {
        return false;
    };
    let canonical = storage_root
        .join("history")
        .join(format!("building_id={bid}"));
    let legacy = storage_root.join(format!("building={bid}"));
    dir_has_parquet(&canonical) || dir_has_parquet(&legacy) || legacy.is_dir()
}

fn dir_has_parquet(root: &Path) -> bool {
    if !root.is_dir() {
        return false;
    }
    fn walk(dir: &Path, depth: usize) -> bool {
        if depth > 8 {
            return false;
        }
        let Ok(rd) = fs::read_dir(dir) else {
            return false;
        };
        for entry in rd.flatten() {
            let path = entry.path();
            if path.is_file() {
                if path
                    .extension()
                    .and_then(|x| x.to_str())
                    .map(|x| x.eq_ignore_ascii_case("parquet"))
                    .unwrap_or(false)
                {
                    return true;
                }
            } else if path.is_dir() && walk(&path, depth + 1) {
                return true;
            }
        }
        false
    }
    walk(root, 0)
}

/// Dual-read resolver (Wave U V7 / Soft-OPEN `wave-o1-tenant-path-migrate`).
///
/// Preference order:
/// 1. `preferred_tenant` → `{hub}/tenants/{tid}/…` when that tree has the building
/// 2. Unique `tenants/*/…` hit for the building (hub_admin / unscoped migrate)
/// 3. Hub-root `{hub}/building=…` / `history/building_id=…`
///
/// Ambiguous multi-tenant hits without a preferred tenant fall through to hub-root
/// (fail closed for cross-tenant label collisions — do not pick a random tenant).
pub fn resolve_building_read_root(
    hub_base: &Path,
    preferred_tenant: Option<&str>,
    building_id: &str,
) -> Result<BuildingReadRoot> {
    let bid = safe_partition_value(building_id.trim(), "building_id")?;

    if let Some(raw) = preferred_tenant.map(str::trim).filter(|s| !s.is_empty()) {
        let tid = safe_partition_value(raw, "tenant_id")?;
        let tenant_root = hub_base.join("tenants").join(&tid);
        if building_history_present(&tenant_root, &bid) {
            return Ok(BuildingReadRoot {
                root: tenant_root,
                source: BuildingReadSource::TenantPartition,
                tenant_id: Some(tid),
            });
        }
    }

    let mut tenant_hits: Vec<(String, PathBuf)> = Vec::new();
    let tenants_dir = hub_base.join("tenants");
    if tenants_dir.is_dir() {
        if let Ok(rd) = fs::read_dir(&tenants_dir) {
            for entry in rd.flatten() {
                if !entry.path().is_dir() {
                    continue;
                }
                let Some(name) = entry.file_name().to_str().map(str::to_string) else {
                    continue;
                };
                if name.starts_with('.') {
                    continue;
                }
                if safe_partition_value(&name, "tenant_id").is_err() {
                    continue;
                }
                let root = entry.path();
                if building_history_present(&root, &bid) {
                    tenant_hits.push((name, root));
                }
            }
        }
    }
    tenant_hits.sort_by(|a, b| a.0.cmp(&b.0));
    if tenant_hits.len() == 1 {
        let (tid, root) = tenant_hits.remove(0);
        return Ok(BuildingReadRoot {
            root,
            source: BuildingReadSource::TenantPartition,
            tenant_id: Some(tid),
        });
    }

    Ok(BuildingReadRoot {
        root: hub_base.to_path_buf(),
        source: BuildingReadSource::HubRoot,
        tenant_id: None,
    })
}

/// Inventory hub-root `building=*` / `history/building_id=*` plus `tenants/{tid}/…`.
pub fn list_building_ids(hub_base: &Path) -> Vec<String> {
    let mut buildings = Vec::new();
    collect_building_ids_under(hub_base, &mut buildings);
    let tenants_dir = hub_base.join("tenants");
    if tenants_dir.is_dir() {
        if let Ok(rd) = fs::read_dir(&tenants_dir) {
            for entry in rd.flatten() {
                if entry.path().is_dir() {
                    collect_building_ids_under(&entry.path(), &mut buildings);
                }
            }
        }
    }
    buildings.sort();
    buildings.dedup();
    buildings
}

fn collect_building_ids_under(root: &Path, out: &mut Vec<String>) {
    if let Ok(rd) = fs::read_dir(root.join("history")) {
        for e in rd.flatten() {
            if !e.path().is_dir() {
                continue;
            }
            if let Some(name) = e
                .file_name()
                .to_str()
                .and_then(|n| n.strip_prefix("building_id="))
            {
                if !name.is_empty() && safe_partition_value(name, "building_id").is_ok() {
                    out.push(name.to_string());
                }
            }
        }
    }
    if let Ok(rd) = fs::read_dir(root) {
        for e in rd.flatten() {
            if !e.path().is_dir() {
                continue;
            }
            if let Some(name) = e
                .file_name()
                .to_str()
                .and_then(|n| n.strip_prefix("building="))
            {
                if !name.is_empty() && safe_partition_value(name, "building_id").is_ok() {
                    out.push(name.to_string());
                }
            }
        }
    }
}

fn validate_segment(value: &str, field: &str) -> Result<()> {
    if value.contains('/')
        || value.contains('\\')
        || value.contains("..")
        || value.contains('\0')
        || value.contains('=')
    {
        bail!("unsafe {field} partition value");
    }
    Ok(())
}

#[derive(Debug, Clone, Serialize)]
pub struct ObjectMetadata {
    pub relative_path: String,
    pub size_bytes: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub modified_unix_seconds: Option<u64>,
}

/// Small local backend used by the canonical storage contract.
///
/// All paths are relative to `root`; callers never pass arbitrary absolute
/// filesystem paths from API input. Final writes are published with a temporary
/// sibling file followed by `rename`, which is atomic on normal local filesystems.
#[derive(Debug, Clone)]
pub struct LocalStorage {
    root: PathBuf,
}

impl LocalStorage {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn exists(&self, relative: &Path) -> Result<bool> {
        Ok(self.resolve(relative)?.exists())
    }

    pub fn read(&self, relative: &Path) -> Result<Vec<u8>> {
        let path = self.resolve(relative)?;
        let mut file = fs::File::open(&path).with_context(|| format!("open {}", path.display()))?;
        let mut out = Vec::new();
        file.read_to_end(&mut out)?;
        Ok(out)
    }

    pub fn write_atomic(&self, relative: &Path, bytes: &[u8]) -> Result<()> {
        let final_path = self.resolve(relative)?;
        let parent = final_path
            .parent()
            .ok_or_else(|| anyhow!("storage path has no parent"))?;
        fs::create_dir_all(parent)?;

        let file_name = final_path
            .file_name()
            .and_then(|v| v.to_str())
            .ok_or_else(|| anyhow!("invalid storage file name"))?;
        let tmp = parent.join(format!(".{file_name}.tmp-{}", std::process::id()));
        {
            let mut file = fs::OpenOptions::new()
                .create(true)
                .truncate(true)
                .write(true)
                .open(&tmp)?;
            file.write_all(bytes)?;
            file.sync_all()?;
        }
        fs::rename(&tmp, &final_path)
            .with_context(|| format!("publish {} -> {}", tmp.display(), final_path.display()))?;
        Ok(())
    }

    pub fn delete(&self, relative: &Path) -> Result<()> {
        let path = self.resolve(relative)?;
        if path.exists() {
            fs::remove_file(path)?;
        }
        Ok(())
    }

    pub fn list_recursive(&self, prefix: &Path) -> Result<Vec<ObjectMetadata>> {
        let base = self.resolve(prefix)?;
        if !base.exists() {
            return Ok(Vec::new());
        }
        let mut out = Vec::new();
        self.walk(&base, &mut out)?;
        out.sort_by(|a, b| a.relative_path.cmp(&b.relative_path));
        Ok(out)
    }

    /// Hub-root `history/` plus every `tenants/{tid}/history/` tree.
    ///
    /// Wave U W7: ACME MT hive lives under `tenants/acme/history/` (~54k small
    /// parts). Compaction / stats that only scanned hub `history/` silently
    /// missed the tenant tree and could not reduce file fan-out.
    pub fn list_history_objects(&self) -> Result<Vec<ObjectMetadata>> {
        let mut out = self.list_recursive(Path::new("history"))?;
        let tenants_dir = self.root.join("tenants");
        if tenants_dir.is_dir() {
            if let Ok(rd) = fs::read_dir(&tenants_dir) {
                for entry in rd.flatten() {
                    if !entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                        continue;
                    }
                    let tid = entry.file_name();
                    let prefix = Path::new("tenants").join(&tid).join("history");
                    out.extend(self.list_recursive(&prefix)?);
                }
            }
        }
        out.sort_by(|a, b| a.relative_path.cmp(&b.relative_path));
        Ok(out)
    }

    fn walk(&self, dir: &Path, out: &mut Vec<ObjectMetadata>) -> Result<()> {
        for entry in fs::read_dir(dir)? {
            let entry = entry?;
            let path = entry.path();
            if path.is_dir() {
                self.walk(&path, out)?;
                continue;
            }
            let meta = entry.metadata()?;
            let rel = path
                .strip_prefix(&self.root)
                .map_err(|_| anyhow!("storage path escaped configured root"))?;
            let modified_unix_seconds = meta
                .modified()
                .ok()
                .and_then(|m| m.duration_since(SystemTime::UNIX_EPOCH).ok())
                .map(|d| d.as_secs());
            out.push(ObjectMetadata {
                relative_path: rel.to_string_lossy().replace('\\', "/"),
                size_bytes: meta.len(),
                modified_unix_seconds,
            });
        }
        Ok(())
    }

    fn resolve(&self, relative: &Path) -> Result<PathBuf> {
        if relative.is_absolute() {
            bail!("storage path must be relative");
        }
        for component in relative.components() {
            use std::path::Component;
            if matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            ) {
                bail!("storage path traversal rejected");
            }
        }
        Ok(self.root.join(relative))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    #[test]
    fn parses_local_and_s3_storage_urls() {
        assert_eq!(
            StorageUrl::parse("file:///data/openfdd").unwrap(),
            StorageUrl::File {
                root: PathBuf::from("/data/openfdd")
            }
        );
        assert_eq!(
            StorageUrl::parse("/srv/openfdd").unwrap(),
            StorageUrl::File {
                root: PathBuf::from("/srv/openfdd")
            }
        );
        assert_eq!(
            StorageUrl::parse("s3://history-bucket/site-a").unwrap(),
            StorageUrl::S3 {
                bucket: "history-bucket".into(),
                prefix: "site-a".into()
            }
        );
        assert!(StorageUrl::parse("https://example.invalid").is_err());
        assert!(StorageUrl::parse("s3://").is_err());
    }

    #[test]
    fn local_file_root_prefers_storage_url_over_parquet_root() {
        let prev_storage = env::var("OPENFDD_STORAGE_URL").ok();
        let prev_parquet = env::var("OPENFDD_PARQUET_ROOT").ok();
        env::set_var(
            "OPENFDD_STORAGE_URL",
            "file:///tmp/openfdd-storage-url-root",
        );
        env::set_var("OPENFDD_PARQUET_ROOT", "/tmp/openfdd-legacy-parquet-root");
        assert_eq!(
            local_file_root_from_env(),
            Some(PathBuf::from("/tmp/openfdd-storage-url-root"))
        );
        env::set_var("OPENFDD_STORAGE_URL", "s3://bucket/prefix");
        assert_eq!(
            local_file_root_from_env(),
            Some(PathBuf::from("/tmp/openfdd-legacy-parquet-root"))
        );
        env::remove_var("OPENFDD_STORAGE_URL");
        assert_eq!(
            local_file_root_from_env(),
            Some(PathBuf::from("/tmp/openfdd-legacy-parquet-root"))
        );
        env::remove_var("OPENFDD_PARQUET_ROOT");
        assert_eq!(local_file_root_from_env(), None);
        if let Some(v) = prev_storage {
            env::set_var("OPENFDD_STORAGE_URL", v);
        }
        if let Some(v) = prev_parquet {
            env::set_var("OPENFDD_PARQUET_ROOT", v);
        }
    }

    #[test]
    fn builds_monthly_hive_paths() {
        let ts = Utc.with_ymd_and_hms(2026, 8, 20, 14, 30, 0).unwrap();
        assert_eq!(
            history_partition_path("BUILDING_100", "AHU_1", ts)
                .unwrap()
                .to_string_lossy(),
            "history/building_id=BUILDING_100/equipment_id=AHU_1/year=2026/month=08"
        );
        assert_eq!(
            weather_partition_path("BUILDING_100", ts)
                .unwrap()
                .to_string_lossy(),
            "weather/building_id=BUILDING_100/year=2026/month=08"
        );
    }

    #[test]
    fn rejects_unsafe_partition_values() {
        let ts = Utc::now();
        assert!(history_partition_path("../secret", "AHU_1", ts).is_err());
        assert!(history_partition_path("B1", "AHU/../../x", ts).is_err());
        assert!(history_partition_path("B=1", "AHU_1", ts).is_err());
    }

    #[test]
    fn tenant_storage_root_off_is_identity() {
        let base = PathBuf::from("/workspace/openfdd");
        assert_eq!(tenant_storage_root(&base, None).unwrap(), base);
        assert_eq!(tenant_storage_root(&base, Some("")).unwrap(), base);
        assert_eq!(tenant_storage_prefix(None).unwrap(), "");
    }

    #[test]
    fn tenant_storage_root_partitions_and_isolates() {
        let base = PathBuf::from("/workspace/openfdd");
        let a = tenant_storage_root(&base, Some("acme")).unwrap();
        let b = tenant_storage_root(&base, Some("beta")).unwrap();
        assert_eq!(a, PathBuf::from("/workspace/openfdd/tenants/acme"));
        assert_eq!(b, PathBuf::from("/workspace/openfdd/tenants/beta"));
        assert_ne!(a, b);
        assert_eq!(tenant_storage_prefix(Some("acme")).unwrap(), "tenants/acme");
        // Hive under tenant root stays relative to that root:
        let ts = Utc.with_ymd_and_hms(2026, 9, 10, 0, 0, 0).unwrap();
        let rel = history_partition_path("bldg2", "loopback", ts).unwrap();
        assert!(a.join(&rel).starts_with(&a));
        assert!(!a.join(&rel).starts_with(&b));
        assert!(tenant_storage_root(&base, Some("../x")).is_err());
        assert!(tenant_storage_root(&base, Some("a=b")).is_err());
    }

    #[test]
    fn dual_read_prefers_tenant_partition_then_hub_fallback() {
        let tmp = TempDir::new().unwrap();
        let hub = tmp.path();
        let tenant = hub.join("tenants/acme/building=ACME/equipment=rtu_01");
        fs::create_dir_all(&tenant).unwrap();
        fs::write(tenant.join("history.parquet"), b"pq").unwrap();
        let hub_only = hub.join("building=BUILDING_100/equipment=AHU_1");
        fs::create_dir_all(&hub_only).unwrap();
        fs::write(hub_only.join("history.parquet"), b"pq").unwrap();

        let acme = resolve_building_read_root(hub, Some("acme"), "ACME").unwrap();
        assert_eq!(acme.source, BuildingReadSource::TenantPartition);
        assert_eq!(acme.tenant_id.as_deref(), Some("acme"));
        assert!(acme.root.ends_with("tenants/acme"));

        // Preferred tenant missing tree → hub-root fallback (additive migrate window).
        let b100 = resolve_building_read_root(hub, Some("building_100"), "BUILDING_100").unwrap();
        assert_eq!(b100.source, BuildingReadSource::HubRoot);
        assert_eq!(b100.root, hub);

        // Unique tenants/* hit without preferred tid.
        let via_scan = resolve_building_read_root(hub, None, "ACME").unwrap();
        assert_eq!(via_scan.source, BuildingReadSource::TenantPartition);
        assert_eq!(via_scan.tenant_id.as_deref(), Some("acme"));
    }

    #[test]
    fn dual_read_ambiguous_tenant_labels_fall_to_hub() {
        let tmp = TempDir::new().unwrap();
        let hub = tmp.path();
        for tid in ["tenant_a", "tenant_b"] {
            let dir = hub
                .join("tenants")
                .join(tid)
                .join("building=site_x")
                .join("equipment=e1");
            fs::create_dir_all(&dir).unwrap();
            fs::write(dir.join("history.parquet"), b"pq").unwrap();
        }
        let resolved = resolve_building_read_root(hub, None, "site_x").unwrap();
        assert_eq!(resolved.source, BuildingReadSource::HubRoot);
        let preferred = resolve_building_read_root(hub, Some("tenant_b"), "site_x").unwrap();
        assert_eq!(preferred.source, BuildingReadSource::TenantPartition);
        assert_eq!(preferred.tenant_id.as_deref(), Some("tenant_b"));
    }

    #[test]
    fn list_building_ids_unions_hub_and_tenant_trees() {
        let tmp = TempDir::new().unwrap();
        let hub = tmp.path();
        fs::create_dir_all(hub.join("building=LAKESIDE_ES")).unwrap();
        fs::create_dir_all(hub.join("tenants/lakeside_sd/building=LAKESIDE_ES")).unwrap();
        fs::create_dir_all(hub.join("tenants/acme/history/building_id=ACME")).unwrap();
        let ids = list_building_ids(hub);
        assert!(ids.contains(&"LAKESIDE_ES".to_string()));
        assert!(ids.contains(&"ACME".to_string()));
    }

    #[test]
    fn local_storage_roundtrip_list_and_delete() {
        let tmp = TempDir::new().unwrap();
        let storage = LocalStorage::new(tmp.path());
        let rel = Path::new("history/building_id=B1/test.bin");
        storage.write_atomic(rel, b"abc").unwrap();
        assert!(storage.exists(rel).unwrap());
        assert_eq!(storage.read(rel).unwrap(), b"abc");
        let objects = storage.list_recursive(Path::new("history")).unwrap();
        assert_eq!(objects.len(), 1);
        assert_eq!(objects[0].size_bytes, 3);
        assert_eq!(objects[0].relative_path, "history/building_id=B1/test.bin");
        storage.delete(rel).unwrap();
        assert!(!storage.exists(rel).unwrap());
    }

    #[test]
    fn local_storage_rejects_traversal() {
        let tmp = TempDir::new().unwrap();
        let storage = LocalStorage::new(tmp.path());
        assert!(storage.read(Path::new("../escape")).is_err());
        assert!(storage
            .write_atomic(Path::new("/tmp/escape"), b"x")
            .is_err());
    }
}
