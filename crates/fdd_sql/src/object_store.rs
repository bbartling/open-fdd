//! S3-compatible historian object-store registration for DataFusion.
//!
//! This module stays provider-neutral. AWS S3, MinIO, Railway Storage Buckets,
//! and other S3-compatible services all map deployment settings into the same
//! `OPENFDD_S3_*` contract. Credentials are never serialized or logged.

use std::collections::BTreeSet;
use std::env;
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use datafusion::arrow::datatypes::DataType;
use datafusion::prelude::{col, lit, ParquetReadOptions, SessionContext};
use fdd_store::{safe_partition_value, HistorianConfig, StorageUrl};
use object_store::aws::{AmazonS3, AmazonS3Builder};
use object_store::path::Path as ObjectPath;
use object_store::ObjectStore;
use url::Url;

use crate::historian::{
    register_historian_dataset, HistorianDatasetKind, HistorianRegistration,
};

const SCOPED_SOURCE_TABLE: &str = "__openfdd_history_scoped_source";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum S3UrlStyle {
    Path,
    Virtual,
}

impl S3UrlStyle {
    fn from_env() -> Result<Self> {
        if let Ok(raw) = env::var("OPENFDD_S3_URL_STYLE") {
            return match raw.trim().to_ascii_lowercase().as_str() {
                "path" | "path_style" | "path-style" => Ok(Self::Path),
                "virtual" | "virtual_hosted" | "virtual-hosted" => Ok(Self::Virtual),
                _ => bail!("OPENFDD_S3_URL_STYLE must be 'path' or 'virtual'"),
            };
        }
        match env::var("OPENFDD_S3_VIRTUAL_HOSTED_STYLE") {
            Ok(raw) => Ok(if parse_bool("OPENFDD_S3_VIRTUAL_HOSTED_STYLE", &raw)? {
                Self::Virtual
            } else {
                Self::Path
            }),
            Err(_) => Ok(Self::Path),
        }
    }

    fn virtual_hosted(self) -> bool {
        matches!(self, Self::Virtual)
    }
}

#[derive(Clone)]
pub struct S3ObjectStoreConfig {
    endpoint: Option<String>,
    region: Option<String>,
    access_key_id: Option<String>,
    secret_access_key: Option<String>,
    session_token: Option<String>,
    url_style: S3UrlStyle,
    allow_http: bool,
}

impl fmt::Debug for S3ObjectStoreConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("S3ObjectStoreConfig")
            .field("endpoint", &self.endpoint)
            .field("region", &self.region)
            .field(
                "access_key_id",
                &self.access_key_id.as_ref().map(|_| "[REDACTED]"),
            )
            .field(
                "secret_access_key",
                &self.secret_access_key.as_ref().map(|_| "[REDACTED]"),
            )
            .field(
                "session_token",
                &self.session_token.as_ref().map(|_| "[REDACTED]"),
            )
            .field("url_style", &self.url_style)
            .field("allow_http", &self.allow_http)
            .finish()
    }
}

