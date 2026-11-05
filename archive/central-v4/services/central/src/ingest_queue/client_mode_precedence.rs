//! Queue coordination precedence: durable Postgres when `OPENFDD_DATABASE_URL` is set.
//!
//! `OPENFDD_INGEST_QUEUE=memory` applies only without a database URL. Connection
//! failures surface as errors; there is no silent fallback to process-local memory.

use chrono::Utc;

use super::client::{Coordination, QueueClient};
use super::model::NewJob;
use crate::test_env_lock::{lock_env, run_env_locked};

struct EnvGuard {
    key: &'static str,
    prev: Option<String>,
}

impl EnvGuard {
    fn set(key: &'static str, value: &str) -> Self {
        let prev = std::env::var(key).ok();
        std::env::set_var(key, value);
        Self { key, prev }
    }

    fn unset(key: &'static str) -> Self {
        let prev = std::env::var(key).ok();
        std::env::remove_var(key);
        Self { key, prev }
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        match self.prev.take() {
            Some(value) => std::env::set_var(self.key, value),
            None => std::env::remove_var(self.key),
        }
    }
}

#[test]
fn coordination_postgres_when_database_url_set_even_with_memory_env() {
    let _lock = lock_env();
    let _db = EnvGuard::set(
        "OPENFDD_DATABASE_URL",
        "postgres://openfdd:openfdd@localhost:5432/openfdd",
    );
    let _queue = EnvGuard::set("OPENFDD_INGEST_QUEUE", "memory");
    assert_eq!(QueueClient::coordination(), Coordination::Postgres);
}

#[test]
fn coordination_memory_only_without_database_url() {
    let _lock = lock_env();
    let _db = EnvGuard::unset("OPENFDD_DATABASE_URL");
    let _queue = EnvGuard::set("OPENFDD_INGEST_QUEUE", "memory");
    assert_eq!(QueueClient::coordination(), Coordination::ExplicitMemory);
}

#[test]
fn coordination_unavailable_without_database_or_memory_flag() {
    let _lock = lock_env();
    let _db = EnvGuard::unset("OPENFDD_DATABASE_URL");
    let _queue = EnvGuard::unset("OPENFDD_INGEST_QUEUE");
    assert_eq!(QueueClient::coordination(), Coordination::Unavailable);
}

#[test]
fn enqueue_errors_when_postgres_unreachable_does_not_use_memory() {
    run_env_locked(async {
        let _db = EnvGuard::set(
            "OPENFDD_DATABASE_URL",
            "postgres://openfdd:openfdd@127.0.0.1:9/openfdd_nope",
        );
        let _queue = EnvGuard::unset("OPENFDD_INGEST_QUEUE");
        assert_eq!(QueueClient::coordination(), Coordination::Postgres);
        let client = QueueClient::memory();
        let now = Utc::now();
        let job = NewJob {
            tenant_id: "w2c-precedence".into(),
            canonical_site: "site".into(),
            provider_instance_id: "portal".into(),
            device_id: "AHU_1".into(),
            model_revision: "rev".into(),
            logical_window_start: now,
            logical_window_end: now + chrono::Duration::hours(1),
            shard: String::new(),
            not_before: now,
            estimated_cost: 1,
            requested_points_digest: None,
        };
        let err = client.enqueue(job, now).await;
        assert!(
            err.is_err(),
            "unreachable postgres must error, not memory enqueue"
        );
    });
}
