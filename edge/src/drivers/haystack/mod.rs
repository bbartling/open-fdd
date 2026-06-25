//! Project Haystack driver for Open-FDD (Niagara nHaystack + rusty-haystack-client).

pub mod client;
pub mod config;
pub mod driver;
pub mod fixture;
pub mod mock_server;
pub mod normalize;
pub mod parity;

pub use driver::*;
