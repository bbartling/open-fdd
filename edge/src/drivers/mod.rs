//! Driver layer for the Rust-only Open-FDD edge.
//!
//! Live field-bus paths use real protocol stacks only (no simulated OT data):
//!
//! - `bacnet` (facade) + `bacnet_live` (rusty-bacnet wire I/O)
//! - `modbus` (facade) + `modbus_live` (rusty-modbus wire I/O)
//! - `haystack` => [rusty-haystack-client](https://github.com/jscott3201/rusty-haystack)
//! - `json_api` => reqwest HTTP with JSON body parsing
//!
//! BACnet/Modbus default to live wire I/O (`OPENFDD_*_MODE=live`). Non-live mode blocks
//! operations with API errors — it does not synthesize field values.
//! Haystack fixture mode (`OPENFDD_HAYSTACK_FIXTURE=1`) is CI-only and explicitly labeled.

pub mod bacnet;
pub mod bacnet_live;
pub mod bacnet_server;
pub mod bacnet_server_runtime;
pub mod haystack;
pub mod json_api;
pub mod live_gate;
pub mod modbus;
pub mod modbus_live;
pub mod tree;
