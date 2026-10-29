//! Portal ingest env parsing shared by the queue worker and provider poller.

use super::model::BudgetDefaults;

/// Documented default for `OPENFDD_PROVIDER_MAX_CONCURRENT` (parallel polls).
pub const DOCUMENTED_PROVIDER_MAX_CONCURRENT: u32 = 2;

/// Parse `OPENFDD_PROVIDER_MAX_CONCURRENT`. Unset or blank means use
/// [`DOCUMENTED_PROVIDER_MAX_CONCURRENT`]. Set but invalid returns an error.
pub fn provider_max_concurrent_from_env() -> Result<u32, String> {
    match std::env::var("OPENFDD_PROVIDER_MAX_CONCURRENT") {
        Err(std::env::VarError::NotPresent) => Ok(DOCUMENTED_PROVIDER_MAX_CONCURRENT),
        Err(std::env::VarError::NotUnicode(_)) => {
            Err("OPENFDD_PROVIDER_MAX_CONCURRENT is not valid UTF-8".into())
        }
        Ok(raw) if raw.trim().is_empty() => Ok(DOCUMENTED_PROVIDER_MAX_CONCURRENT),
        Ok(raw) => {
            let trimmed = raw.trim();
            let parsed: u32 = trimmed.parse().map_err(|_| {
                format!(
                    "OPENFDD_PROVIDER_MAX_CONCURRENT must be a positive integer, got {trimmed:?}"
                )
            })?;
            if parsed == 0 {
                return Err("OPENFDD_PROVIDER_MAX_CONCURRENT must be greater than zero".into());
            }
            Ok(parsed)
        }
    }
}

/// Effective parallel ingest claims: min(provider cap, portal budget in-flight).
pub fn effective_max_concurrent_jobs(budget: BudgetDefaults) -> Result<usize, String> {
    let provider_cap = provider_max_concurrent_from_env()?;
    let capped = provider_cap.min(budget.max_in_flight);
    usize::try_from(capped).map_err(|_| "portal concurrent job cap overflow".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Mutex, MutexGuard};

    static ENV_TEST_LOCK: Mutex<()> = Mutex::new(());

    fn env_test_guard() -> MutexGuard<'static, ()> {
        // Tests may poison this mutex when a case panics; recovering keeps the
        // env lock usable for later cases in the same process.
        ENV_TEST_LOCK
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
    }

    struct EnvGuard {
        key: &'static str,
        prior: Option<String>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: Option<&str>) -> Self {
            let prior = std::env::var(key).ok();
            match value {
                Some(v) => std::env::set_var(key, v),
                None => std::env::remove_var(key),
            }
            Self { key, prior }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            match &self.prior {
                Some(v) => std::env::set_var(self.key, v),
                None => std::env::remove_var(self.key),
            }
        }
    }

    #[test]
    fn unset_uses_documented_default() {
        let _lock = env_test_guard();
        let _g = EnvGuard::set("OPENFDD_PROVIDER_MAX_CONCURRENT", None);
        assert_eq!(
            provider_max_concurrent_from_env().unwrap(),
            DOCUMENTED_PROVIDER_MAX_CONCURRENT
        );
    }

    #[test]
    fn zero_and_garbage_are_config_errors() {
        let _lock = env_test_guard();
        let _g = EnvGuard::set("OPENFDD_PROVIDER_MAX_CONCURRENT", Some("0"));
        assert!(provider_max_concurrent_from_env().is_err());
        let _g = EnvGuard::set("OPENFDD_PROVIDER_MAX_CONCURRENT", Some("nope"));
        assert!(provider_max_concurrent_from_env().is_err());
    }
}
