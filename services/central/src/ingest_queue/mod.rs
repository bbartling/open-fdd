//! Shared Postgres ingest queue, leases, and scoped job HTTP.

mod client;
mod coverage;
pub(crate) mod cursor;
pub(crate) mod http;
mod memory;
mod model;
mod postgres;
mod scale;
pub(crate) mod schedule;
mod status;
mod worker;

#[cfg(test)]
mod durability;
#[cfg(test)]
mod ledger_contract;
#[cfg(test)]
mod scope_acceptance;
#[cfg(test)]
mod upgrade_acceptance;
#[cfg(test)]
mod writer_fence;

pub use client::QueueClient;
pub use worker::spawn_with_shutdown;
