//! Fault detection layer.
//!
//! FDD in this Rust-only baseline is DataFusion SQL oriented. Driver data lands
//! in Arrow-shaped historian tables, then rules are SQL over those tables.

pub mod datafusion_sql;
