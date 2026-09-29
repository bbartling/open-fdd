//! Shared application state.

use std::sync::Arc;

use crate::config::Settings;
use crate::services::{
    bacnet_client::BacnetClientService, bacnet_server::BacnetServerManager,
    haystack::HaystackService, mqtt_publish_ledger::MqttPublishLedger, poll::PollEngine,
    rest::RestClientService, telemetry_control::TelemetryControl, weather::WeatherService,
};

#[derive(Clone)]
pub struct AppState {
    pub settings: Arc<Settings>,
    pub api_key: Option<String>,
    pub bacnet_server: Arc<BacnetServerManager>,
    pub bacnet_client: Arc<BacnetClientService>,
    pub poll_engine: Arc<PollEngine>,
    pub weather: Arc<WeatherService>,
    pub haystack: Arc<HaystackService>,
    pub rest: Arc<RestClientService>,
    pub telemetry: Arc<TelemetryControl>,
    /// Diagnostics: QoS 1 publish attempts / acks. Does not filter telemetry.
    pub publish_ledger: Arc<MqttPublishLedger>,
}