impl S3ObjectStoreConfig {
    pub fn from_env() -> Result<Self> {
        let endpoint = nonempty_env("OPENFDD_S3_ENDPOINT");
        let region = nonempty_env("OPENFDD_S3_REGION");
        let access_key_id = nonempty_env("OPENFDD_S3_ACCESS_KEY_ID");
        let secret_access_key = nonempty_env("OPENFDD_S3_SECRET_ACCESS_KEY");
        let session_token = nonempty_env("OPENFDD_S3_SESSION_TOKEN");
        let allow_http = match env::var("OPENFDD_S3_ALLOW_HTTP") {
            Ok(raw) => parse_bool("OPENFDD_S3_ALLOW_HTTP", &raw)?,
            Err(_) => false,
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

        if let Some(endpoint) = &endpoint {
            let parsed = Url::parse(endpoint).context("parse OPENFDD_S3_ENDPOINT")?;
            if !parsed.username().is_empty() || parsed.password().is_some() {
                bail!("OPENFDD_S3_ENDPOINT must not embed credentials");
            }
            match parsed.scheme() {
                "https" => {}
                "http" if allow_http => {}
                "http" => bail!(
                    "HTTP S3 endpoint requires OPENFDD_S3_ALLOW_HTTP=true (local/test only)"
                ),
                _ => bail!("OPENFDD_S3_ENDPOINT must use http:// or https://"),
            }
            if parsed.host_str().is_none() {
                bail!("OPENFDD_S3_ENDPOINT requires a host");
            }
        }

        Ok(Self {
            endpoint,
            region,
            access_key_id,
            secret_access_key,
            session_token,
            url_style: S3UrlStyle::from_env()?,
            allow_http,
        })
    }

    fn build(&self, bucket: &str) -> Result<AmazonS3> {
        let mut builder = AmazonS3Builder::from_env()
            .with_bucket_name(bucket)
            .with_virtual_hosted_style_request(self.url_style.virtual_hosted())
            .with_allow_http(self.allow_http);

        if let Some(region) = &self.region {
            builder = builder.with_region(region);
        }
        if let Some(endpoint) = &self.endpoint {
            builder = builder.with_endpoint(endpoint_for_style(
                endpoint,
                bucket,
                self.url_style.virtual_hosted(),
            )?);
        }
        if let (Some(key), Some(secret)) = (&self.access_key_id, &self.secret_access_key) {
            builder = builder
                .with_access_key_id(key)
                .with_secret_access_key(secret);
        }
        if let Some(token) = &self.session_token {
            builder = builder.with_token(token);
        }

        builder.build().context("build S3-compatible object store")
    }
}

/// Register the configured historian backend as logical table `history`.
pub async fn register_configured_historian(
    ctx: &SessionContext,
    config: &HistorianConfig,
) -> Result<HistorianRegistration> {
    register_configured_historian_scoped(ctx, config, None).await
}

/// Register the configured historian, optionally narrowing S3 discovery to one
/// canonical building partition before DataFusion plans a scan.
pub async fn register_configured_historian_scoped(
    ctx: &SessionContext,
    config: &HistorianConfig,
    building_id: Option<&str>,
) -> Result<HistorianRegistration> {
    match &config.storage_url {
        StorageUrl::File { root } => register_historian_dataset(ctx, root).await,
        StorageUrl::S3 { bucket, prefix } => {
            let s3 = S3ObjectStoreConfig::from_env()?;
            register_s3_historian(ctx, bucket, prefix, building_id, &s3).await
        }
    }
}

/// Restrict an already-registered canonical `history` table to one building.
///
/// Kept for callers that already hold a registered table. New S3 callers should
/// prefer [`register_configured_historian_scoped`] so object discovery itself is
/// narrowed to the building prefix.
pub async fn scope_history_to_building(ctx: &SessionContext, building_id: &str) -> Result<()> {
    let building_id = safe_partition_value(building_id, "building_id")?;
    let scoped = ctx
        .table("history")
        .await
        .context("open registered history for building scope")?
        .filter(col("building_id").eq(lit(building_id)))?;
    ctx.deregister_table("history")?;
    ctx.register_table("history", scoped.into_view())?;
    Ok(())
}

/// Scratch directory used only to preserve central's fail-closed
/// `building=<id>` presence check while canonical S3 data lives remotely.
pub fn s3_scope_index_root() -> PathBuf {
    if let Some(root) = nonempty_env("OPENFDD_S3_SCOPE_INDEX_DIR") {
        return PathBuf::from(root);
    }
    let workspace = nonempty_env("OPENFDD_WORKSPACE").unwrap_or_else(|| "workspace".into());
    PathBuf::from(workspace).join("data/openfdd-s3-scope-index")
}

/// Refresh the S3 building-scope scratch index from canonical Hive prefixes.
///
/// This uses delimiter listing at the `history/` prefix, so the refresh cost is
/// proportional to building prefixes rather than historian object count.
pub async fn refresh_s3_scope_index_from_env() -> Result<Option<usize>> {
    let config = HistorianConfig::from_env()?;
    let StorageUrl::S3 { bucket, prefix } = &config.storage_url else {
        return Ok(None);
    };
    let s3 = S3ObjectStoreConfig::from_env()?;
    let store = s3.build(bucket)?;
    let history_prefix = object_history_prefix(prefix);
    let listing = store
        .list_with_delimiter(Some(&ObjectPath::from(history_prefix)))
        .await
        .context("list S3 historian building prefixes")?;

    let root = s3_scope_index_root();
    fs::create_dir_all(&root)
        .with_context(|| format!("create S3 scope scratch index {}", root.display()))?;

    let mut expected = BTreeSet::new();
    for common_prefix in listing.common_prefixes {
        let raw = common_prefix.to_string();
        let Some(segment) = raw
            .split('/')
            .find(|segment| segment.starts_with("building_id="))
        else {
            continue;
        };
        let Some(building) = segment.strip_prefix("building_id=") else {
            continue;
        };
        let building = safe_partition_value(building, "building_id")?;
        expected.insert(format!("building={building}"));
    }

    for entry in fs::read_dir(&root)? {
        let entry = entry?;
        if !entry.file_type()?.is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with("building=") && !expected.contains(&name) {
            fs::remove_dir_all(entry.path())?;
        }
    }
    for marker in &expected {
        fs::create_dir_all(root.join(marker))?;
    }
    fs::write(
        root.join(".openfdd-s3-scope-index"),
        b"scratch metadata only; canonical historian is object storage\n",
    )?;

    // Central's existing scope guard reads this compatibility variable. The
    // canonical storage URL remains authoritative for the actual historian.
    env::set_var("OPENFDD_PARQUET_ROOT", &root);
    Ok(Some(expected.len()))
}

/// Extract the existing central `building=<id>` scope marker from a local path.
pub fn building_scope_from_compat_path(path: &Path) -> Option<&str> {
    path.file_name()
        .and_then(|name| name.to_str())
        .and_then(|name| {
            name.strip_prefix("building=")
                .or_else(|| name.strip_prefix("building_id="))
        })
}

async fn register_s3_historian(
    ctx: &SessionContext,
    bucket: &str,
    prefix: &str,
    building_id: Option<&str>,
    config: &S3ObjectStoreConfig,
) -> Result<HistorianRegistration> {
    let store = config.build(bucket)?;
    let store_url = Url::parse(&format!("s3://{bucket}"))?;
    ctx.runtime_env()
        .register_object_store(&store_url, Arc::new(store));

    let history_root = canonical_history_url(bucket, prefix);
    let Some(building_id) = building_id else {
        let options = ParquetReadOptions::new()
            .table_partition_cols(canonical_partition_columns())
            .parquet_pruning(true);
        ctx.register_parquet("history", history_root.as_str(), options)
            .await
            .with_context(|| format!("register canonical S3 history from {history_root}"))?;
        return Ok(HistorianRegistration {
            kind: HistorianDatasetKind::CanonicalHive,
            root: history_root,
        });
    };

    let building = safe_partition_value(building_id, "building_id")?;
    let scoped_root = format!("{history_root}building_id={building}/");
    let options = ParquetReadOptions::new()
        .table_partition_cols(vec![
            ("equipment_id".to_string(), DataType::Utf8),
            ("year".to_string(), DataType::Utf8),
            ("month".to_string(), DataType::Utf8),
        ])
        .parquet_pruning(true);
    ctx.register_parquet(SCOPED_SOURCE_TABLE, scoped_root.as_str(), options)
        .await
        .with_context(|| format!("register building-scoped S3 history from {scoped_root}"))?;

    let escaped = building.replace('\'', "''");
    let scoped = ctx
        .sql(&format!(
            "SELECT *, '{escaped}' AS building_id FROM {SCOPED_SOURCE_TABLE}"
        ))
        .await
        .context("build building-scoped S3 history view")?;
    ctx.register_table("history", scoped.into_view())?;

    Ok(HistorianRegistration {
        kind: HistorianDatasetKind::CanonicalHive,
        root: scoped_root,
    })
}

fn canonical_partition_columns() -> Vec<(String, DataType)> {
    vec![
        ("building_id".to_string(), DataType::Utf8),
        ("equipment_id".to_string(), DataType::Utf8),
        ("year".to_string(), DataType::Utf8),
        ("month".to_string(), DataType::Utf8),
    ]
}

fn canonical_history_url(bucket: &str, prefix: &str) -> String {
    let prefix = prefix.trim_matches('/');
    if prefix.is_empty() {
        format!("s3://{bucket}/history/")
    } else {
        format!("s3://{bucket}/{prefix}/history/")
    }
}

fn object_history_prefix(prefix: &str) -> String {
    let prefix = prefix.trim_matches('/');
    if prefix.is_empty() {
        "history".to_string()
    } else {
        format!("{prefix}/history")
    }
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

fn nonempty_env(name: &str) -> Option<String> {
    env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn parse_bool(name: &str, raw: &str) -> Result<bool> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => Err(anyhow!("{name} must be true/false")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn clear_s3_env() {
        for key in [
            "OPENFDD_S3_ENDPOINT",
            "OPENFDD_S3_REGION",
            "OPENFDD_S3_ACCESS_KEY_ID",
            "OPENFDD_S3_SECRET_ACCESS_KEY",
            "OPENFDD_S3_SESSION_TOKEN",
            "OPENFDD_S3_URL_STYLE",
            "OPENFDD_S3_VIRTUAL_HOSTED_STYLE",
            "OPENFDD_S3_ALLOW_HTTP",
            "OPENFDD_S3_SCOPE_INDEX_DIR",
        ] {
            env::remove_var(key);
        }
    }

    #[test]
    fn debug_redacts_explicit_credentials() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_s3_env();
        env::set_var("OPENFDD_S3_ACCESS_KEY_ID", "visible-key-must-not-leak");
        env::set_var("OPENFDD_S3_SECRET_ACCESS_KEY", "visible-secret-must-not-leak");
        let cfg = S3ObjectStoreConfig::from_env().unwrap();
        let rendered = format!("{cfg:?}");
        assert!(!rendered.contains("visible-key-must-not-leak"));
        assert!(!rendered.contains("visible-secret-must-not-leak"));
        assert!(rendered.contains("[REDACTED]"));
        clear_s3_env();
    }

    #[test]
    fn rejects_partial_explicit_credentials() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_s3_env();
        env::set_var("OPENFDD_S3_ACCESS_KEY_ID", "key-only");
        assert!(S3ObjectStoreConfig::from_env().is_err());
        clear_s3_env();
    }

    #[test]
    fn rejects_http_endpoint_unless_explicitly_allowed() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_s3_env();
        env::set_var("OPENFDD_S3_ENDPOINT", "http://127.0.0.1:9000");
        assert!(S3ObjectStoreConfig::from_env().is_err());
        env::set_var("OPENFDD_S3_ALLOW_HTTP", "true");
        assert!(S3ObjectStoreConfig::from_env().is_ok());
        clear_s3_env();
    }

