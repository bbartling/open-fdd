//! Explicit protected envelopes and aggregate compute budget (#1127 P1).

use std::env;

use anyhow::{bail, Context, Result};
use serde::Serialize;

use crate::cgroup::CapacityDiscovery;

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
    /// Aggregate DataFusion MemoryPool size (process-wide).
    pub compute_memory_bytes: u64,
    /// Compatibility per-job hint (OPENFDD_QUERY_MEMORY_MB); never larger than aggregate.
    pub query_memory_bytes: u64,
    pub compute_origin: String,
    pub query_origin: String,
    pub expensive_compute_available: bool,
    pub notes: Vec<String>,
}

impl ComputeBudget {
    /// Resolve aggregate compute budget.
    ///
    /// Prefer `OPENFDD_COMPUTE_MEMORY_MB` for the shared pool. `OPENFDD_QUERY_MEMORY_MB`
    /// remains a compatibility per-job ceiling bounded by the aggregate — it is not
    /// silently reinterpreted as N independent pools.
    pub fn resolve(discovery: &CapacityDiscovery, query_memory_mb: u64) -> Result<Self> {
        let mut notes = discovery.memory.notes.clone();
        let hard = discovery.memory.hard_limit_bytes;
        let reserves = ReserveEnvelopes::from_env_or_defaults(hard)?;
        let query_bytes = query_memory_mb
            .checked_mul(1024 * 1024)
            .ok_or_else(|| anyhow::anyhow!("OPENFDD_QUERY_MEMORY_MB is too large"))?;

        let (compute_bytes, compute_origin, expensive_ok) =
            if let Ok(raw) = env::var("OPENFDD_COMPUTE_MEMORY_MB") {
                let mb: u64 = raw
                    .trim()
                    .parse()
                    .context("OPENFDD_COMPUTE_MEMORY_MB must be a positive integer")?;
                if mb == 0 {
                    bail!("OPENFDD_COMPUTE_MEMORY_MB must be greater than zero");
                }
                let bytes = mb
                    .checked_mul(1024 * 1024)
                    .ok_or_else(|| anyhow::anyhow!("OPENFDD_COMPUTE_MEMORY_MB is too large"))?;
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
                            (clamped.max(1), "OPENFDD_COMPUTE_MEMORY_MB_clamped_unavailable".into(), false)
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
                        "Protected envelopes leave <64 MiB compute — expensive work unavailable"
                            .into(),
                    );
                    (
                        available.max(1),
                        "cgroup_minus_reserves_unavailable".into(),
                        false,
                    )
                } else {
                    // Cap initial aggregate at query_memory when COMPUTE unset so operators
                    // who sized QUERY_MEMORY keep a familiar ceiling — shared, not multiplied.
                    let capped = available.min(query_bytes.max(64 * 1024 * 1024));
                    notes.push(
                        "OPENFDD_COMPUTE_MEMORY_MB unset: aggregate pool = min(cgroup−reserves, QUERY_MEMORY); concurrent sessions share one pool"
                            .into(),
                    );
                    (capped, "cgroup_minus_reserves_capped_by_query".into(), true)
                }
            } else {
                notes.push(
                    "No cgroup hard limit: aggregate pool falls back to OPENFDD_QUERY_MEMORY_MB (shared, not per-session)"
                        .into(),
                );
                (
                    query_bytes.max(1),
                    "OPENFDD_QUERY_MEMORY_MB_shared_fallback".into(),
                    true,
                )
            };

        let query_capped = query_bytes.min(compute_bytes).max(1);
        if query_capped < query_bytes {
            notes.push(
                "OPENFDD_QUERY_MEMORY_MB capped to aggregate OPENFDD_COMPUTE_MEMORY_MB envelope"
                    .into(),
            );
        }

        Ok(Self {
            hard_capacity_bytes: hard,
            reserves,
            compute_memory_bytes: compute_bytes.max(1),
            query_memory_bytes: query_capped,
            compute_origin,
            query_origin: "OPENFDD_QUERY_MEMORY_MB".into(),
            expensive_compute_available: expensive_ok,
            notes,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cgroup::{CpuDiscovery, MemoryDiscovery};

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

    #[test]
    fn compute_env_wins_and_is_not_multiplied_by_sessions() {
        std::env::set_var("OPENFDD_COMPUTE_MEMORY_MB", "512");
        std::env::remove_var("OPENFDD_INGEST_RESERVE_MB");
        let budget = ComputeBudget::resolve(&discovery(Some(24_000_000_000)), 512).unwrap();
        std::env::remove_var("OPENFDD_COMPUTE_MEMORY_MB");
        assert_eq!(budget.compute_memory_bytes, 512 * 1024 * 1024);
        assert_eq!(budget.compute_origin, "OPENFDD_COMPUTE_MEMORY_MB");
        assert!(budget.expensive_compute_available);
    }

    #[test]
    fn tiny_cgroup_marks_expensive_unavailable() {
        std::env::remove_var("OPENFDD_COMPUTE_MEMORY_MB");
        // 200 MiB hard; default reserves exceed leftover.
        let budget = ComputeBudget::resolve(&discovery(Some(200 * 1024 * 1024)), 512).unwrap();
        assert!(!budget.expensive_compute_available);
    }
}
