//! Shared Postgres ingest queue, leases, and scoped job HTTP.

mod client;
mod coverage;
pub(crate) mod cursor;
pub(crate) mod http;
mod memory;
mod model;
mod portal_env;
mod postgres;
pub(crate) mod replay_horizon;
mod scale;
pub(crate) mod schedule;
mod status;
mod worker;

#[cfg(test)]
mod durability;
#[cfg(test)]
mod ledger_contract;
#[cfg(test)]
mod replay_horizon_acceptance;
#[cfg(test)]
mod scope_acceptance;
#[cfg(test)]
mod site_backfill_acceptance;
#[cfg(test)]
mod upgrade_acceptance;
#[cfg(test)]
mod writer_fence;

pub use client::QueueClient;
pub use worker::spawn_with_shutdown;