    #[test]
    fn parses_virtual_and_path_url_styles() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_s3_env();
        env::set_var("OPENFDD_S3_URL_STYLE", "virtual");
        assert_eq!(
            S3ObjectStoreConfig::from_env().unwrap().url_style,
            S3UrlStyle::Virtual
        );
        env::set_var("OPENFDD_S3_URL_STYLE", "path");
        assert_eq!(
            S3ObjectStoreConfig::from_env().unwrap().url_style,
            S3UrlStyle::Path
        );
        clear_s3_env();
    }

    #[test]
    fn endpoint_rejects_embedded_credentials() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_s3_env();
        env::set_var(
            "OPENFDD_S3_ENDPOINT",
            "https://user:secret@storage.example.invalid",
        );
        assert!(S3ObjectStoreConfig::from_env().is_err());
        clear_s3_env();
    }

    #[test]
    fn compatibility_path_extracts_building_scope() {
        assert_eq!(
            building_scope_from_compat_path(Path::new("/tmp/index/building=BUILDING_100")),
            Some("BUILDING_100")
        );
        assert_eq!(
            building_scope_from_compat_path(Path::new("/tmp/index/building_id=BUILDING_200")),
            Some("BUILDING_200")
        );
        assert_eq!(building_scope_from_compat_path(Path::new("/tmp/index")), None);
    }

    #[test]
    fn virtual_hosted_endpoint_adds_bucket_once() {
        assert_eq!(
            endpoint_for_style("https://storage.example.com", "history-123", true).unwrap(),
            "https://history-123.storage.example.com"
        );
        assert_eq!(
            endpoint_for_style(
                "https://history-123.storage.example.com/",
                "history-123",
                true
            )
            .unwrap(),
            "https://history-123.storage.example.com"
        );
    }

    #[test]
    fn path_style_endpoint_keeps_base_host() {
        assert_eq!(
            endpoint_for_style("http://minio:9000/", "history", false).unwrap(),
            "http://minio:9000"
        );
    }
}
