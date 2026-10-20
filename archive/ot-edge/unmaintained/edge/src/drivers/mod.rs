//! Driver layer for Open-FDD Central.
//!
//! Live field-bus protocols (BACnet / Modbus / Haystack wire I/O) live in
//! `openfdd-fieldbus` and arrive here over MQTTS. Remaining modules expose
//! retired-compatible JSON facades and the JSON API / model helpers.

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
