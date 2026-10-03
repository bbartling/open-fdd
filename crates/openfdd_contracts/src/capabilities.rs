//! Versioned connector hello and capability contracts.
//!
//! These types deliberately describe observed runtime state separately from
//! authentication and from the read-only proxy contract.  A connector saying
//! that it supports an action never grants a caller permission to use it.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::service::{ConnectorServiceProfile, ServiceIdentity};

/// Stable schema identifier for connector hello/capability responses.
pub const CAPABILITIES_CONTRACT_V1: &str = "openfdd.connector.capabilities.v1";
pub const CAPABILITIES_AGGREGATE_CONTRACT_V1: &str = "openfdd.capabilities.aggregate.v1";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum ConnectorProtocol {
    Bacnet,
    Modbus,
    Haystack,
    Rest,
    Mqtt,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum CapabilityState {
    Disabled,
    NotConfigured,
    Checking,
    Ready,
    Degraded,
    Unreachable,
    AuthFailure,
    Incompatible,
    Stale,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum ConnectorAction {
    MetadataRead,
    PointRead,
    PriorityArrayRead,
    PriorityHistoryRead,
    PriorityHistoryTrigger,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum DeliveryStatus {
    Disabled,
    NotConfigured,
    Checking,
    Ready,
    Degraded,
    Unreachable,
    AuthFailure,
    Incompatible,
    Stale,
    Unknown,
}

impl From<CapabilityState> for DeliveryStatus {
    fn from(value: CapabilityState) -> Self {
        match value {
            CapabilityState::Disabled => Self::Disabled,
            CapabilityState::NotConfigured => Self::NotConfigured,
            CapabilityState::Checking => Self::Checking,
            CapabilityState::Ready => Self::Ready,
            CapabilityState::Degraded => Self::Degraded,
            CapabilityState::Unreachable => Self::Unreachable,
            CapabilityState::AuthFailure => Self::AuthFailure,
            CapabilityState::Incompatible => Self::Incompatible,
            CapabilityState::Stale => Self::Stale,
            CapabilityState::Unknown => Self::Unknown,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ServiceVersion {
    pub service: String,
    pub build: String,
    pub contract: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ConnectorCapability {
    pub protocol: ConnectorProtocol,
    pub compiled: bool,
    pub configured: bool,
    pub enabled: bool,
    pub readiness: CapabilityState,
    pub source_health: CapabilityState,
    pub mqtt_connection: DeliveryStatus,
    pub durable_delivery: DeliveryStatus,
    #[serde(default)]
    pub supported_actions: Vec<ConnectorAction>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct RecipeObservation {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub declared: Option<String>,
    /// Services selected by the deployment/configuration.  This is kept
    /// separate from `observed_services`: configuration alone is never
    /// evidence that a connector or broker is alive.
    #[serde(default)]
    pub configured_services: Vec<String>,
    /// Services for which this response has runtime evidence.  A service may
    /// be configured while this list is empty or incomplete.
    #[serde(default)]
    pub observed_services: Vec<String>,
    /// Required services outside the connector probe boundary, or otherwise
    /// not observed by this response. This prevents a connector projection
    /// from claiming that a complete compose recipe is healthy.
    #[serde(default)]
    pub unobserved_services: Vec<String>,
    /// `matched`, `declared_missing`, `observed_extra`, or `not_declared`.
    pub reconciliation: String,
}

impl RecipeObservation {
    /// Return the service set required by the documented compose recipes.
    /// These requirements are deliberately centralized in the wire contract
    /// so fieldbus and central cannot silently disagree about completeness.
    pub fn required_services(declared: &str) -> &'static [&'static str] {
        match declared {
            "csv" => &["central", "web"],
            "central" => &["central", "mqtt", "web"],
            // The edge compose recipe contains fieldbus only. Its broker is
            // an external dependency reported separately by delivery state.
            "edge" => &["fieldbus"],
            "standalone" => &["central", "fieldbus", "mqtt", "web"],
            _ => &[],
        }
    }

    pub fn missing_services(declared: Option<&str>, observed_services: &[String]) -> Vec<String> {
        let Some(declared) = declared else {
            return Vec::new();
        };
        Self::required_services(declared)
            .iter()
            .filter(|service| !observed_services.iter().any(|item| item == **service))
            .map(|service| (*service).to_string())
            .collect()
    }

    /// Reconcile a declared recipe against both its configured services and
    /// runtime evidence.  A configured service is never treated as observed.
    pub fn reconcile(
        declared: Option<&str>,
        configured_services: &[String],
        observed_services: &[String],
    ) -> &'static str {
        let Some(declared) = declared else {
            return "not_declared";
        };
        let required = Self::required_services(declared);
        if required.is_empty() {
            return "declared_missing";
        }
        if !required
            .iter()
            .all(|service| configured_services.iter().any(|item| item == service))
            || !required
                .iter()
                .all(|service| observed_services.iter().any(|item| item == service))
        {
            return "declared_missing";
        }
        if observed_services
            .iter()
            .any(|service| !required.contains(&service.as_str()))
        {
            return "observed_extra";
        }
        "matched"
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ConnectorHelloResponse {
    pub schema: String,
    pub version: ServiceVersion,
    #[serde(default)]
    pub compiled_protocols: Vec<ConnectorProtocol>,
    #[serde(default)]
    pub connectors: Vec<ConnectorCapability>,
    pub recipe: RecipeObservation,
    /// Legacy `openfdd-fieldbus` omits this field. Split connector processes
    /// populate it so Central can distinguish ownership without treating a
    /// configured protocol as live or ready.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub service_identity: Option<ServiceIdentity>,
    pub observed_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct UpstreamCapability {
    pub edge_id: String,
    /// Scheme and authority only. Paths, credentials, and query strings are
    /// intentionally never returned.
    pub address: String,
    pub state: CapabilityState,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hello: Option<ConnectorHelloResponse>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_success_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct CapabilitiesAggregateResponse {
    pub schema: String,
    pub version: ServiceVersion,
    pub central: ConnectorHelloResponse,
    #[serde(default)]
    pub upstreams: Vec<UpstreamCapability>,
    pub recipe: RecipeObservation,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub diagnostic: Option<String>,
    /// Time at which this aggregate was generated. Connector hello timestamps
    /// remain the evidence time for each probe and are not rewritten on cache
    /// hits.
    pub generated_at: DateTime<Utc>,
    pub observed_at: DateTime<Utc>,
}

impl ConnectorHelloResponse {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != CAPABILITIES_CONTRACT_V1 {
            return Err(format!("unsupported capability schema {}", self.schema));
        }
        if self.version.contract != CAPABILITIES_CONTRACT_V1 {
            return Err("capability contract version mismatch".into());
        }
        if self.version.service.trim().is_empty() || self.version.build.trim().is_empty() {
            return Err("service and build versions are required".into());
        }
        if self.version.service.len() > 128 || self.version.build.len() > 128 {
            return Err("service and build versions are too long".into());
        }
        if let Some(identity) = &self.service_identity {
            identity.validate()?;
            if self.version.service != identity.service
                || self.version.service != identity.version.service
                || self.version.build != identity.version.build
            {
                return Err("capability hello does not match service identity".into());
            }
            let expected_protocols = match identity.profile {
                ConnectorServiceProfile::BacnetModbus => {
                    &[ConnectorProtocol::Bacnet, ConnectorProtocol::Modbus][..]
                }
                ConnectorServiceProfile::Haystack => &[ConnectorProtocol::Haystack][..],
            };
            if self.compiled_protocols.len() != expected_protocols.len()
                || !expected_protocols
                    .iter()
                    .all(|protocol| self.compiled_protocols.contains(protocol))
                || self.connectors.len() != expected_protocols.len()
                || self.connectors.iter().any(|connector| {
                    !connector.compiled || !expected_protocols.contains(&connector.protocol)
                })
                || !expected_protocols.iter().all(|protocol| {
                    self.connectors
                        .iter()
                        .any(|connector| connector.protocol == *protocol)
                })
            {
                return Err("capability protocols do not match service identity profile".into());
            }
        }
        if !self
            .version
            .service
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-' | '+'))
            || !self
                .version
                .build
                .chars()
                .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-' | '+'))
        {
            return Err("service and build versions contain unsafe characters".into());
        }
        if self.connectors.iter().any(|connector| {
            connector
                .detail
                .as_deref()
                .is_some_and(|detail| detail.len() > 512)
        }) {
            return Err("connector detail is too long".into());
        }
        let valid_service =
            |service: &str| matches!(service, "central" | "fieldbus" | "mqtt" | "web");
        if self
            .recipe
            .declared
            .as_deref()
            .is_some_and(|declared| !matches!(declared, "edge" | "standalone" | "central" | "csv"))
            || self.recipe.configured_services.len() > 8
            || self.recipe.observed_services.len() > 8
            || self.recipe.unobserved_services.len() > 8
            || self
                .recipe
                .configured_services
                .iter()
                .chain(self.recipe.observed_services.iter())
                .chain(self.recipe.unobserved_services.iter())
                .any(|service| service.len() > 32 || !valid_service(service))
            || !matches!(
                self.recipe.reconciliation.as_str(),
                "matched" | "declared_missing" | "observed_extra" | "not_declared"
            )
        {
            return Err("recipe observation contains invalid public fields".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capability_contract_round_trips_and_keeps_explicit_states() {
        let response = ConnectorHelloResponse {
            schema: CAPABILITIES_CONTRACT_V1.into(),
            version: ServiceVersion {
                service: "fieldbus".into(),
                build: "3.5.58+abc".into(),
                contract: CAPABILITIES_CONTRACT_V1.into(),
            },
            compiled_protocols: vec![ConnectorProtocol::Bacnet],
            connectors: vec![ConnectorCapability {
                protocol: ConnectorProtocol::Bacnet,
                compiled: true,
                configured: false,
                enabled: false,
                readiness: CapabilityState::NotConfigured,
                source_health: CapabilityState::NotConfigured,
                mqtt_connection: DeliveryStatus::Disabled,
                durable_delivery: DeliveryStatus::Disabled,
                supported_actions: vec![ConnectorAction::MetadataRead],
                detail: None,
            }],
            recipe: RecipeObservation {
                declared: None,
                configured_services: vec!["fieldbus".into()],
                observed_services: vec!["fieldbus".into()],
                unobserved_services: vec![],
                reconciliation: "not_declared".into(),
            },
            service_identity: None,
            observed_at: Utc::now(),
        };
        response.validate().unwrap();
        let value = serde_json::to_value(&response).unwrap();
        assert_eq!(value["schema"], CAPABILITIES_CONTRACT_V1);
        assert_eq!(value["connectors"][0]["readiness"], "not_configured");
        let decoded: ConnectorHelloResponse = serde_json::from_value(value).unwrap();
        assert_eq!(
            decoded.connectors[0].readiness,
            CapabilityState::NotConfigured
        );
    }

    #[test]
    fn every_wire_state_is_explicit() {
        for state in [
            CapabilityState::Disabled,
            CapabilityState::NotConfigured,
            CapabilityState::Checking,
            CapabilityState::Ready,
            CapabilityState::Degraded,
            CapabilityState::Unreachable,
            CapabilityState::AuthFailure,
            CapabilityState::Incompatible,
            CapabilityState::Stale,
            CapabilityState::Unknown,
        ] {
            let encoded = serde_json::to_string(&state).unwrap();
            assert!(!encoded.is_empty());
        }
    }

    #[test]
    fn hello_propagates_split_profile_without_claiming_legacy_ownership() {
        let legacy = ConnectorHelloResponse {
            schema: CAPABILITIES_CONTRACT_V1.into(),
            version: ServiceVersion {
                service: "openfdd-fieldbus".into(),
                build: "test".into(),
                contract: CAPABILITIES_CONTRACT_V1.into(),
            },
            compiled_protocols: vec![ConnectorProtocol::Bacnet],
            connectors: vec![],
            recipe: RecipeObservation {
                declared: None,
                configured_services: vec!["fieldbus".into()],
                observed_services: vec!["fieldbus".into()],
                unobserved_services: vec![],
                reconciliation: "not_declared".into(),
            },
            service_identity: None,
            observed_at: Utc::now(),
        };
        legacy.validate().unwrap();
        assert!(serde_json::to_value(&legacy)
            .unwrap()
            .get("service_identity")
            .is_none());

        let mut split = legacy;
        split.version.service = "openfdd-bacnet-modbus".into();
        split.version.build = "3.5.60+test".into();
        split.compiled_protocols = vec![ConnectorProtocol::Bacnet, ConnectorProtocol::Modbus];
        split.connectors = vec![
            ConnectorCapability {
                protocol: ConnectorProtocol::Bacnet,
                compiled: true,
                configured: false,
                enabled: false,
                readiness: CapabilityState::NotConfigured,
                source_health: CapabilityState::NotConfigured,
                mqtt_connection: DeliveryStatus::Disabled,
                durable_delivery: DeliveryStatus::Disabled,
                supported_actions: vec![],
                detail: None,
            },
            ConnectorCapability {
                protocol: ConnectorProtocol::Modbus,
                compiled: true,
                configured: false,
                enabled: false,
                readiness: CapabilityState::NotConfigured,
                source_health: CapabilityState::NotConfigured,
                mqtt_connection: DeliveryStatus::Disabled,
                durable_delivery: DeliveryStatus::Disabled,
                supported_actions: vec![],
                detail: None,
            },
        ];
        split.service_identity = Some(ServiceIdentity::new(
            crate::service::ConnectorServiceProfile::BacnetModbus,
            "3.5.60+test",
            crate::service::RecipeKind::EdgeBacnetModbus,
        ));
        split.validate().unwrap();
        assert_eq!(
            serde_json::to_value(split).unwrap()["service_identity"]["profile"],
            "bacnet_modbus"
        );
    }

    fn valid_split_hello() -> ConnectorHelloResponse {
        let identity = ServiceIdentity::new(
            ConnectorServiceProfile::Haystack,
            "3.5.60+test",
            crate::service::RecipeKind::EdgeHaystack,
        );
        ConnectorHelloResponse {
            schema: CAPABILITIES_CONTRACT_V1.into(),
            version: ServiceVersion {
                contract: CAPABILITIES_CONTRACT_V1.into(),
                ..identity.version.clone()
            },
            compiled_protocols: vec![ConnectorProtocol::Haystack],
            connectors: vec![ConnectorCapability {
                protocol: ConnectorProtocol::Haystack,
                compiled: true,
                configured: false,
                enabled: false,
                readiness: CapabilityState::NotConfigured,
                source_health: CapabilityState::NotConfigured,
                mqtt_connection: DeliveryStatus::Disabled,
                durable_delivery: DeliveryStatus::Disabled,
                supported_actions: vec![],
                detail: None,
            }],
            recipe: RecipeObservation {
                declared: None,
                configured_services: vec!["fieldbus".into()],
                observed_services: vec!["fieldbus".into()],
                unobserved_services: vec![],
                reconciliation: "not_declared".into(),
            },
            service_identity: Some(identity),
            observed_at: Utc::now(),
        }
    }

    #[test]
    fn split_identity_must_match_hello_version_and_profile_protocols() {
        let hello = valid_split_hello();
        hello.validate().unwrap();

        let mut hello = valid_split_hello();
        hello.version.build = "different-build".into();
        assert_eq!(
            hello.validate().unwrap_err(),
            "capability hello does not match service identity"
        );

        let mut hello = valid_split_hello();
        hello.version.service = "openfdd-haystack-shadow".into();
        assert_eq!(
            hello.validate().unwrap_err(),
            "capability hello does not match service identity"
        );

        let mut hello = valid_split_hello();
        hello.compiled_protocols = vec![ConnectorProtocol::Bacnet];
        assert_eq!(
            hello.validate().unwrap_err(),
            "capability protocols do not match service identity profile"
        );

        let mut hello = valid_split_hello();
        hello.connectors[0].protocol = ConnectorProtocol::Bacnet;
        assert_eq!(
            hello.validate().unwrap_err(),
            "capability protocols do not match service identity profile"
        );
    }
}
