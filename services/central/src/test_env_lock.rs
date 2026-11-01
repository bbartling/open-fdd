//! Process-wide lock for tests that mutate `OPENFDD_*` env vars.
//!
//! Multiple modules (`tenant`, `tenant_budget`, ...) must share one lock - a
//! per-module `ENV_LOCK` does not serialize across modules and flakes
//! (e.g. `tenant::tests::resolve_on_scopes_buildings` vs budget flag tests).

use std::path::Path;
use std::sync::{Mutex, MutexGuard};

static ENV_LOCK: Mutex<()> = Mutex::new(());

pub fn lock_env() -> MutexGuard<'static, ()> {
    ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner())
}

/// Sets `OPENFDD_WORKSPACE` for the guard's lifetime, then restores the prior value.
///
/// Declare this after `lock_env()` so the variable is restored before the lock drops.
pub struct WorkspaceEnv {
    prev: Option<String>,
}

impl WorkspaceEnv {
    pub fn set(path: &Path) -> Self {
        let prev = std::env::var("OPENFDD_WORKSPACE").ok();
        std::env::set_var("OPENFDD_WORKSPACE", path);
        Self { prev }
    }
}

impl Drop for WorkspaceEnv {
    fn drop(&mut self) {
        match self.prev.take() {
            Some(v) => std::env::set_var("OPENFDD_WORKSPACE", v),
            None => std::env::remove_var("OPENFDD_WORKSPACE"),
        }
    }
}
