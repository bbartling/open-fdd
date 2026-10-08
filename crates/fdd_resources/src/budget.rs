//! Explicit protected envelopes and aggregate compute budget (#1127 P1 / #1179).
//!
//! Aggregate pool size is a **fraction of the detected cgroup/host hard limit**
//! minus reserve envelopes — portable across 8 GiB edges, 24 GiB Railway, and
//! large VMs. Absolute env overrides are clamped and reported. Never hard-code
//! Railway plan sizes in product defaults.

use std::env;

use anyhow::{bail, Context, Result};
use serde::Serialize;

use crate::cgroup::CapacityDiscovery;

/// Default share of (hard − reserves) given to the process-wide DataFusion pool
/// when `OPENFDD_COMPUTE_MEMORY_MB` is unset.
pub const DEFAULT_COMPUTE_MEMORY_FRACTION: f64 = 0.50;

/// Floor for the aggregate FairSpillPool when capacity allows.
const MIN_POOL_BYTES: u64 = 256 * 1024 * 1024;

/// Reserved process envelopes that must not be given to the DataFusion pool.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ReserveEnvelopes {
    pub ingest_bytes: u64,
    pub staging_bytes: u64,
    pub control_bytes: u64,
    pub background_bytes: u64,
    pub headroom_bytes: u64,
}

impl ReserveEnvelopes {
    pub fn total(&self) -> u64 {
        self.ingest_bytes
            .saturating_add(self.staging_bytes)
            .saturating_add(self.control_bytes)
            .saturating_add(self.background_bytes)
            .saturating_add(self.headroom_bytes)
    }

