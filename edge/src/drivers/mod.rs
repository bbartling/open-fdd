//! Driver layer for the Rust-only Open-FDD edge.
//!
//! The fast prototype keeps these drivers deterministic and simulator-backed so
//! Docker Desktop can run without field hardware. The module boundaries mirror
//! the production direction:
//!
//! - `bacnet` + `bacnet_live` => rusty-bacnet discovery/read/poll/priority-array path
//! - `modbus` => rusty-modbus scan/read path
//! - `json_api` => external HTTP JSON telemetry path
//! - `haystack` => Project Haystack read/nav/ops path, including Niagara replacement

pub mod bacnet;
pub mod bacnet_live;
pub mod haystack;
pub mod json_api;
pub mod modbus;
pub mod modbus_live;
