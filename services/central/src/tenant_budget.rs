//! Wave L Phase 5 - per-tenant request budgets (noisy-neighbor guardrails).
//!
//! Default: **disabled** when `OPENFDD_MULTI_TENANT` is OFF, or when
//! `OPENFDD_TENANT_BUDGETS` is unset/0/false. Single-hub semantics unchanged.
//! Lab notes: `docs/operations/WAVE_L_TENANT_BUDGETS_LAB.md`.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use utoipa::ToSchema;

use crate::tenant::multi_tenant_enabled;

/// Env flag - enable per-tenant budgets. Default off.
pub fn tenant_budgets_enabled() -> bool {
    if !multi_tenant_enabled() {
        return false;
    }
    match std::env::var("OPENFDD_TENANT_BUDGETS") {
        Ok(v) => matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        ),
        Err(_) => false,
    }
}

fn env_u32(name: &str, default: u32) -> u32 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.trim().parse().ok())
        .unwrap_or(default)
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct TenantBudgetConfig {
    pub enabled: bool,
    /// Max FDD `/api/fdd/run` accepts per tenant per rolling minute.
    pub fdd_runs_per_minute: u32,
    /// Max `POST /api/jobs` creates per tenant per rolling hour.
    pub jobs_per_hour: u32,
}

impl TenantBudgetConfig {
    pub fn from_env() -> Self {
        Self {
            enabled: tenant_budgets_enabled(),
            fdd_runs_per_minute: env_u32("OPENFDD_TENANT_FDD_RUNS_PER_MIN", 30),
            jobs_per_hour: env_u32("OPENFDD_TENANT_JOBS_PER_HOUR", 60),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BudgetKind {
    FddRun,
    JobCreate,
}

impl BudgetKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::FddRun => "fdd_run",
            Self::JobCreate => "job_create",
        }
    }
}

#[derive(Debug, Default)]
struct WindowCounter {
    stamps: Vec<Instant>,
}

impl WindowCounter {
    fn prune(&mut self, window: Duration, now: Instant) {
        self.stamps.retain(|t| now.duration_since(*t) < window);
    }

    fn count(&mut self, window: Duration, now: Instant) -> usize {
        self.prune(window, now);
        self.stamps.len()
    }

    fn record(&mut self, now: Instant) {
        self.stamps.push(now);
    }
}

/// Process-local sliding-window counters keyed by tenant + kind.
#[derive(Debug, Default)]
pub struct TenantBudgetTracker {
    inner: Mutex<HashMap<(String, &'static str), WindowCounter>>,
}

impl TenantBudgetTracker {
    pub fn new() -> Self {
        Self::default()
    }

    /// Fail-closed when enabled and over limit; always Ok when disabled.
    pub fn check_and_record(
        &self,
        cfg: &TenantBudgetConfig,
        tenant_id: &str,
        kind: BudgetKind,
    ) -> Result<(), String> {
        if !cfg.enabled {
            return Ok(());
        }
        let (limit, window) = match kind {
            BudgetKind::FddRun => (cfg.fdd_runs_per_minute, Duration::from_secs(60)),
            BudgetKind::JobCreate => (cfg.jobs_per_hour, Duration::from_secs(3600)),
        };
        if limit == 0 {
            return Err(format!(
                "tenant budget deny: {} limit is 0 for tenant {tenant_id}",
                kind.as_str()
            ));
        }
        let now = Instant::now();
        let mut map = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        let entry = map
            .entry((tenant_id.to_string(), kind.as_str()))
            .or_default();
        let n = entry.count(window, now);
        if n as u32 >= limit {
            return Err(format!(
                "tenant budget exceeded: {} limit={limit}/window for tenant {tenant_id}",
                kind.as_str()
            ));
        }
        entry.record(now);
        Ok(())
    }
}

#[derive(Debug, Serialize, ToSchema)]
pub struct TenantBudgetsResponse {
    pub ok: bool,
    pub multi_tenant: bool,
    pub budgets: TenantBudgetConfig,
    /// Active tenant used for accounting when enabled (`legacy` when OFF).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub active_tenant_id: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Mutex, MutexGuard};

    static ENV_LOCK: Mutex<()> = Mutex::new(());
    fn lock_env() -> MutexGuard<'static, ()> {
        ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner())
    }

    #[test]
    fn budgets_disabled_when_multi_tenant_off() {
        let _g = lock_env();
        std::env::remove_var("OPENFDD_MULTI_TENANT");
        std::env::set_var("OPENFDD_TENANT_BUDGETS", "1");
        assert!(!tenant_budgets_enabled());
        std::env::remove_var("OPENFDD_TENANT_BUDGETS");
    }

    #[test]
    fn budgets_enabled_only_when_both_on() {
        let _g = lock_env();
        std::env::set_var("OPENFDD_MULTI_TENANT", "1");
        std::env::set_var("OPENFDD_TENANT_BUDGETS", "1");
        assert!(tenant_budgets_enabled());
        std::env::remove_var("OPENFDD_TENANT_BUDGETS");
        std::env::remove_var("OPENFDD_MULTI_TENANT");
    }

    #[test]
    fn tracker_allows_under_limit_and_denies_over() {
        let tracker = TenantBudgetTracker::new();
        let cfg = TenantBudgetConfig {
            enabled: true,
            fdd_runs_per_minute: 2,
            jobs_per_hour: 10,
        };
        tracker
            .check_and_record(&cfg, "acme", BudgetKind::FddRun)
            .unwrap();
        tracker
            .check_and_record(&cfg, "acme", BudgetKind::FddRun)
            .unwrap();
        let err = tracker
            .check_and_record(&cfg, "acme", BudgetKind::FddRun)
            .unwrap_err();
        assert!(err.contains("exceeded"));
        // other tenant independent
        tracker
            .check_and_record(&cfg, "beta", BudgetKind::FddRun)
            .unwrap();
    }

    #[test]
    fn tracker_noop_when_disabled() {
        let tracker = TenantBudgetTracker::new();
        let cfg = TenantBudgetConfig {
            enabled: false,
            fdd_runs_per_minute: 1,
            jobs_per_hour: 1,
        };
        for _ in 0..5 {
            tracker
                .check_and_record(&cfg, "legacy", BudgetKind::FddRun)
                .unwrap();
        }
    }
}
