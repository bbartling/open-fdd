//! Process-wide shared DataFusion runtime (#1127 P1).
//!
//! One aggregate `MemoryPool` serves isolated `SessionContext`s. Concurrent
//! FDD/AFDD/analytics must not each allocate a full `OPENFDD_QUERY_MEMORY_MB`
//! pool. Session/catalog isolation is preserved via separate contexts.

use std::sync::{Arc, OnceLock};

use anyhow::{anyhow, Context, Result};
use datafusion::execution::runtime_env::{RuntimeEnv, RuntimeEnvBuilder};
use datafusion::prelude::{SessionConfig, SessionContext};
use fdd_resources::{discover_capacity, ComputeBudget};
use fdd_store::HistorianConfig;
use serde::Serialize;

use crate::tuning::{clamp_tuning_to_cpu, DataFusionTuning};

#[derive(Debug, Clone, Serialize)]
pub struct SharedRuntimeInfo {
    pub compute_memory_bytes: u64,
    pub query_memory_bytes: u64,
    pub compute_origin: String,
    pub expensive_compute_available: bool,
    pub spill_directory: Option<String>,
    pub effective_target_partitions: Option<usize>,
    pub effective_batch_size: Option<usize>,
    pub notes: Vec<String>,
}

struct SharedCompute {
    runtime: Arc<RuntimeEnv>,
    session_config: SessionConfig,
    info: SharedRuntimeInfo,
}

static SHARED: OnceLock<SharedCompute> = OnceLock::new();

fn build_shared(config: &HistorianConfig) -> Result<SharedCompute> {
    let discovery = discover_capacity();
    let budget = ComputeBudget::resolve(&discovery, config.query_memory_mb)?;
    let memory_bytes = usize::try_from(budget.compute_memory_bytes)
        .map_err(|_| anyhow!("compute memory budget exceeds platform address space"))?;

    let mut runtime = RuntimeEnvBuilder::new().with_memory_limit(memory_bytes, 1.0);
    if let Some(spill_dir) = &config.spill_directory {
        std::fs::create_dir_all(spill_dir)
            .with_context(|| format!("create DataFusion spill dir {}", spill_dir.display()))?;
        runtime = runtime.with_temp_file_path(spill_dir);
    }
    let runtime = runtime
        .build_arc()
        .context("build shared DataFusion runtime")?;

    let mut tuning = DataFusionTuning::from_env()?;
    clamp_tuning_to_cpu(&mut tuning, discovery.cpu.effective_cores);
    let session_config = tuning.session_config()?;

    let info = SharedRuntimeInfo {
        compute_memory_bytes: budget.compute_memory_bytes,
        query_memory_bytes: budget.query_memory_bytes,
        compute_origin: budget.compute_origin,
        expensive_compute_available: budget.expensive_compute_available,
        spill_directory: config
            .spill_directory
            .as_ref()
            .map(|p| p.display().to_string()),
        effective_target_partitions: tuning.target_partitions,
        effective_batch_size: tuning.batch_size,
        notes: budget.notes,
    };

    Ok(SharedCompute {
        runtime,
        session_config,
        info,
    })
}

fn shared(config: &HistorianConfig) -> Result<&'static SharedCompute> {
    if let Some(existing) = SHARED.get() {
        return Ok(existing);
    }
    let built = build_shared(config)?;
    Ok(SHARED.get_or_init(|| built))
}

/// Effective shared-runtime diagnostics (initialized on first session factory call).
pub fn shared_runtime_info(config: &HistorianConfig) -> Result<SharedRuntimeInfo> {
    Ok(shared(config)?.info.clone())
}

/// Production session factory: shared aggregate pool + env-tuned SessionConfig.
pub fn new_shared_historian_session(config: &HistorianConfig) -> Result<SessionContext> {
    let shared = shared(config)?;
    if !shared.info.expensive_compute_available {
        anyhow::bail!(
            "expensive DataFusion compute unavailable: protected envelopes leave insufficient capacity ({})",
            shared.info.compute_origin
        );
    }
    Ok(SessionContext::new_with_config_rt(
        shared.session_config.clone(),
        shared.runtime.clone(),
    ))
}

