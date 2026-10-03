//! Shared Open-FDD MQTT / Haystack-style contracts.

pub mod capabilities;
pub mod command;
pub mod envelope;
pub mod proxy;
pub mod topics;

pub use capabilities::{
    CapabilitiesAggregateResponse, CapabilityState, ConnectorAction, ConnectorCapability,
    ConnectorHelloResponse, ConnectorProtocol, DeliveryStatus, RecipeObservation, ServiceVersion,
    UpstreamCapability, CAPABILITIES_AGGREGATE_CONTRACT_V1, CAPABILITIES_CONTRACT_V1,
};
pub use command::{CommandAck, CommandEnvelope, CommandStatus};
pub use envelope::{
    Protocol, Quality, SchemaVersion, TelemetryEnvelope, TelemetryPoint, ValueKind,
};
pub use proxy::{
    ConnectorReadRequest, ConnectorReadResponse, ConnectorReadResult, ConnectorScope, ReadError,
    ReadPointResult, ReadPriorityArrayResult, ReadPrioritySlot, ReadTarget, ReadValueState,
    READ_PROXY_CONTRACT_V1,
};
pub use topics::{parse_topic, payload_matches_topic, TopicBuilder, TopicIdentity, TopicKind};

/// Current wire schema string carried in every envelope.
pub const SCHEMA_V1: &str = "openfdd.mqtt.telemetry.v1";
pub const COMMAND_SCHEMA_V1: &str = "openfdd.mqtt.command.v1";
pub const ACK_SCHEMA_V1: &str = "openfdd.mqtt.ack.v1";
pub const STATUS_SCHEMA_V1: &str = "openfdd.mqtt.status.v1";