    /// Defaults are conservative starting points — calibrate from measured workloads.
    pub fn from_env_or_defaults(hard_capacity: Option<u64>) -> Result<Self> {
        let pct = |name: &str, default_mb: u64, frac: f64| -> Result<u64> {
            if let Ok(raw) = env::var(name) {
                let mb: u64 = raw
                    .trim()
                    .parse()
                    .with_context(|| format!("{name} must be a positive integer (MiB)"))?;
                if mb == 0 {
                    bail!("{name} must be greater than zero");
                }
                return Ok(mb.saturating_mul(1024 * 1024));
            }
            if let Some(hard) = hard_capacity {
                let from_frac = ((hard as f64) * frac).round() as u64;
                let floor = default_mb.saturating_mul(1024 * 1024);
                Ok(from_frac.max(floor).min(hard / 4).max(floor.min(hard / 8)))
            } else {
                Ok(default_mb.saturating_mul(1024 * 1024))
            }
        };
        Ok(Self {
            ingest_bytes: pct("OPENFDD_INGEST_RESERVE_MB", 256, 0.10)?,
            staging_bytes: pct("OPENFDD_STAGING_RESERVE_MB", 128, 0.05)?,
            control_bytes: pct("OPENFDD_CONTROL_RESERVE_MB", 128, 0.05)?,
            background_bytes: pct("OPENFDD_BACKGROUND_RESERVE_MB", 64, 0.03)?,
            headroom_bytes: pct("OPENFDD_MEMORY_HEADROOM_MB", 256, 0.08)?,
        })
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ComputeBudget {
    pub hard_capacity_bytes: Option<u64>,
    pub reserves: ReserveEnvelopes,
    /// Aggregate DataFusion MemoryPool size (process-wide FairSpillPool).
    pub compute_memory_bytes: u64,
    /// Per-request / per-chunk reservation ceiling (`OPENFDD_QUERY_MEMORY_MB`).
    /// Never larger than the aggregate pool. Default `pool/2` when env unset.
    pub query_memory_bytes: u64,
    pub compute_origin: String,
    pub query_origin: String,
    pub expensive_compute_available: bool,
    pub compute_fraction: Option<String>,
    pub notes: Vec<String>,
}

fn parse_positive_mb(name: &str, raw: &str) -> Result<u64> {
    let mb: u64 = raw
        .trim()
        .parse()
        .with_context(|| format!("{name} must be a positive integer"))?;
    if mb == 0 {
        bail!("{name} must be greater than zero");
    }
    mb.checked_mul(1024 * 1024)
        .ok_or_else(|| anyhow::anyhow!("{name} is too large"))
}

fn compute_fraction_from_env(notes: &mut Vec<String>) -> Result<f64> {
    match env::var("OPENFDD_COMPUTE_MEMORY_FRACTION") {
        Ok(raw) => {
            let f: f64 = raw
                .trim()
                .parse()
                .context("OPENFDD_COMPUTE_MEMORY_FRACTION must be a float in (0, 1]")?;
            if !(f > 0.0 && f <= 1.0) {
                bail!("OPENFDD_COMPUTE_MEMORY_FRACTION must be in (0, 1]");
            }
            Ok(f)
        }
        Err(_) => {
            notes.push(format!(
                "OPENFDD_COMPUTE_MEMORY_FRACTION unset: using default {DEFAULT_COMPUTE_MEMORY_FRACTION}"
            ));
            Ok(DEFAULT_COMPUTE_MEMORY_FRACTION)
        }
    }
}

impl ComputeBudget {
    /// Resolve aggregate compute budget.
    ///
    /// - Pool (`compute_memory_bytes`): `OPENFDD_COMPUTE_MEMORY_MB` when set
    ///   (clamped to `hard − reserves`); else
    ///   `(hard − reserves) × OPENFDD_COMPUTE_MEMORY_FRACTION` (default 0.50),
    ///   floored at 256 MiB when capacity allows. No hard limit → host
    ///   `MemTotal` path already in discovery, or `QUERY` fallback.
    /// - Per-request (`query_memory_bytes`): explicit `OPENFDD_QUERY_MEMORY_MB`
    ///   when set (clamped to pool); else `pool / 2`. Never sizes the aggregate
    ///   pool.
    ///
    /// `query_memory_mb` is a compatibility hint from `HistorianConfig` used only
    /// when the env var is unset **and** there is no discoverable hard limit
    /// (legacy shared-fallback path).
    pub fn resolve(discovery: &CapacityDiscovery, query_memory_mb: u64) -> Result<Self> {
        let mut notes = discovery.memory.notes.clone();
        let hard = discovery.memory.hard_limit_bytes;
        let reserves = ReserveEnvelopes::from_env_or_defaults(hard)?;

        let query_env = env::var("OPENFDD_QUERY_MEMORY_MB").ok();
        let query_explicit_bytes = match query_env.as_deref() {
            Some(raw) => Some(parse_positive_mb("OPENFDD_QUERY_MEMORY_MB", raw)?),
            None => None,
        };

        let fraction = compute_fraction_from_env(&mut notes)?;
        let mut compute_fraction_label = None;

        let (compute_bytes, compute_origin, expensive_ok) = if let Ok(raw) =
            env::var("OPENFDD_COMPUTE_MEMORY_MB")
        {
            let bytes = parse_positive_mb("OPENFDD_COMPUTE_MEMORY_MB", &raw)?;
            if let Some(hard_b) = hard {
                if bytes + reserves.total() > hard_b {
                    notes.push(
                        "OPENFDD_COMPUTE_MEMORY_MB + reserves exceed discovered hard capacity; clamping"
                            .into(),
                    );
                    let clamped = hard_b.saturating_sub(reserves.total());
                    if clamped < 64 * 1024 * 1024 {
                        notes.push(
                            "Protected envelopes leave <64 MiB compute — expensive work unavailable"
                                .into(),
                        );
                        (
                            clamped.max(1),
                            "OPENFDD_COMPUTE_MEMORY_MB_clamped_unavailable".into(),
                            false,
                        )
                    } else {
                        (clamped, "OPENFDD_COMPUTE_MEMORY_MB_clamped".into(), true)
                    }
                } else {
                    (bytes, "OPENFDD_COMPUTE_MEMORY_MB".into(), true)
                }
            } else {
                (bytes, "OPENFDD_COMPUTE_MEMORY_MB".into(), true)
            }
        } else if let Some(hard_b) = hard {
            let available = hard_b.saturating_sub(reserves.total());
            if available < 64 * 1024 * 1024 {
                notes.push(
                    "Protected envelopes leave <64 MiB compute — expensive work unavailable".into(),
                );
                (
                    available.max(1),
                    "cgroup_minus_reserves_unavailable".into(),
                    false,
                )
            } else {
                let from_frac = ((available as f64) * fraction).round() as u64;
                let pool = from_frac
                    .max(MIN_POOL_BYTES.min(available))
                    .min(available)
                    .max(1);
                compute_fraction_label = Some(format!("{fraction}"));
                notes.push(format!(
                    "OPENFDD_COMPUTE_MEMORY_MB unset: FairSpillPool = (hard−reserves)×{fraction} = {pool} bytes (portable; QUERY_MEMORY is per-request only)"
                ));
                (pool, "cgroup_minus_reserves_times_fraction".into(), true)
            }
        } else {
            // Discovery already fell back to host MemTotal when possible; if still
            // None, use HistorianConfig / QUERY as last resort (shared, not per-session).
            let fallback = query_explicit_bytes.unwrap_or_else(|| {
                query_memory_mb
                    .saturating_mul(1024 * 1024)
                    .max(MIN_POOL_BYTES)
            });
            notes.push(
                "No hard memory limit discovered: aggregate pool falls back to QUERY/config (shared FairSpillPool, not per-session)"
                    .into(),
            );
            (
                fallback.max(1),
                "query_or_config_shared_fallback".into(),
                true,
            )
        };

        let (query_bytes, query_origin) = if let Some(explicit) = query_explicit_bytes {
            let capped = explicit.min(compute_bytes).max(1);
            if capped < explicit {
                notes.push(
                    "OPENFDD_QUERY_MEMORY_MB capped to aggregate FairSpillPool envelope".into(),
                );
            }
            (capped, "OPENFDD_QUERY_MEMORY_MB".into())
        } else {
            let half = (compute_bytes / 2).max(1);
            notes.push("OPENFDD_QUERY_MEMORY_MB unset: per-request ceiling = pool/2".into());
            (half, "pool_half_default".into())
        };

        Ok(Self {
            hard_capacity_bytes: hard,
            reserves,
            compute_memory_bytes: compute_bytes.max(1),
            query_memory_bytes: query_bytes,
            compute_origin,
            query_origin,
            expensive_compute_available: expensive_ok,
            compute_fraction: compute_fraction_label,
            notes,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cgroup::{CpuDiscovery, MemoryDiscovery};
    use std::sync::Mutex;

    // Env-mutating budget tests must not race (CI runs lib tests parallel).
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn discovery(hard: Option<u64>) -> CapacityDiscovery {
        CapacityDiscovery {
            memory: MemoryDiscovery {
                available: hard.is_some(),
                hard_limit_bytes: hard,
                current_bytes: Some(0),
                high_bytes: None,
                source: "test".into(),
                hierarchy_complete: hard.is_some(),
                notes: vec![],
            },
            cpu: CpuDiscovery {
                logical_cores: 4,
                cpuset_cores: Some(4),
                quota_cores: Some(4.0),
                effective_cores: 4,
                source: "test".into(),
                notes: vec![],
            },
        }
    }

    fn clear_budget_env() {
        for k in [
            "OPENFDD_COMPUTE_MEMORY_MB",
            "OPENFDD_COMPUTE_MEMORY_FRACTION",
            "OPENFDD_QUERY_MEMORY_MB",
            "OPENFDD_INGEST_RESERVE_MB",
            "OPENFDD_STAGING_RESERVE_MB",
            "OPENFDD_CONTROL_RESERVE_MB",
            "OPENFDD_BACKGROUND_RESERVE_MB",
            "OPENFDD_MEMORY_HEADROOM_MB",
        ] {
            std::env::remove_var(k);
        }
    }

    #[test]
    fn compute_env_wins_and_is_not_multiplied_by_sessions() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_budget_env();
        std::env::set_var("OPENFDD_COMPUTE_MEMORY_MB", "512");
        let budget = ComputeBudget::resolve(&discovery(Some(24_000_000_000)), 512).unwrap();
        clear_budget_env();
        assert_eq!(budget.compute_memory_bytes, 512 * 1024 * 1024);
        assert_eq!(budget.compute_origin, "OPENFDD_COMPUTE_MEMORY_MB");
        assert!(budget.expensive_compute_available);
    }

    #[test]
    fn tiny_cgroup_marks_expensive_unavailable() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_budget_env();
        // 200 MiB hard; default reserves exceed leftover.
        let budget = ComputeBudget::resolve(&discovery(Some(200 * 1024 * 1024)), 512).unwrap();
        clear_budget_env();
        assert!(!budget.expensive_compute_available);
    }

    #[test]
    fn fraction_pool_scales_across_host_sizes() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_budget_env();
        // Pin reserves so math is deterministic across hosts.
        std::env::set_var("OPENFDD_INGEST_RESERVE_MB", "256");
        std::env::set_var("OPENFDD_STAGING_RESERVE_MB", "128");
        std::env::set_var("OPENFDD_CONTROL_RESERVE_MB", "128");
        std::env::set_var("OPENFDD_BACKGROUND_RESERVE_MB", "64");
        std::env::set_var("OPENFDD_MEMORY_HEADROOM_MB", "256");
        // total reserves = 832 MiB
        let reserve = 832u64 * 1024 * 1024;

        let cases = [
            (8u64 * 1024 * 1024 * 1024, "8g"),
            (24u64 * 1024 * 1024 * 1024, "24g"),
            (100u64 * 1024 * 1024 * 1024, "100g"),
        ];
        for (hard, label) in cases {
            let budget = ComputeBudget::resolve(&discovery(Some(hard)), 512).unwrap();
            let available = hard - reserve;
            let expected = ((available as f64) * 0.50).round() as u64;
            assert_eq!(
                budget.compute_memory_bytes, expected,
                "{label}: pool should be 50% of (hard−reserves)"
            );
            assert_eq!(
                budget.compute_origin, "cgroup_minus_reserves_times_fraction",
                "{label}"
            );
            // QUERY unset → pool/2 (not the old 512 MiB pool cap).
            assert_eq!(
                budget.query_memory_bytes,
                expected / 2,
                "{label}: per-request default is pool/2"
            );
            assert_eq!(budget.query_origin, "pool_half_default", "{label}");
            // Must not be pinned to Railway 10/24 GB absolutes.
            assert_ne!(budget.compute_memory_bytes, 10u64 * 1024 * 1024 * 1024);
        }
        clear_budget_env();
    }

    #[test]
    fn query_env_is_per_request_ceiling_not_pool_size() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_budget_env();
        std::env::set_var("OPENFDD_INGEST_RESERVE_MB", "256");
        std::env::set_var("OPENFDD_STAGING_RESERVE_MB", "128");
        std::env::set_var("OPENFDD_CONTROL_RESERVE_MB", "128");
        std::env::set_var("OPENFDD_BACKGROUND_RESERVE_MB", "64");
        std::env::set_var("OPENFDD_MEMORY_HEADROOM_MB", "256");
        std::env::set_var("OPENFDD_QUERY_MEMORY_MB", "512");
        let hard = 24u64 * 1024 * 1024 * 1024;
        let budget = ComputeBudget::resolve(&discovery(Some(hard)), 512).unwrap();
        clear_budget_env();
        // Pool stays fraction-sized; QUERY does not shrink it to 512 MiB.
        assert!(
            budget.compute_memory_bytes > 512 * 1024 * 1024,
            "pool must not be capped by QUERY_MEMORY"
        );
        assert_eq!(budget.query_memory_bytes, 512 * 1024 * 1024);
        assert_eq!(budget.query_origin, "OPENFDD_QUERY_MEMORY_MB");
    }

    #[test]
    fn absolute_compute_override_clamped_to_hard_minus_reserves() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|p| p.into_inner());
        clear_budget_env();
        std::env::set_var("OPENFDD_COMPUTE_MEMORY_MB", "20000");
        std::env::set_var("OPENFDD_INGEST_RESERVE_MB", "256");
        std::env::set_var("OPENFDD_STAGING_RESERVE_MB", "128");
        std::env::set_var("OPENFDD_CONTROL_RESERVE_MB", "128");
        std::env::set_var("OPENFDD_BACKGROUND_RESERVE_MB", "64");
        std::env::set_var("OPENFDD_MEMORY_HEADROOM_MB", "256");
        let hard = 8u64 * 1024 * 1024 * 1024;
        let budget = ComputeBudget::resolve(&discovery(Some(hard)), 512).unwrap();
        clear_budget_env();
        let reserve = 832u64 * 1024 * 1024;
        assert_eq!(budget.compute_memory_bytes, hard - reserve);
        assert_eq!(budget.compute_origin, "OPENFDD_COMPUTE_MEMORY_MB_clamped");
    }
}
