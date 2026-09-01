//! DataFusion execution tuning for historian workloads.
//!
//! DataFusion 55 enables CPU-sized target partitions, parallel file
//! scans/joins/windows/sorts, Parquet row-group pruning, page-index pruning,
//! and batch coalescing. Open-FDD keeps those defaults and layers on the knobs
//! that materially help selective historian scans, especially over object
//! storage: late Parquet filter pushdown/reordering and optional footer
//! prefetch. Expensive/format-dependent features such as Bloom pruning and full
//! listing statistics remain opt-in until H10 benchmarks justify them.

use std::env;

use anyhow::{bail, Context, Result};
use datafusion::config::ConfigNonZeroUsize;
use datafusion::prelude::SessionConfig;

const DEFAULT_S3_METADATA_SIZE_HINT_KB: usize = 512;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DataFusionTuning {
    pub batch_size: Option<usize>,
    pub target_partitions: Option<usize>,
    pub parquet_pushdown_filters: bool,
    pub parquet_reorder_filters: bool,
    pub parquet_bloom_filter_pruning: bool,
    pub collect_statistics: bool,
    pub parquet_metadata_size_hint_bytes: Option<usize>,
    pub meta_fetch_concurrency: Option<usize>,
    pub repartition_file_min_size_bytes: Option<usize>,
}

impl DataFusionTuning {
    pub fn from_env() -> Result<Self> {
        let s3 = env::var("OPENFDD_STORAGE_URL")
            .ok()
            .is_some_and(|raw| raw.trim().starts_with("s3://"));
        let metadata_hint_kb =
            env_optional_usize("OPENFDD_DATAFUSION_METADATA_SIZE_HINT_KB")?.or(if s3 {
                Some(DEFAULT_S3_METADATA_SIZE_HINT_KB)
            } else {
                None
            });

        Ok(Self {
            batch_size: env_optional_usize("OPENFDD_DATAFUSION_BATCH_SIZE")?,
            target_partitions: env_optional_usize("OPENFDD_DATAFUSION_TARGET_PARTITIONS")?,
            parquet_pushdown_filters: env_bool(
                "OPENFDD_DATAFUSION_PARQUET_PUSHDOWN_FILTERS",
                true,
            )?,
            parquet_reorder_filters: env_bool("OPENFDD_DATAFUSION_PARQUET_REORDER_FILTERS", true)?,
            parquet_bloom_filter_pruning: env_bool(
                "OPENFDD_DATAFUSION_BLOOM_FILTER_PRUNING",
                false,
            )?,
            collect_statistics: env_bool("OPENFDD_DATAFUSION_COLLECT_STATISTICS", false)?,
            parquet_metadata_size_hint_bytes: metadata_hint_kb
                .map(|kb| checked_kib(kb, "OPENFDD_DATAFUSION_METADATA_SIZE_HINT_KB"))
                .transpose()?,
            meta_fetch_concurrency: env_optional_usize(
                "OPENFDD_DATAFUSION_META_FETCH_CONCURRENCY",
            )?,
            repartition_file_min_size_bytes: env_optional_usize(
                "OPENFDD_DATAFUSION_REPARTITION_FILE_MIN_MB",
            )?
            .map(|mb| checked_mib(mb, "OPENFDD_DATAFUSION_REPARTITION_FILE_MIN_MB"))
            .transpose()?,
        })
    }

    pub fn session_config(&self) -> Result<SessionConfig> {
        let mut config = SessionConfig::new()
            .with_parquet_pruning(true)
            .with_parquet_page_index_pruning(true)
            .with_parquet_bloom_filter_pruning(self.parquet_bloom_filter_pruning)
            .with_collect_statistics(self.collect_statistics);

        if let Some(batch_size) = self.batch_size {
            config = config.with_batch_size(batch_size);
        }
        if let Some(target_partitions) = self.target_partitions {
            config = config.with_target_partitions(target_partitions);
        }

        let options = config.options_mut();
        options.execution.parquet.pushdown_filters = self.parquet_pushdown_filters;
        options.execution.parquet.reorder_filters = self.parquet_reorder_filters;
        options.execution.parquet.metadata_size_hint = self.parquet_metadata_size_hint_bytes;
        if let Some(concurrency) = self.meta_fetch_concurrency {
            options.execution.meta_fetch_concurrency =
                ConfigNonZeroUsize::try_new(concurrency).context(
                    "OPENFDD_DATAFUSION_META_FETCH_CONCURRENCY must be greater than zero",
                )?;
        }
        if let Some(min_size) = self.repartition_file_min_size_bytes {
            options.optimizer.repartition_file_min_size = min_size;
        }
        Ok(config)
    }
}

pub fn historian_session_config_from_env() -> Result<SessionConfig> {
    DataFusionTuning::from_env()?.session_config()
}

fn env_optional_usize(name: &str) -> Result<Option<usize>> {
    let Ok(raw) = env::var(name) else {
        return Ok(None);
    };
    let raw = raw.trim();
    if raw.is_empty() {
        return Ok(None);
    }
    let value = raw
        .parse::<usize>()
        .with_context(|| format!("{name} must be a positive integer"))?;
    if value == 0 {
        bail!("{name} must be greater than zero");
    }
    Ok(Some(value))
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

fn checked_kib(value: usize, name: &str) -> Result<usize> {
    value
        .checked_mul(1024)
        .with_context(|| format!("{name} is too large"))
}

fn checked_mib(value: usize, name: &str) -> Result<usize> {
    value
        .checked_mul(1024 * 1024)
        .with_context(|| format!("{name} is too large"))
}
