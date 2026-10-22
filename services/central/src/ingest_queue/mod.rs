//! Shared Postgres ingest queue, leases, and scoped job HTTP.

mod client;
pub(crate) mod http;
mod memory;
mod model;
mod postgres;
mod scale;
mod schedule;
mod worker;

#[cfg(test)]
mod ledger_contract;
#[cfg(test)]
mod scope_acceptance;

pub use client::QueueClient;
pub use worker::spawn_with_shutdown;
