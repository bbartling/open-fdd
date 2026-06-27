//! Driver layer for the Rust-only Open-FDD edge.
//!
//! Live field-bus paths use real protocol stacks:
//!
//! - `bacnet` + `bacnet_live` => [rusty-bacnet](https://github.com/jscott3201/rusty-bacnet)
//! - `modbus` + `modbus_live` => [rusty-modbus](https://github.com/jscott3201/rusty-modbus)
//! - `haystack` => [rusty-haystack-client](https://github.com/jscott3201/rusty-haystack)
//! - `json_api` => reqwest HTTP with JSON body parsing
//!
//! Explicit `OPENFDD_*_MODE=live` (default) for BACnet/Modbus field-bus I/O.
//! Haystack fixture mode (`OPENFDD_HAYSTACK_FIXTURE=1`) is CI-only for Haystack.

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
