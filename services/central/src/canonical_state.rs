//! Small canonical state-object store used by continuous AFDD scheduling.
//!
//! State objects live beside the canonical historian so restart behavior is the
//! same for local disk and S3-compatible deployments. Secrets are read from the
//! existing OPENFDD_S3_* environment contract and are never returned/logged.

use std::env;
use std::future::Future;
use std::path::Path;
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use bytes::Bytes;
use fdd_store::{HistorianConfig, LocalStorage, StorageUrl};
use object_store::aws::AmazonS3Builder;
use object_store::path::Path as ObjectPath;
use object_store::ObjectStore;
use url::Url;

#[derive(Clone)]
pub enum CanonicalStateStore {
    Local(LocalStorage),
    S3 {
        store: Arc<dyn ObjectStore>,
        prefix: String,
    },
}

impl CanonicalStateStore {
    pub fn from_env() -> Result<Self> {
        Self::from_config(&HistorianConfig::from_env()?)
    }

    pub fn from_config(config: &HistorianConfig) -> Result<Self> {
        match &config.storage_url {
            StorageUrl::File { root } => Ok(Self::Local(LocalStorage::new(root))),
            StorageUrl::S3 { bucket, prefix } => Ok(Self::S3 {
                store: build_s3_store(bucket)?,
                prefix: prefix.trim_matches('/').to_string(),
            }),
        }
    }

    pub fn read_optional(&self, relative_path: &Path) -> Result<Option<Vec<u8>>> {
        validate_relative(relative_path)?;
        match self {
            Self::Local(storage) => {
                if !storage.exists(relative_path)? {
                    return Ok(None);
                }
                Ok(Some(storage.read(relative_path)?))
            }
            Self::S3 { store, prefix } => {
                let location = object_path(prefix, relative_path)?;
                let result = match run_object_store(store.get(&location)) {
                    Ok(result) => result,
                    Err(error) if is_not_found(&error) => return Ok(None),
                    Err(error) => {
                        return Err(error)
                            .with_context(|| format!("read S3 state object {location}"));
                    }
                };
                let bytes = run_object_store(result.bytes())
                    .with_context(|| format!("read S3 state object body {location}"))?;
                Ok(Some(bytes.to_vec()))
            }
        }
    }

    pub fn write(&self, relative_path: &Path, bytes: &[u8]) -> Result<()> {
        validate_relative(relative_path)?;
        match self {
            Self::Local(storage) => storage.write_atomic(relative_path, bytes),
            Self::S3 { store, prefix } => {
                let location = object_path(prefix, relative_path)?;
                run_object_store(store.put(&location, Bytes::copy_from_slice(bytes).into()))
                    .with_context(|| format!("write S3 state object {location}"))?;
                Ok(())
            }
        }
    }
}

fn validate_relative(path: &Path) -> Result<()> {
    if path.is_absolute() {
        bail!("canonical state path must be relative");
    }
    if path
        .components()
        .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        bail!("canonical state path traversal rejected");
    }
    Ok(())
}

fn object_path(prefix: &str, relative_path: &Path) -> Result<ObjectPath> {
    validate_relative(relative_path)?;
    let relative = relative_path.to_string_lossy().replace('\\', "/");
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

fn parse_bool(name: &str, raw: &str) -> Result<bool> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => bail!("{name} must be a boolean"),
    }
}

fn build_s3_store(bucket: &str) -> Result<Arc<dyn ObjectStore>> {
    let endpoint = nonempty_env("OPENFDD_S3_ENDPOINT");
    let region = nonempty_env("OPENFDD_S3_REGION");
    let access_key_id = nonempty_env("OPENFDD_S3_ACCESS_KEY_ID");
    let secret_access_key = nonempty_env("OPENFDD_S3_SECRET_ACCESS_KEY");
    let session_token = nonempty_env("OPENFDD_S3_SESSION_TOKEN");
    let allow_http = env::var("OPENFDD_S3_ALLOW_HTTP")
        .ok()
        .map(|raw| parse_bool("OPENFDD_S3_ALLOW_HTTP", &raw))
        .transpose()?
        .unwrap_or(false);
    let virtual_hosted = match env::var("OPENFDD_S3_URL_STYLE") {
        Ok(raw) => match raw.trim().to_ascii_lowercase().as_str() {
            "path" | "path_style" | "path-style" => false,
            "virtual" | "virtual_hosted" | "virtual-hosted" => true,
            _ => bail!("OPENFDD_S3_URL_STYLE must be 'path' or 'virtual'"),
        },
        Err(_) => env::var("OPENFDD_S3_VIRTUAL_HOSTED_STYLE")
            .ok()
            .map(|raw| parse_bool("OPENFDD_S3_VIRTUAL_HOSTED_STYLE", &raw))
            .transpose()?
            .unwrap_or(false),
    };

    match (&access_key_id, &secret_access_key) {
        (Some(_), None) | (None, Some(_)) => bail!(
            "OPENFDD_S3_ACCESS_KEY_ID and OPENFDD_S3_SECRET_ACCESS_KEY must be configured together"
        ),
        _ => {}
    }
    if session_token.is_some() && access_key_id.is_none() {
        bail!("OPENFDD_S3_SESSION_TOKEN requires explicit S3 access key credentials");
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
            "http" => bail!("HTTP S3 endpoint requires OPENFDD_S3_ALLOW_HTTP=true"),
            _ => bail!("OPENFDD_S3_ENDPOINT must use http:// or https://"),
        }
        let host = parsed
            .host_str()
            .ok_or_else(|| anyhow!("OPENFDD_S3_ENDPOINT requires a host"))?
            .to_string();
        let endpoint = if virtual_hosted
            && host != bucket
            && !host.starts_with(&format!("{bucket}."))
        {
            let mut rewritten = parsed;
            rewritten
                .set_host(Some(&format!("{bucket}.{host}")))
                .map_err(|_| anyhow!("cannot apply virtual-hosted S3 bucket to endpoint"))?;
            rewritten.as_str().trim_end_matches('/').to_string()
        } else {
            endpoint.trim_end_matches('/').to_string()
        };
        builder = builder.with_endpoint(endpoint);
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
        builder.build().context("build canonical S3 state store")?,
    ))
}

fn run_object_store<F, T>(future: F) -> Result<T>
where
    F: Future<Output = object_store::Result<T>>,
{
    if let Ok(handle) = tokio::runtime::Handle::try_current() {
        match handle.runtime_flavor() {
            tokio::runtime::RuntimeFlavor::MultiThread => {
                return tokio::task::block_in_place(|| handle.block_on(future)).map_err(Into::into);
            }
            tokio::runtime::RuntimeFlavor::CurrentThread => {
                bail!("S3 canonical state requires a multi-thread Tokio runtime");
            }
            _ => bail!("unsupported Tokio runtime flavor for S3 canonical state"),
        }
    }
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .context("build canonical state object-store runtime")?;
    runtime.block_on(future).map_err(Into::into)
}

fn is_not_found(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<object_store::Error>()
        .is_some_and(|error| matches!(error, object_store::Error::NotFound { .. }))
}
