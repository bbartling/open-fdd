//! Shared application state.

use std::sync::Arc;

use crate::config::Settings;
use crate::services::{
    bacnet_client::BacnetClientService, bacnet_server::BacnetServerManager,
    haystack::HaystackService, mqtt_publish_ledger::MqttPublishLedger, poll::PollEngine,
    priority_scan::PriorityScanService, rest::RestClientService,
    telemetry_control::TelemetryControl, weather::WeatherService,
};
use openfdd_contracts::ServiceIdentity;

#[derive(Clone)]
pub struct AppState {
    pub settings: Arc<Settings>,
    pub api_key: Option<String>,
    pub bacnet_server: Arc<BacnetServerManager>,
    pub bacnet_client: Arc<BacnetClientService>,
    pub poll_engine: Arc<PollEngine>,
    pub weather: Arc<WeatherService>,
    /// `None` for the BACnet/Modbus split process. Keeping the optional field
    /// on the compatibility state lets the legacy router stay intact without
    /// constructing Haystack credentials in the BACnet process.
    pub haystack: Option<Arc<HaystackService>>,
    pub rest: Arc<RestClientService>,
    pub telemetry: Arc<TelemetryControl>,
    /// Durable, opt-in, read-only BACnet priority-array observation.
    pub priority_scan: Arc<PriorityScanService>,
    /// Diagnostics: QoS 1 publish attempts / acks. Does not filter telemetry.
    pub publish_ledger: Arc<MqttPublishLedger>,
    /// Present only for a split process. Legacy `openfdd-fieldbus` remains
    /// deliberately multi-protocol and omits the split identity.
    pub service_identity: Option<ServiceIdentity>,
}
