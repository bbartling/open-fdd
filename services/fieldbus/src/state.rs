//! Shared application state.

use std::sync::Arc;

use crate::config::Settings;
use crate::services::{
    bacnet_client::BacnetClientService, bacnet_server::BacnetServerManager,
    haystack::HaystackService, poll::PollEngine, weather::WeatherService,
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
}
