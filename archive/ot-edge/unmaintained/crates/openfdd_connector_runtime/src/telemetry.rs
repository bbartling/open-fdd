//! Shared telemetry sink configuration and bounded batches.
//!
//! Connector processes may buffer and forward observations, but they never
//! write Parquet or create DataFusion sessions.  The authenticated local
//! ingest endpoint or the optional MQTT transport is the handoff to Central.

use openfdd_contracts::TelemetryEnvelope;
use serde::{Deserialize, Serialize};
use url::Url;

pub const TELEMETRY_SINK_CONTRACT_V1: &str = "openfdd.connector.telemetry-sink.v1";
pub const MAX_TELEMETRY_BATCH_BYTES: usize = 1_048_576;
pub const MAX_TELEMETRY_BATCH_POINTS: usize = 5_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TelemetrySinkMode {
    Disabled,
    Mqtts,
    LocalIngest,
    Dual,
}

impl TelemetrySinkMode {
    pub fn parse(raw: &str) -> Result<Self, String> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "disabled" | "off" | "none" => Ok(Self::Disabled),
            "mqtts" | "mqtt" => Ok(Self::Mqtts),
            "local_ingest" | "local_fieldbus" | "http" => Ok(Self::LocalIngest),
            "dual" => Ok(Self::Dual),
            other => Err(format!(
                "invalid OPENFDD_TELEMETRY_SINK '{other}' (expected disabled | mqtts | local_ingest | dual)"
            )),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TelemetrySinkConfig {
    pub schema: String,
    pub mode: TelemetrySinkMode,
    /// Authority-only public description of the local ingest endpoint.  The
    /// bearer token is read from an environment variable by the future sink
    /// implementation and is never represented here.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub local_ingest_authority: Option<String>,
    pub site_id: String,
    pub edge_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tenant_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub building_id: Option<String>,
    pub max_batch_points: usize,
    pub max_batch_bytes: usize,
}

impl TelemetrySinkConfig {
    pub fn from_env() -> Result<Self, String> {
        let mode = TelemetrySinkMode::parse(
            &std::env::var("OPENFDD_TELEMETRY_SINK").unwrap_or_else(|_| "disabled".into()),
        )?;
        let local_ingest_authority = std::env::var("OPENFDD_LOCAL_INGEST_URL")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .map(|raw| public_authority(&raw))
            .transpose()?;
        let config = Self {
            schema: TELEMETRY_SINK_CONTRACT_V1.into(),
            mode,
            local_ingest_authority,
            site_id: required_env("OPENFDD_SITE_ID", "site_id")?,
            edge_id: required_env("OPENFDD_EDGE_ID", "edge_id")?,
            tenant_id: optional_env("OPENFDD_TENANT_ID"),
            building_id: optional_env("OPENFDD_BUILDING_ID"),
            max_batch_points: MAX_TELEMETRY_BATCH_POINTS,
            max_batch_bytes: MAX_TELEMETRY_BATCH_BYTES,
        };
        config.validate()?;
        Ok(config)
    }

