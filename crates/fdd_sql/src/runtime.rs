//! Process-wide shared DataFusion runtime (#1127 P1 / #1179).
//!
//! One aggregate [`FairSpillPool`] (wrapped in [`TrackConsumersPool`]) serves
//! isolated `SessionContext`s. Pool size is a fraction of the detected
//! cgroup/host limit minus reserves — not `OPENFDD_QUERY_MEMORY_MB` (that is
//! the per-request ceiling). Spill lands under `OPENFDD_DATAFUSION_SPILL_DIR`
//! (default `<storage_root>/.datafusion-spill`).

use std::num::NonZeroUsize;
use std::path::PathBuf;
use std::sync::{Arc, OnceLock};

use anyhow::{anyhow, Context, Result};
use datafusion::execution::memory_pool::{FairSpillPool, TrackConsumersPool};
use datafusion::execution::runtime_env::{RuntimeEnv, RuntimeEnvBuilder};
use datafusion::prelude::{SessionConfig, SessionContext};
use fdd_resources::{discover_capacity, ComputeBudget};
use fdd_store::{HistorianConfig, StorageUrl};
use serde::Serialize;

use crate::tuning::{clamp_tuning_to_cpu, DataFusionTuning};

/// Default spill directory byte budget when unset (tied loosely to disk budget).
const DEFAULT_SPILL_MAX_BYTES: u64 = 8 * 1024 * 1024 * 1024;

#[derive(Debug, Clone, Serialize)]
pub struct SharedRuntimeInfo {
    pub compute_memory_bytes: u64,
    pub query_memory_bytes: u64,
    pub hard_capacity_bytes: Option<u64>,
    pub compute_origin: String,
    pub query_origin: String,
    pub compute_fraction: Option<String>,
    pub pool_kind: String,
    pub expensive_compute_available: bool,
    pub spill_directory: Option<String>,
    pub spill_max_bytes: Option<u64>,
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

fn default_spill_dir(config: &HistorianConfig) -> Option<PathBuf> {
    if let Some(explicit) = &config.spill_directory {
        return Some(explicit.clone());
    }
    match &config.storage_url {
        StorageUrl::File { root } => Some(root.join(".datafusion-spill")),
        StorageUrl::S3 { .. } => {
            // Object storage has no local root; fall back to workspace temp.
            let workspace =
                std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
            Some(PathBuf::from(workspace).join("data/openfdd/.datafusion-spill"))
        }
    }
}

fn spill_max_bytes() -> u64 {
    match std::env::var("OPENFDD_DATAFUSION_SPILL_MAX_BYTES") {
        Ok(raw) => raw
            .trim()
            .parse::<u64>()
            .ok()
            .filter(|n| *n > 0)
            .unwrap_or(DEFAULT_SPILL_MAX_BYTES),
        Err(_) => match std::env::var("OPENFDD_DATAFUSION_SPILL_MAX_GB") {
            Ok(raw) => raw
                .trim()
                .parse::<u64>()
                .ok()
                .filter(|n| *n > 0)
                .map(|gb| gb.saturating_mul(1024 * 1024 * 1024))
                .unwrap_or(DEFAULT_SPILL_MAX_BYTES),
            Err(_) => DEFAULT_SPILL_MAX_BYTES,
        },
    }
}

fn build_shared(config: &HistorianConfig) -> Result<SharedCompute> {
    let discovery = discover_capacity();
    let budget = ComputeBudget::resolve(&discovery, config.query_memory_mb)?;
    let memory_bytes = usize::try_from(budget.compute_memory_bytes)
        .map_err(|_| anyhow!("compute memory budget exceeds platform address space"))?;

    let spill_dir = default_spill_dir(config);
    let spill_cap = spill_max_bytes();
    let mut notes = budget.notes.clone();

    // FairSpillPool + TrackConsumersPool — Greedy via with_memory_limit is wrong
    // for concurrent spillable operators (#1179).
    let pool = Arc::new(TrackConsumersPool::new(
        FairSpillPool::new(memory_bytes),
        NonZeroUsize::new(5).expect("non-zero"),
    ));
    let mut runtime = RuntimeEnvBuilder::new().with_memory_pool(pool);

    if let Some(ref spill) = spill_dir {
        std::fs::create_dir_all(spill)
            .with_context(|| format!("create DataFusion spill dir {}", spill.display()))?;
        // Probe writability before session creation (fail loud).
        let probe = spill.join(".openfdd-spill-probe");
        std::fs::write(&probe, b"ok")
            .with_context(|| format!("spill dir not writable: {}", spill.display()))?;
        let _ = std::fs::remove_file(&probe);
        runtime = runtime
            .with_temp_file_path(spill)
            .with_max_temp_directory_size(spill_cap);
        notes.push(format!(
            "FairSpillPool spill dir={} max_bytes={spill_cap}",
            spill.display()
        ));
    } else {
        notes.push("No spill directory resolved — FairSpillPool cannot spill to disk".into());
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
        hard_capacity_bytes: budget.hard_capacity_bytes,
        compute_origin: budget.compute_origin,
        query_origin: budget.query_origin,
        compute_fraction: budget.compute_fraction,
        pool_kind: "FairSpillPool+TrackConsumersPool".into(),
        expensive_compute_available: budget.expensive_compute_available,
        spill_directory: spill_dir.as_ref().map(|p| p.display().to_string()),
        spill_max_bytes: spill_dir.as_ref().map(|_| spill_cap),
        effective_target_partitions: tuning.target_partitions,
        effective_batch_size: tuning.batch_size,
        notes,
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

/// Production session factory: shared FairSpillPool + env-tuned SessionConfig.
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

    let pool = Arc::new(TrackConsumersPool::new(
        FairSpillPool::new(memory_bytes),
        NonZeroUsize::new(5).expect("non-zero"),
    ));
    let mut runtime = RuntimeEnvBuilder::new().with_memory_pool(pool);
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
            .unwrap_or_else(std::env::temp_dir);
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
        assert_eq!(built.info.pool_kind, "FairSpillPool+TrackConsumersPool");
        // Display proves FairSpillPool is inside TrackConsumersPool.
        let pool_dbg = format!("{}", a.runtime_env().memory_pool);
        assert!(
            pool_dbg.contains("fair") && pool_dbg.contains("track_consumers"),
            "unexpected pool display: {pool_dbg}"
        );
        std::env::remove_var("OPENFDD_COMPUTE_MEMORY_MB");
    }

    #[test]
    fn spill_dir_created_and_writable_or_build_fails() {
        std::env::set_var("OPENFDD_COMPUTE_MEMORY_MB", "64");
        let tmp = TempDir::new().unwrap();
        let spill = tmp.path().join("nested").join("spill");
        let config = cfg(Some(spill.clone()), 64);
        let built = build_shared(&config).unwrap();
        assert!(spill.is_dir());
        assert_eq!(
            built.info.spill_directory.as_deref(),
            Some(spill.to_str().unwrap())
        );
        std::env::remove_var("OPENFDD_COMPUTE_MEMORY_MB");
    }

    #[test]
    fn default_spill_under_storage_root_when_unset() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path().join("hist");
        std::fs::create_dir_all(&root).unwrap();
        let config = HistorianConfig {
            storage_url: StorageUrl::File { root: root.clone() },
            flush_rows: 5_000,
            flush_seconds: 60,
            target_file_mb: 128,
            compaction_min_files: 8,
            compaction_enabled: true,
            query_memory_mb: 64,
            spill_directory: None,
            legacy_parquet_root: None,
        };
        let resolved = default_spill_dir(&config).unwrap();
        assert_eq!(resolved, root.join(".datafusion-spill"));
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
