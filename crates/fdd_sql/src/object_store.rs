//! S3-compatible historian object-store registration for DataFusion.
//!
//! This module stays provider-neutral. AWS S3, MinIO, Railway Storage Buckets,
//! and other S3-compatible services all map deployment settings into the same
//! `OPENFDD_S3_*` contract. Credentials are never serialized or logged.

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

use crate::historian::{register_historian_dataset, HistorianRegistration};

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
            .field("access_key_id", &self.access_key_id.as_ref().map(|_| "[REDACTED]"))
            .field(
                "secret_access_key",
                &self.secret_access_key.as_ref().map(|_| "[REDACTED]"),
            )
            .field("session_token", &self.session_token.as_ref().map(|_| "[REDACTED]"))
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

        if let Some(endpoint) = &endpoint {
            let parsed = Url::parse(endpoint).context("parse OPENFDD_S3_ENDPOINT")?;
            if parsed.username() != "" || parsed.password().is_some() {
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
            builder = builder.with_endpoint(endpoint);
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
///
/// Local and legacy file-backed configurations use the H3 registration path.
/// S3 configurations register the provider-neutral object store with DataFusion
/// and then expose the same canonical Hive partition columns as local storage.
pub async fn register_configured_historian(
    ctx: &SessionContext,
    config: &HistorianConfig,
) -> Result<HistorianRegistration> {
    match &config.storage_url {
        StorageUrl::File { root } => register_historian_dataset(ctx, root).await,
        StorageUrl::S3 { bucket, prefix } => {
            let s3 = S3ObjectStoreConfig::from_env()?;
            register_s3_historian(ctx, bucket, prefix, &s3).await
        }
    }
}

/// Restrict an already-registered canonical `history` table to one building.
///
/// This creates a DataFusion view instead of constructing a filename glob, so
/// the canonical `building_id` Hive predicate remains available for partition
/// pruning on both local and object-store backends.
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

/// Scratch directory used only to preserve the existing central fail-closed
/// `building=<id>` presence check while canonical S3 data lives remotely.
///
/// This directory is metadata/cache, never historian durability. It deliberately
/// follows central's existing local-root precedence so no application code needs
/// Railway-specific branches.
pub fn s3_scope_index_root() -> PathBuf {
    if let Ok(root) = env::var("OPENFDD_PARQUET_ROOT") {
        return PathBuf::from(root);
    }
    if let Ok(workspace) = env::var("OPENFDD_WORKSPACE") {
        return PathBuf::from(workspace).join(".cache/parquet");
    }
    PathBuf::from(".cache/parquet")
}

/// Refresh the S3 building-scope scratch index from canonical Hive prefixes.
///
/// A successful refresh creates empty `building=<id>` marker directories for
/// buildings that actually exist under `history/building_id=<id>/`. Unknown
/// building requests therefore continue to fail closed in the existing central
/// analytics bridge, while `register_parquet_tree` below routes the real scan to
/// S3 and applies the matching DataFusion building predicate.
pub async fn refresh_s3_scope_index_from_env() -> Result<Option<usize>> {
    let config = HistorianConfig::from_env()?;
    let StorageUrl::S3 { bucket, prefix } = &config.storage_url else {
        return Ok(None);
    };
    let s3 = S3ObjectStoreConfig::from_env()?;
    let store = s3.build(bucket)?;
    let history_prefix = if prefix.is_empty() {
        "history".to_string()
    } else {
        format!("{}/history", prefix.trim_matches('/'))
    };
    let listing = store
        .list_with_delimiter(Some(&ObjectPath::from(history_prefix)))
        .await
        .context("list S3 historian building prefixes")?;

    let root = s3_scope_index_root();
    fs::create_dir_all(&root)
        .with_context(|| format!("create S3 scope scratch index {}", root.display()))?;
    let mut buildings = 0usize;
    for common_prefix in listing.common_prefixes {
        let Some(segment) = common_prefix.as_ref().rsplit('/').next() else {
            continue;
        };
        let Some(building) = segment.strip_prefix("building_id=") else {
            continue;
        };
        let building = safe_partition_value(building, "building_id")?;
        fs::create_dir_all(root.join(format!("building={building}")))?;
        buildings += 1;
    }
    fs::write(
        root.join(".openfdd-s3-scope-index"),
        b"scratch metadata only; canonical historian is object storage\n",
    )?;
    Ok(Some(buildings))
}

/// Extract the existing central `building=<id>` scope marker from a local path.
pub fn building_scope_from_compat_path(path: &Path) -> Option<&str> {
    path.file_name()
        .and_then(|name| name.to_str())
        .and_then(|name| name.strip_prefix("building="))
}

async fn register_s3_historian(
    ctx: &SessionContext,
    bucket: &str,
    prefix: &str,
    config: &S3ObjectStoreConfig,
) -> Result<HistorianRegistration> {
    let store = config.build(bucket)?;
    let store_url = Url::parse(&format!("s3://{bucket}"))?;
    ctx.runtime_env()
        .register_object_store(&store_url, Arc::new(store));

    let history_root = if prefix.is_empty() {
        format!("s3://{bucket}/history/")
    } else {
        format!("s3://{bucket}/{}/history/", prefix.trim_matches('/'))
    };
    let options = ParquetReadOptions::new()
        .table_partition_cols(vec![
            ("building_id".to_string(), DataType::Utf8),
            ("equipment_id".to_string(), DataType::Utf8),
            ("year".to_string(), DataType::Utf8),
            ("month".to_string(), DataType::Utf8),
        ])
        .parquet_pruning(true);
    ctx.register_parquet("history", history_root.as_str(), options)
        .await
        .with_context(|| format!("register canonical S3 history from {history_root}"))?;

    Ok(HistorianRegistration {
        kind: crate::historian::HistorianDatasetKind::CanonicalHive,
        root: history_root,
    })
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
        assert_eq!(S3ObjectStoreConfig::from_env().unwrap().url_style, S3UrlStyle::Virtual);
        env::set_var("OPENFDD_S3_URL_STYLE", "path");
        assert_eq!(S3ObjectStoreConfig::from_env().unwrap().url_style, S3UrlStyle::Path);
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
        assert_eq!(building_scope_from_compat_path(Path::new("/tmp/index")), None);
    }
}
