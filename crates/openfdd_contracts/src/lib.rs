//! Shared Open-FDD MQTT / Haystack-style contracts.

pub mod command;
pub mod envelope;
pub mod topics;

pub use command::{CommandAck, CommandEnvelope, CommandStatus};
pub use envelope::{
    Protocol, Quality, SchemaVersion, TelemetryEnvelope, TelemetryPoint, ValueKind,
};
pub use topics::{TopicBuilder, TopicKind};

/// Current wire schema string carried in every envelope.
pub const SCHEMA_V1: &str = "openfdd.mqtt.telemetry.v1";
pub const COMMAND_SCHEMA_V1: &str = "openfdd.mqtt.command.v1";
pub const ACK_SCHEMA_V1: &str = "openfdd.mqtt.ack.v1";
pub const STATUS_SCHEMA_V1: &str = "openfdd.mqtt.status.v1";
