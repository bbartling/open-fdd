//! Provider-neutral S3-compatible historian runtime for DataFusion.
//!
//! The engine consumes the generic `OPENFDD_S3_*` contract. Provider-specific
//! names (Railway, MinIO, AWS, etc.) belong only in deployment configuration.

use std::collections::BTreeSet;
use std::env;
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use datafusion::arrow::datatypes::DataType;
use datafusion::prelude::{ParquetReadOptions, SessionContext};
use fdd_store::{safe_partition_value, HistorianConfig, StorageUrl};
use object_store::aws::{AmazonS3, AmazonS3Builder};
use object_store::path::Path as ObjectPath;
use object_store::ObjectStore;
use url::Url;

use crate::historian::{
    register_historian_dataset, HistorianDatasetKind, HistorianRegistration,
};

const DEFAULT_S3_REGION: &str = "us-east-1";
const SCOPED_SOURCE_TABLE: &str = "__openfdd_history_scoped_source";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum S3UrlStyle {
    Path,
    Virtual,
}

impl S3UrlStyle {
    fn from_env() -> Result<Self> {
        if let Some(raw) = nonempty_env("OPENFDD_S3_URL_STYLE") {
            return match raw.to_ascii_lowercase().as_str() {
                "path" | "path-style" | "path_style" => Ok(Self::Path),
                "virtual" | "virtual-hosted" | "virtual_hosted" => Ok(Self::Virtual),
                _ => bail!("OPENFDD_S3_URL_STYLE must be 'path' or 'virtual'"),
            };
        }
        match nonempty_env("OPENFDD_S3_VIRTUAL_HOSTED_STYLE") {
            Some(raw) if parse_bool("OPENFDD_S3_VIRTUAL_HOSTED_STYLE", &raw)? => {
                Ok(Self::Virtual)
            }
            Some(_) | None => Ok(Self::Path),
        }
    }

    fn virtual_hosted(self) -> bool {
        matches!(self, Self::Virtual)
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct S3ObjectStoreConfig {
    endpoint: Option<String>,
    region: String,
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
                &self.access_key_id.as_ref().map(|_| "<redacted>"),
            )
            .field(
                "secret_access_key",
                &self.secret_access_key.as_ref().map(|_| "<redacted>"),
            )
            .field(
                "session_token",
                &self.session_token.as_ref().map(|_| "<redacted>"),
            )
            .field("url_style", &self.url_style)
            .field("allow_http", &self.allow_http)
            .finish()
    }
}