/// Unshared session for unit tests that need private spill/memory (not production).
pub fn new_unshared_historian_session(config: &HistorianConfig) -> Result<SessionContext> {
    let memory_bytes = config
        .query_memory_mb
        .checked_mul(1024 * 1024)
        .ok_or_else(|| anyhow!("OPENFDD_QUERY_MEMORY_MB is too large"))?;
    let memory_bytes = usize::try_from(memory_bytes)
        .map_err(|_| anyhow!("OPENFDD_QUERY_MEMORY_MB exceeds platform address space"))?;

    let mut runtime = RuntimeEnvBuilder::new().with_memory_limit(memory_bytes, 1.0);
    if let Some(spill_dir) = &config.spill_directory {
        std::fs::create_dir_all(spill_dir)
            .with_context(|| format!("create DataFusion spill dir {}", spill_dir.display()))?;
        runtime = runtime.with_temp_file_path(spill_dir);
    }
    let runtime = runtime.build_arc().context("build DataFusion runtime")?;
    let session_config = DataFusionTuning::from_env()
        .and_then(|t| t.session_config())
        .unwrap_or_else(|_| SessionConfig::new());
    Ok(SessionContext::new_with_config_rt(session_config, runtime))
}

#[cfg(test)]
mod tests {
    use super::*;
    use fdd_store::StorageUrl;
    use tempfile::TempDir;

    fn cfg(spill: Option<std::path::PathBuf>, query_mb: u64) -> HistorianConfig {
        let tmp = spill
            .as_ref()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_else(|| std::env::temp_dir());
        HistorianConfig {
            storage_url: StorageUrl::File {
                root: tmp.join("history-root"),
            },
            flush_rows: 5_000,
            flush_seconds: 60,
            target_file_mb: 128,
            compaction_min_files: 8,
            compaction_enabled: true,
            query_memory_mb: query_mb,
            spill_directory: spill,
            legacy_parquet_root: None,
        }
    }

    #[test]
    fn two_sessions_share_one_memory_pool() {
        std::env::set_var("OPENFDD_COMPUTE_MEMORY_MB", "128");
        let tmp = TempDir::new().unwrap();
        let config = cfg(Some(tmp.path().join("spill")), 128);
        // Use unshared builder for isolation from other tests' OnceLock...
        // For aggregate proof, build two contexts from the same Arc manually.
        let built = build_shared(&config).unwrap();
        let a =
            SessionContext::new_with_config_rt(built.session_config.clone(), built.runtime.clone());
        let b =
            SessionContext::new_with_config_rt(built.session_config.clone(), built.runtime.clone());
        assert!(Arc::ptr_eq(&a.runtime_env(), &b.runtime_env()));
        assert!(Arc::ptr_eq(
            &a.runtime_env().memory_pool,
            &b.runtime_env().memory_pool
        ));
        std::env::remove_var("OPENFDD_COMPUTE_MEMORY_MB");
    }

    #[test]
    fn tuning_is_applied_to_session_config() {
        std::env::set_var("OPENFDD_DATAFUSION_BATCH_SIZE", "2048");
        std::env::set_var("OPENFDD_DATAFUSION_TARGET_PARTITIONS", "3");
        std::env::set_var("OPENFDD_COMPUTE_MEMORY_MB", "64");
        let tmp = TempDir::new().unwrap();
        let config = cfg(Some(tmp.path().join("spill")), 64);
        let built = build_shared(&config).unwrap();
        assert_eq!(built.info.effective_batch_size, Some(2048));
        assert_eq!(built.info.effective_target_partitions, Some(3));
        assert_eq!(built.session_config.batch_size(), 2048);
        assert_eq!(built.session_config.target_partitions(), 3);
        let _ctx =
            SessionContext::new_with_config_rt(built.session_config.clone(), built.runtime.clone());
        std::env::remove_var("OPENFDD_DATAFUSION_BATCH_SIZE");
        std::env::remove_var("OPENFDD_DATAFUSION_TARGET_PARTITIONS");
        std::env::remove_var("OPENFDD_COMPUTE_MEMORY_MB");
    }
}