    pub fn disabled_for_tests() -> Self {
        Self {
            schema: TELEMETRY_SINK_CONTRACT_V1.into(),
            mode: TelemetrySinkMode::Disabled,
            local_ingest_authority: None,
            site_id: "test-site".into(),
            edge_id: "test-edge".into(),
            tenant_id: None,
            building_id: None,
            max_batch_points: MAX_TELEMETRY_BATCH_POINTS,
            max_batch_bytes: MAX_TELEMETRY_BATCH_BYTES,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema != TELEMETRY_SINK_CONTRACT_V1 {
            return Err("unsupported telemetry sink contract".into());
        }
        for (name, value) in [
            ("site_id", self.site_id.as_str()),
            ("edge_id", self.edge_id.as_str()),
        ] {
            if value.trim().is_empty()
                || value.len() > 256
                || value.contains('/')
                || value.contains('\\')
            {
                return Err(format!("invalid telemetry {name}"));
            }
        }
        if let Some(authority) = self.local_ingest_authority.as_deref() {
            public_authority(authority)
                .map_err(|error| format!("invalid local ingest authority: {error}"))?;
        }
        if self.max_batch_points == 0 || self.max_batch_points > MAX_TELEMETRY_BATCH_POINTS {
            return Err("telemetry max_batch_points exceeds the process bound".into());
        }
        if self.max_batch_bytes == 0 || self.max_batch_bytes > MAX_TELEMETRY_BATCH_BYTES {
            return Err("telemetry max_batch_bytes exceeds the process bound".into());
        }
        if matches!(
            self.mode,
            TelemetrySinkMode::LocalIngest | TelemetrySinkMode::Dual
        ) && self.local_ingest_authority.is_none()
        {
            return Err("local telemetry mode requires OPENFDD_LOCAL_INGEST_URL".into());
        }
        Ok(())
    }

    pub fn status(&self) -> TelemetrySinkStatus {
        TelemetrySinkStatus {
            schema: self.schema.clone(),
            mode: self.mode,
            local_ingest_authority: self.local_ingest_authority.clone(),
            bounded: self.validate().is_ok(),
            durable: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TelemetrySinkStatus {
    pub schema: String,
    pub mode: TelemetrySinkMode,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub local_ingest_authority: Option<String>,
    pub bounded: bool,
    /// This remains false until a sink receives a Central receipt.  A queued
    /// HTTP request or broker PUBACK is not a historian durability claim.
    pub durable: bool,
}

#[derive(Debug, Clone)]
pub struct TelemetryBatch {
    envelope: TelemetryEnvelope,
    max_points: usize,
    max_bytes: usize,
    site_id: String,
    edge_id: String,
}

impl TelemetryBatch {
    pub fn new(envelope: TelemetryEnvelope, config: &TelemetrySinkConfig) -> Result<Self, String> {
        config.validate()?;
        if envelope.site_id != config.site_id || envelope.edge_id != config.edge_id {
            return Err("telemetry envelope identity does not match sink config".into());
        }
        let batch = Self {
            envelope,
            max_points: config.max_batch_points,
            max_bytes: config.max_batch_bytes,
            site_id: config.site_id.clone(),
            edge_id: config.edge_id.clone(),
        };
        batch.validate()?;
        Ok(batch)
    }

    pub fn envelope(&self) -> &TelemetryEnvelope {
        &self.envelope
    }

    pub fn envelope_mut(&mut self) -> &mut TelemetryEnvelope {
        &mut self.envelope
    }

    pub fn validate(&self) -> Result<(), String> {
        self.envelope.validate()?;
        if self.envelope.site_id != self.site_id || self.envelope.edge_id != self.edge_id {
            return Err("telemetry envelope identity does not match sink config".into());
        }
        if self.envelope.points.len() > MAX_TELEMETRY_BATCH_POINTS
            || self.envelope.points.len() > self.max_points
        {
            return Err("telemetry batch exceeds point bound".into());
        }
        let bytes = serde_json::to_vec(&self.envelope)
            .map_err(|error| format!("serialize telemetry batch: {error}"))?;
        if bytes.len() > MAX_TELEMETRY_BATCH_BYTES || bytes.len() > self.max_bytes {
            return Err("telemetry batch exceeds byte bound".into());
        }
        Ok(())
    }
}

fn required_env(name: &str, label: &str) -> Result<String, String> {
    optional_env(name)
        .ok_or_else(|| format!("{name} is required when building telemetry config ({label})"))
}

fn optional_env(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn public_authority(raw: &str) -> Result<String, String> {
    let url = Url::parse(raw).map_err(|error| format!("invalid local ingest URL: {error}"))?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
        return Err("local ingest URL must have an http(s) scheme and host".into());
    }
    if url.path() != "/" && !url.path().is_empty() {
        return Err(
            "local ingest URL must expose authority only; route paths are fixed by the sink".into(),
        );
    }
    if url.query().is_some()
        || url.fragment().is_some()
        || url.username() != ""
        || url.password().is_some()
    {
        return Err("local ingest URL must not contain credentials, query, or fragment".into());
    }
    let host = url
        .host_str()
        .ok_or_else(|| "local ingest URL host required".to_string())?;
    Ok(match url.port() {
        Some(port) => format!("{}://{}:{}", url.scheme(), host, port),
        None => format!("{}://{}", url.scheme(), host),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use openfdd_contracts::{Protocol, Quality, TelemetryPoint, ValueKind};
    use serde_json::json;

    #[test]
    fn local_endpoint_is_redacted_to_authority() {
        assert!(public_authority("https://central.internal:8443/ignored").is_err());
        assert_eq!(
            public_authority("https://central.internal:8443").unwrap(),
            "https://central.internal:8443"
        );
    }

    #[test]
    fn batch_is_bounded_and_uses_existing_envelope_contract() {
        let cfg = TelemetrySinkConfig::disabled_for_tests();
        let envelope = openfdd_contracts::TelemetryEnvelope::new(
            &cfg.site_id,
            &cfg.edge_id,
            Protocol::Bacnet,
            1,
            vec![TelemetryPoint {
                id: "point:1".into(),
                display_name: None,
                kind: Some(ValueKind::Number),
                value: json!(72.0),
                unit: Some("degF".into()),
                quality: Quality::Good,
                observed_at: None,
                tags: Default::default(),
            }],
        );
        let batch = TelemetryBatch::new(envelope, &cfg).unwrap();
        batch.validate().unwrap();
    }

    #[test]
    fn invalid_config_is_rejected_and_never_reports_bounded() {
        let mut cfg = TelemetrySinkConfig::disabled_for_tests();
        cfg.schema = "wrong".into();
        assert!(cfg.validate().is_err());
        assert!(!cfg.status().bounded);
        assert!(TelemetryBatch::new(
            openfdd_contracts::TelemetryEnvelope::new(
                &cfg.site_id,
                &cfg.edge_id,
                Protocol::Bacnet,
                1,
                vec![TelemetryPoint {
                    id: "point:1".into(),
                    display_name: None,
                    kind: Some(ValueKind::Number),
                    value: json!(72.0),
                    unit: Some("degF".into()),
                    quality: Quality::Good,
                    observed_at: None,
                    tags: Default::default(),
                }],
            ),
            &cfg,
        )
        .is_err());

        let mut cfg = TelemetrySinkConfig::disabled_for_tests();
        cfg.max_batch_points = MAX_TELEMETRY_BATCH_POINTS + 1;
        assert!(cfg.validate().is_err());
        assert!(!cfg.status().bounded);
    }

    #[test]
    fn batch_requires_configured_identity_and_rechecks_it() {
        let cfg = TelemetrySinkConfig::disabled_for_tests();
        let foreign = openfdd_contracts::TelemetryEnvelope::new(
            "other-site",
            &cfg.edge_id,
            Protocol::Bacnet,
            1,
            vec![TelemetryPoint {
                id: "point:1".into(),
                display_name: None,
                kind: Some(ValueKind::Number),
                value: json!(72.0),
                unit: Some("degF".into()),
                quality: Quality::Good,
                observed_at: None,
                tags: Default::default(),
            }],
        );
        assert!(TelemetryBatch::new(foreign, &cfg).is_err());

        let envelope = openfdd_contracts::TelemetryEnvelope::new(
            &cfg.site_id,
            &cfg.edge_id,
            Protocol::Bacnet,
            1,
            vec![TelemetryPoint {
                id: "point:1".into(),
                display_name: None,
                kind: Some(ValueKind::Number),
                value: json!(72.0),
                unit: Some("degF".into()),
                quality: Quality::Good,
                observed_at: None,
                tags: Default::default(),
            }],
        );
        let mut batch = TelemetryBatch::new(envelope, &cfg).unwrap();
        batch.envelope_mut().edge_id = "other-edge".into();
        assert!(batch.validate().is_err());
    }
}
