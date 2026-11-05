//! Agent-first ingest contracts and strict validation gates.

pub mod commissioning_validate;
pub mod contract;
pub mod validate;

pub use commissioning_validate::validate_commissioning;
pub use contract::contract_json;
pub use validate::{csv_strict_enabled, evaluate_csv_session, ValidationInput};
