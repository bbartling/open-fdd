//! Process-wide lock for tests that mutate `OPENFDD_*` env vars.
//!
//! Multiple modules (`tenant`, `tenant_budget`, ...) must share one lock - a
//! per-module `ENV_LOCK` does not serialize across modules and flakes
//! (e.g. `tenant::tests::resolve_on_scopes_buildings` vs budget flag tests).

use std::sync::{Mutex, MutexGuard};

static ENV_LOCK: Mutex<()> = Mutex::new(());

pub fn lock_env() -> MutexGuard<'static, ()> {
    ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner())
}
