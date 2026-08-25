//! Per-edge telemetry suspend/resume: stop BACnet poll + weather + REST poll + MQTT publish;
//! keep the hosted BACnet server running. Desired state is persisted across restarts.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tracing::{info, warn};

use crate::services::poll::PollEngine;
use crate::services::rest::RestClientService;
use crate::services::weather::WeatherService;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TelemetryAction {
    Suspend,
    Resume,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct PersistedState {
    suspended: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    approved_by: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    updated_at: Option<String>,
}

pub struct TelemetryControl {
    suspended: AtomicBool,
    path: PathBuf,
    poll: Arc<PollEngine>,
    weather: Arc<WeatherService>,
    rest: Arc<RestClientService>,
    last_approved_by: tokio::sync::Mutex<Option<String>>,
    last_updated_at: tokio::sync::Mutex<Option<String>>,
}

impl TelemetryControl {
    pub fn new(
        poll: Arc<PollEngine>,
        weather: Arc<WeatherService>,
        rest: Arc<RestClientService>,
    ) -> Self {
        let edge_id = std::env::var("OPENFDD_EDGE_ID").unwrap_or_else(|_| "fieldbus-1".into());
        let path = std::env::var("OPENFDD_TELEMETRY_STATE_PATH")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from(format!("/tmp/openfdd-telemetry-{edge_id}.json")));
        Self {
            suspended: AtomicBool::new(false),
            path,
            poll,
            weather,
            rest,
            last_approved_by: tokio::sync::Mutex::new(None),
            last_updated_at: tokio::sync::Mutex::new(None),
        }
    }

    pub fn is_suspended(&self) -> bool {
        self.suspended.load(Ordering::SeqCst)
    }

    /// Load persisted desire and apply before MQTT bridge / long-lived loops rely on the gate.
    pub async fn apply_persisted_on_boot(self: &Arc<Self>) {
        let Some(state) = self.load() else {
            return;
        };
        *self.last_approved_by.lock().await = state.approved_by.clone();
        *self.last_updated_at.lock().await = state.updated_at.clone();
        if state.suspended {
            info!(path = %self.path.display(), "applying persisted telemetry suspend on boot");
            let by = state.approved_by.as_deref().unwrap_or("persisted");
            if let Err(err) = self.suspend_inner(by, false).await {
                warn!(%err, "failed to apply persisted telemetry suspend");
            }
        }
    }

    pub async fn suspend(&self, approved_by: &str) -> Result<Value, String> {
        self.suspend_inner(approved_by, true).await
    }

    pub async fn resume(&self, approved_by: &str) -> Result<Value, String> {
        if !self.is_suspended() {
            return Ok(self.status().await);
        }
        self.poll.start().await;
        if let Err(err) = self.weather.start().await {
            warn!(%err, "weather resume failed");
        }
        self.rest.start().await;
        self.suspended.store(false, Ordering::SeqCst);
        self.persist(false, approved_by).await?;
        info!(approved_by = %approved_by, "telemetry resumed (poll + weather + mqtt publish)");
        Ok(self.status().await)
    }

    pub async fn apply_action(
        &self,
        action: TelemetryAction,
        approved_by: &str,
    ) -> Result<Value, String> {
        match action {
            TelemetryAction::Suspend => self.suspend(approved_by).await,
            TelemetryAction::Resume => self.resume(approved_by).await,
        }
    }

    pub async fn status(&self) -> Value {
        let poll = self.poll.status().await;
        json!({
            "ok": true,
            "suspended": self.is_suspended(),
            "poll_running": poll["running"].as_bool().unwrap_or(false),
            "mqtt_publish_gated": self.is_suspended(),
            "weather_stopped": self.is_suspended(),
            "bacnet_server_kept": true,
            "approved_by": self.last_approved_by.lock().await.clone(),
            "updated_at": self.last_updated_at.lock().await.clone(),
            "state_path": self.path.display().to_string(),
        })
    }

    async fn suspend_inner(&self, approved_by: &str, persist: bool) -> Result<Value, String> {
        self.poll.stop().await;
        self.weather.stop().await;
        self.rest.stop().await;
        self.suspended.store(true, Ordering::SeqCst);
        if persist {
            self.persist(true, approved_by).await?;
        } else {
            *self.last_approved_by.lock().await = Some(approved_by.to_string());
        }
        info!(approved_by = %approved_by, "telemetry suspended (poll + weather + mqtt publish gated; bacnet server kept)");
        Ok(self.status().await)
    }

    async fn persist(&self, suspended: bool, approved_by: &str) -> Result<(), String> {
        let updated_at = Utc::now().to_rfc3339();
        *self.last_approved_by.lock().await = Some(approved_by.to_string());
        *self.last_updated_at.lock().await = Some(updated_at.clone());
        let state = PersistedState {
            suspended,
            approved_by: Some(approved_by.to_string()),
            updated_at: Some(updated_at),
        };
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let body = serde_json::to_vec_pretty(&state).map_err(|e| e.to_string())?;
        std::fs::write(&self.path, body).map_err(|e| e.to_string())?;
        Ok(())
    }

    fn load(&self) -> Option<PersistedState> {
        let bytes = std::fs::read(&self.path).ok()?;
        serde_json::from_slice(&bytes).ok()
    }
}

/// Parse MQTT / REST command payload for edge telemetry control.
pub fn parse_telemetry_command(target_id: &str, value: &Value) -> Result<TelemetryAction, String> {
    if target_id != "edge:telemetry" && !target_id.starts_with("edge:telemetry:") {
        return Err(format!(
            "telemetry target_id must be edge:telemetry (got {target_id})"
        ));
    }
    if let Some(suffix) = target_id.strip_prefix("edge:telemetry:") {
        return match suffix {
            "suspend" => Ok(TelemetryAction::Suspend),
            "resume" => Ok(TelemetryAction::Resume),
            other => Err(format!("unknown telemetry action in target_id: {other}")),
        };
    }
    let action = value
        .get("action")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "value.action required (suspend|resume)".to_string())?;
    match action {
        "suspend" => Ok(TelemetryAction::Suspend),
        "resume" => Ok(TelemetryAction::Resume),
        other => Err(format!("unknown telemetry action: {other}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_action_from_value() {
        let v = json!({"action": "suspend"});
        assert_eq!(
            parse_telemetry_command("edge:telemetry", &v).unwrap(),
            TelemetryAction::Suspend
        );
    }

    #[test]
    fn parse_action_from_target_suffix() {
        assert_eq!(
            parse_telemetry_command("edge:telemetry:resume", &json!({})).unwrap(),
            TelemetryAction::Resume
        );
    }
}