impl S3ObjectStoreConfig {
    pub fn from_env() -> Result<Self> {
        let endpoint = nonempty_env("OPENFDD_S3_ENDPOINT");
        if let Some(raw) = &endpoint {
            validate_endpoint(raw)?;
        }

        let access_key_id = nonempty_env("OPENFDD_S3_ACCESS_KEY_ID");
        let secret_access_key = nonempty_env("OPENFDD_S3_SECRET_ACCESS_KEY");
        if access_key_id.is_some() != secret_access_key.is_some() {
            bail!(
                "OPENFDD_S3_ACCESS_KEY_ID and OPENFDD_S3_SECRET_ACCESS_KEY must be configured together"
            );
        }
        let session_token = nonempty_env("OPENFDD_S3_SESSION_TOKEN");
        if session_token.is_some() && access_key_id.is_none() {
            bail!(
                "OPENFDD_S3_SESSION_TOKEN requires explicit access key and secret key configuration"
            );
        }

        let allow_http = env_bool("OPENFDD_S3_ALLOW_HTTP", false)?;
        if let Some(raw) = &endpoint {
            let parsed = Url::parse(raw).context("parse OPENFDD_S3_ENDPOINT")?;
            if parsed.scheme() == "http" && !allow_http {
                bail!("HTTP S3 endpoint requires OPENFDD_S3_ALLOW_HTTP=true (local/test only)");
            }
        }
        if allow_http && session_token.is_some() {
            bail!("OPENFDD_S3_SESSION_TOKEN cannot be combined with OPENFDD_S3_ALLOW_HTTP=true");
        }

        Ok(Self {
            endpoint,
            region: nonempty_env("OPENFDD_S3_REGION")
                .unwrap_or_else(|| DEFAULT_S3_REGION.to_string()),
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
            .with_region(&self.region)
            .with_virtual_hosted_style_request(self.url_style.virtual_hosted())
            .with_allow_http(self.allow_http);

        if let Some(endpoint) = &self.endpoint {
            builder = builder.with_endpoint(endpoint_for_style(
                endpoint,
                bucket,
                self.url_style.virtual_hosted(),
            )?);
        }
        if let (Some(access), Some(secret)) = (&self.access_key_id, &self.secret_access_key) {
            builder = builder
                .with_access_key_id(access)
                .with_secret_access_key(secret);
        }
        if let Some(token) = &self.session_token {
            builder = builder.with_token(token);
        }

        builder.build().context("build S3-compatible object store")
    }
}

/// True when the canonical historian setting selects the S3 backend.
pub fn configured_storage_is_s3() -> Result<bool> {
    Ok(matches!(
        HistorianConfig::from_env()?.storage_url,
        StorageUrl::S3 { .. }
    ))
}

/// Register the canonical historian selected by `HistorianConfig`.
pub async fn register_configured_historian(
    ctx: &SessionContext,
    config: &HistorianConfig,
) -> Result<HistorianRegistration> {
    register_configured_historian_scoped(ctx, config, None).await
}

/// Register the canonical historian, optionally narrowing the object-store path
/// to one building before DataFusion plans any scan.
///
/// Scoping at the URL root is intentionally stronger than adding only a SQL
/// predicate: unrelated building objects are never candidates for the file scan.
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

async fn register_s3_historian(
    ctx: &SessionContext,
    bucket: &str,
    prefix: &str,
    building_id: Option<&str>,
    config: &S3ObjectStoreConfig,
) -> Result<HistorianRegistration> {
    let store = config.build(bucket)?;
    let store_url = Url::parse(&format!("s3://{bucket}"))
        .with_context(|| format!("build object-store URL for s3://{bucket}"))?;
    ctx.runtime_env()
        .register_object_store(&store_url, Arc::new(store));

    let base = canonical_history_url(bucket, prefix);
    match building_id {
        None => {
            let options = ParquetReadOptions::new()
                .table_partition_cols(canonical_partition_columns())
                .parquet_pruning(true);
            ctx.register_parquet("history", base.as_str(), options)
                .await
                .with_context(|| format!("register canonical S3 historian from {base}"))?;
            Ok(HistorianRegistration {
                kind: HistorianDatasetKind::CanonicalHive,
                root: base,
            })
        }
        Some(building_id) => {
            let building = safe_partition_value(building_id, "building_id")?;
            let scoped = format!("{base}building_id={building}/");
            let options = ParquetReadOptions::new()
                .table_partition_cols(vec![
                    ("equipment_id".to_string(), DataType::Utf8),
                    ("year".to_string(), DataType::Utf8),
                    ("month".to_string(), DataType::Utf8),
                ])
                .parquet_pruning(true);
            ctx.register_parquet(SCOPED_SOURCE_TABLE, scoped.as_str(), options)
                .await
                .with_context(|| format!("register building-scoped S3 historian from {scoped}"))?;

            let escaped = building.replace('\'', "''");
            let scoped_df = ctx
                .sql(&format!(
                    "SELECT *, '{escaped}' AS building_id FROM {SCOPED_SOURCE_TABLE}"
                ))
                .await
                .context("build building-scoped S3 history view")?;
            ctx.register_table("history", scoped_df.into_view())?;

            Ok(HistorianRegistration {
                kind: HistorianDatasetKind::CanonicalHive,
                root: scoped,
            })
        }
    }
}

/// Refresh the local S3 building-scope index used by existing central analytics.
///
/// The index contains empty `building=<id>/` directories only. It is scratch
/// metadata, never historian data. DataFusion still reads Parquet directly from
/// S3; the directories preserve the existing fail-closed check for unknown
/// buildings without rewriting the central analytics module.
pub async fn refresh_s3_scope_index_from_env() -> Result<Option<PathBuf>> {
    let historian = HistorianConfig::from_env()?;
    let StorageUrl::S3 { bucket, prefix } = &historian.storage_url else {
        return Ok(None);
    };

    let config = S3ObjectStoreConfig::from_env()?;
    let store = config.build(bucket)?;
    let object_prefix = ObjectPath::from(object_history_prefix(prefix));
    let listed = store
        .list_with_delimiter(Some(&object_prefix))
        .await
        .with_context(|| format!("list S3 historian building prefixes in s3://{bucket}"))?;

    let mut expected = BTreeSet::new();
    for common in listed.common_prefixes {
        let raw = common.to_string();
        if let Some(segment) = raw
            .split('/')
            .find(|segment| segment.starts_with("building_id="))
        {
            let id = segment.trim_start_matches("building_id=");
            let safe = safe_partition_value(id, "building_id")?;
            expected.insert(format!("building={safe}"));
        }
    }

    let index_root = s3_scope_index_root();
    std::fs::create_dir_all(&index_root)
        .with_context(|| format!("create S3 scope index {}", index_root.display()))?;

    for entry in std::fs::read_dir(&index_root)? {
        let entry = entry?;
        if !entry.file_type()?.is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with("building=") && !expected.contains(&name) {
            std::fs::remove_dir_all(entry.path())?;
        }
    }
    for name in &expected {
        std::fs::create_dir_all(index_root.join(name))?;
    }

    // Canonical S3 storage wins over the legacy local root compatibility knob.
    // Central analytics already consults OPENFDD_PARQUET_ROOT for its scope guard.
    env::set_var("OPENFDD_PARQUET_ROOT", &index_root);
    Ok(Some(index_root))
}

fn s3_scope_index_root() -> PathBuf {
    if let Some(raw) = nonempty_env("OPENFDD_S3_SCOPE_INDEX_DIR") {
        return PathBuf::from(raw);
    }
    let workspace = nonempty_env("OPENFDD_WORKSPACE").unwrap_or_else(|| "workspace".into());
    Path::new(&workspace).join("data/openfdd-s3-scope-index")
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
    validate_endpoint(endpoint)?;
    if !virtual_hosted {
        return Ok(endpoint.to_string());
    }

    let mut parsed = Url::parse(endpoint).context("parse OPENFDD_S3_ENDPOINT")?;
    let host = parsed
        .host_str()
        .ok_or_else(|| anyhow!("OPENFDD_S3_ENDPOINT requires a host"))?;
    if host == bucket || host.starts_with(&format!("{bucket}.")) {
        return Ok(endpoint.to_string());
    }
    let bucket_host = format!("{bucket}.{host}");
    parsed
        .set_host(Some(&bucket_host))
        .map_err(|_| anyhow!("cannot apply virtual-hosted S3 bucket to endpoint"))?;
    Ok(parsed.as_str().trim_end_matches('/').to_string())
}

fn validate_endpoint(raw: &str) -> Result<()> {
    let parsed = Url::parse(raw).context("parse OPENFDD_S3_ENDPOINT")?;
    if !matches!(parsed.scheme(), "http" | "https") {
        bail!("OPENFDD_S3_ENDPOINT must use http:// or https://");
    }
    if parsed.host_str().is_none() {
        bail!("OPENFDD_S3_ENDPOINT requires a host");
    }
    if !parsed.username().is_empty() || parsed.password().is_some() {
        bail!("OPENFDD_S3_ENDPOINT must not embed credentials");
    }
    Ok(())
}

fn nonempty_env(name: &str) -> Option<String> {
    env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn env_bool(name: &str, default: bool) -> Result<bool> {
    let Some(raw) = nonempty_env(name) else {
        return Ok(default);
    };
    parse_bool(name, &raw)
}

fn parse_bool(name: &str, raw: &str) -> Result<bool> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => bail!("{name} must be true/false"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn clear_env() {
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
    fn canonical_s3_history_url_keeps_optional_prefix() {
        assert_eq!(
            canonical_history_url("history-bucket", ""),
            "s3://history-bucket/history/"
        );
        assert_eq!(
            canonical_history_url("history-bucket", "/openfdd/prod/"),
            "s3://history-bucket/openfdd/prod/history/"
        );
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
    fn path_style_keeps_base_endpoint() {
        assert_eq!(
            endpoint_for_style("http://minio:9000/", "history", false).unwrap(),
            "http://minio:9000"
        );
    }

    #[test]
    fn debug_never_emits_credentials() {
        let config = S3ObjectStoreConfig {
            endpoint: Some("https://storage.example.com".into()),
            region: "auto".into(),
            access_key_id: Some("access-secret-value".into()),
            secret_access_key: Some("super-secret-value".into()),
            session_token: Some("session-secret-value".into()),
            url_style: S3UrlStyle::Virtual,
            allow_http: false,
        };
        let debug = format!("{config:?}");
        assert!(!debug.contains("access-secret-value"));
        assert!(!debug.contains("super-secret-value"));
        assert!(!debug.contains("session-secret-value"));
        assert!(debug.contains("<redacted>"));
    }

    #[test]
    fn config_rejects_partial_credentials_and_credential_endpoint() {
        let _guard = ENV_LOCK.lock().unwrap();
        clear_env();
        env::set_var("OPENFDD_S3_ACCESS_KEY_ID", "key-only");
        assert!(S3ObjectStoreConfig::from_env().is_err());
        clear_env();
        env::set_var(
            "OPENFDD_S3_ENDPOINT",
            "https://user:secret@example.com",
        );
        assert!(S3ObjectStoreConfig::from_env().is_err());
        clear_env();
    }
}
