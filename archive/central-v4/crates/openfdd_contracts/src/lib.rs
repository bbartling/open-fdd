//! Shared Open-FDD MQTT / Haystack-style contracts.

pub mod capabilities;
pub mod command;
pub mod envelope;
pub mod haystack;
pub mod ingest;
pub mod inventory;
pub mod priority_scan;
pub mod proxy;
pub mod service;
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
pub use haystack::{
    HaystackAboutRequest, HaystackAboutResponse, HaystackCatalogRecord, HaystackCatalogRequest,
    HaystackCatalogResponse, HaystackCurrentReadRequest, HaystackCurrentReadResponse,
    HaystackHistoryReadRequest, HaystackHistoryReadResponse, HaystackHistorySeries,
    HaystackNavRequest, HaystackNavResponse, HaystackOperation, HaystackRecordKind, HaystackValue,
    HAYSTACK_CATALOG_CONTRACT_V1, HAYSTACK_MAX_BODY_BYTES, HAYSTACK_MAX_CURSOR_LENGTH,
    HAYSTACK_MAX_HISTORY_POINTS, HAYSTACK_MAX_HISTORY_SAMPLES, HAYSTACK_MAX_PAGE_SIZE,
    HAYSTACK_MAX_RANGE_HOURS, HAYSTACK_READ_CONTRACT_V1,
};
pub use ingest::{LocalIngestReceipt, LocalIngestStatus, LOCAL_INGEST_RECEIPT_CONTRACT_V1};
pub use inventory::{
    sanitize_inventory_label, ConnectorInventoryRequest, ConnectorInventoryResponse,
    InventoryAvailability, InventoryCommandability, InventoryPointReference, InventoryProvenance,
    InventoryRecord, CONNECTOR_INVENTORY_CONTRACT_V1, INVENTORY_MAX_CURSOR_LENGTH,
    INVENTORY_MAX_PAGE_SIZE,
};
pub use priority_scan::{
    PriorityHistoryRecord, PriorityHistoryRequest, PriorityHistoryResponse,
    PriorityHistoryTriggerRequest, PriorityHistoryTriggerResponse, PriorityScanConfig,
    PriorityScanStatus, PriorityScanTarget, BACNET_MAX_INSTANCE, PRIORITY_SCAN_CONTRACT_V1,
    PRIORITY_SCAN_DEFAULT_INTERVAL_SECS, PRIORITY_SCAN_DEFAULT_MAX_POINTS_PER_DEVICE,
    PRIORITY_SCAN_MAX_CURSOR_OFFSET, PRIORITY_SCAN_MAX_INTERVAL_SECS, PRIORITY_SCAN_MAX_PAGE_SIZE,
    PRIORITY_SCAN_MAX_POINTS_PER_DEVICE, PRIORITY_SCAN_MIN_INTERVAL_SECS,
    PRIORITY_SCAN_TRIGGER_CONTRACT_V1,
};
pub use proxy::{
    ConnectorReadRequest, ConnectorReadResponse, ConnectorReadResult, ConnectorScope, ReadError,
    ReadPointResult, ReadPriorityArrayResult, ReadPrioritySlot, ReadTarget, ReadValueState,
    READ_PROXY_CONTRACT_V1,
};
pub use service::{
    ConnectorServiceProfile, RecipeKind, ServiceIdentity, SERVICE_IDENTITY_CONTRACT_V1,
};
pub use topics::{parse_topic, payload_matches_topic, TopicBuilder, TopicIdentity, TopicKind};

/// Current wire schema string carried in every envelope.
pub const SCHEMA_V1: &str = "openfdd.mqtt.telemetry.v1";
pub const COMMAND_SCHEMA_V1: &str = "openfdd.mqtt.command.v1";
pub const ACK_SCHEMA_V1: &str = "openfdd.mqtt.ack.v1";
pub const STATUS_SCHEMA_V1: &str = "openfdd.mqtt.status.v1";
