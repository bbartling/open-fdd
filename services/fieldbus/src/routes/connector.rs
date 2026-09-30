//! Versioned fieldbus hello and explicitly requested read-only proxy.
//!
//! Building a hello response only inspects configuration and in-memory
//! delivery counters.  It never starts discovery, reads a point, or writes an
//! OT value.  The proxy is a separate authenticated operation and only accepts
//! BACnet targets present in the configured field-device inventory.

use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use chrono::Utc;
use openfdd_contracts::{
    CapabilityState, ConnectorAction, ConnectorCapability, ConnectorHelloResponse,
    ConnectorProtocol, ConnectorReadRequest, ConnectorReadResponse, DeliveryStatus,
    RecipeObservation, ServiceVersion, CAPABILITIES_CONTRACT_V1,
};
use serde_json::Value;

use crate::config::{git_sha, load_rest_devices, IngestMode};
use crate::error::{ApiError, ApiResult};
use crate::mqtt_bridge::mqtt_enabled;
use crate::state::AppState;

const SERVICE_NAME: &str = "openfdd-fieldbus";

fn build_version() -> String {
    let base = env!("CARGO_PKG_VERSION");
    let sha: String = git_sha()
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .take(12)
        .collect();
    if sha.is_empty() || sha == "unknown" {
        base.to_string()
    } else {
        format!("{base}+{sha}")
    }
}

fn declared_recipe() -> Option<String> {
    ["OPENFDD_BUILD_RECIPE", "OPENFDD_RECIPE"]
        .into_iter()
        .find_map(|name| {
            std::env::var(name)
                .ok()
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty())
        })
}

fn recipe_observation(configured_protocols: &[ConnectorProtocol]) -> RecipeObservation {
    let declared = declared_recipe();
    let mut observed_services = vec!["fieldbus".to_string()];
    if configured_protocols
        .iter()
        .any(|protocol| matches!(protocol, ConnectorProtocol::Mqtt))
    {
        observed_services.push("mqtt".into());
    }
    observed_services.sort();
    let reconciliation = match declared.as_deref() {
        None => "not_declared",
        Some("edge") | Some("standalone") if observed_services.contains(&"fieldbus".into()) => {
            "matched"
        }
        Some("central") | Some("csv") => "declared_missing",
        Some(_) => "observed_extra",
    };
    RecipeObservation {
        declared,
        observed_services,
        reconciliation: reconciliation.into(),
    }
}

fn source_state(configured: bool, enabled: bool) -> CapabilityState {
    match (configured, enabled) {
        (false, _) => CapabilityState::NotConfigured,
        (true, false) => CapabilityState::Disabled,
        (true, true) => CapabilityState::Ready,
    }
}

fn delivery_states(state: &AppState) -> (DeliveryStatus, DeliveryStatus) {
    let mode = IngestMode::from_env().unwrap_or(IngestMode::Mqtts);
    let ledger = state.publish_ledger.snapshot();
    let attempts = ledger
        .get("publish_attempts")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let acks = ledger
        .get("publish_acks")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let mqtt = if !mode.uses_mqtt() || !mqtt_enabled() {
        DeliveryStatus::Disabled
    } else if std::env::var("OPENFDD_MQTT_HOST")
        .ok()
        .filter(|host| !host.trim().is_empty())
        .is_none()
    {
        DeliveryStatus::NotConfigured
    } else if acks > 0 {
        DeliveryStatus::Ready
    } else if attempts > 0 {
        DeliveryStatus::Unreachable
    } else {
        DeliveryStatus::Stale
    };
    let durable = if mode.uses_local() {
        DeliveryStatus::Ready
    } else if mode.uses_mqtt() && mqtt_enabled() {
        if acks > 0 {
            DeliveryStatus::Ready
        } else {
            DeliveryStatus::Stale
        }
    } else {
        DeliveryStatus::Disabled
    };
    (mqtt, durable)
}

fn capability(
    protocol: ConnectorProtocol,
    configured: bool,
    enabled: bool,
    actions: Vec<ConnectorAction>,
    mqtt: DeliveryStatus,
    durable: DeliveryStatus,
    detail: Option<String>,
) -> ConnectorCapability {
    let readiness = source_state(configured, enabled);
    let source_health = match readiness {
        CapabilityState::Ready => CapabilityState::Stale,
        other => other,
    };
    ConnectorCapability {
        protocol,
        compiled: true,
        configured,
        enabled,
        readiness,
        source_health,
        mqtt_connection: mqtt,
        durable_delivery: durable,
        supported_actions: actions,
        detail,
    }
}

pub fn hello_response(state: &AppState) -> ConnectorHelloResponse {
    let (mqtt, durable) = delivery_states(state);
    let bacnet_devices = state.bacnet_client.configured_device_count();
    let bacnet_enabled =
        state.bacnet_client.enabled_device_count() > 0 && state.settings.poll.enabled;
    let bacnet_detail = if bacnet_devices == 0 {
        Some("field-device inventory is empty or unavailable".into())
    } else {
        Some(format!(
            "{} enabled configured device(s), {} configured point(s)",
            state.bacnet_client.enabled_device_count(),
            state.bacnet_client.configured_point_count()
        ))
    };
    let rest_devices = load_rest_devices(None, &state.settings.rest).unwrap_or_default();
    let rest_configured = rest_devices.iter().any(|device| device.enabled);
    let haystack_configured = std::env::var("OPENFDD_HAYSTACK_ENABLED")
        .ok()
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
        && std::env::var("OPENFDD_HAYSTACK_URL")
            .ok()
            .is_some_and(|url| !url.trim().is_empty());
    let modbus_configured = std::env::var("OPENFDD_MODBUS_ENABLED")
        .ok()
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false);
    let mqtt_configured = mqtt_enabled()
        && std::env::var("OPENFDD_MQTT_HOST")
            .ok()
            .is_some_and(|host| !host.trim().is_empty());

    let connectors = vec![
        capability(
            ConnectorProtocol::Bacnet,
            bacnet_devices > 0,
            bacnet_enabled,
            vec![
                ConnectorAction::MetadataRead,
                ConnectorAction::PointRead,
                ConnectorAction::PriorityArrayRead,
            ],
            mqtt,
            durable,
            bacnet_detail,
        ),
        capability(
            ConnectorProtocol::Modbus,
            modbus_configured,
            modbus_configured,
            vec![ConnectorAction::MetadataRead],
            mqtt,
            durable,
            Some("read-only proxy inventory is not configured for Modbus".into()),
        ),
        capability(
            ConnectorProtocol::Haystack,
            haystack_configured,
            haystack_configured,
            vec![ConnectorAction::MetadataRead],
            mqtt,
            durable,
            Some("explicit Haystack upstream configuration is required".into()),
        ),
        capability(
            ConnectorProtocol::Rest,
            rest_configured,
            rest_configured,
            vec![ConnectorAction::MetadataRead, ConnectorAction::PointRead],
            mqtt,
            durable,
            Some("REST reads use the configured device catalog".into()),
        ),
        capability(
            ConnectorProtocol::Mqtt,
            mqtt_configured,
            mqtt_configured,
            vec![ConnectorAction::MetadataRead],
            mqtt,
            durable,
            Some("MQTT transport and durable delivery are reported separately".into()),
        ),
    ];
    let compiled_protocols = vec![
        ConnectorProtocol::Bacnet,
        ConnectorProtocol::Modbus,
        ConnectorProtocol::Haystack,
        ConnectorProtocol::Rest,
        ConnectorProtocol::Mqtt,
    ];
    ConnectorHelloResponse {
        schema: CAPABILITIES_CONTRACT_V1.into(),
        version: ServiceVersion {
            service: SERVICE_NAME.into(),
            build: build_version(),
            contract: CAPABILITIES_CONTRACT_V1.into(),
        },
        compiled_protocols,
        recipe: recipe_observation(
            &connectors
                .iter()
                .filter(|connector| connector.configured)
                .map(|connector| connector.protocol)
                .collect::<Vec<_>>(),
        ),
        connectors,
        observed_at: Utc::now(),
    }
}

fn local_scope_matches(scope: &openfdd_contracts::ConnectorScope) -> Result<(), ApiError> {
    let expected_edge = std::env::var("OPENFDD_EDGE_ID")
        .or_else(|_| std::env::var("RUSTY_GATEWAY_EDGE_ID"))
        .map_err(|_| ApiError::Forbidden("fieldbus edge identity is not configured".into()))?;
    if expected_edge.trim() != scope.edge_id {
        return Err(ApiError::Forbidden(
            "edge is outside this fieldbus scope".into(),
        ));
    }
    let expected_building = std::env::var("OPENFDD_BUILDING_ID")
        .or_else(|_| std::env::var("OPENFDD_SITE_ID"))
        .map_err(|_| ApiError::Forbidden("fieldbus building identity is not configured".into()))?;
    if expected_building.trim() != scope.building_id {
        return Err(ApiError::Forbidden(
            "building is outside this fieldbus scope".into(),
        ));
    }
    if let Some(tenant) = &scope.tenant_id {
        let expected_tenant = std::env::var("OPENFDD_TENANT_ID").map_err(|_| {
            ApiError::Forbidden("fieldbus tenant identity is not configured".into())
        })?;
        if expected_tenant.trim() != tenant {
            return Err(ApiError::Forbidden(
                "tenant is outside this fieldbus scope".into(),
            ));
        }
    }
    Ok(())
}

async fn connector_hello(State(state): State<AppState>) -> Json<ConnectorHelloResponse> {
    Json(hello_response(&state))
}

async fn connector_read(
    State(state): State<AppState>,
    Json(request): Json<ConnectorReadRequest>,
) -> ApiResult<Json<ConnectorReadResponse>> {
    request.validate().map_err(ApiError::BadRequest)?;
    local_scope_matches(&request.scope)?;
    let response = match &request.target {
        openfdd_contracts::ReadTarget::ConnectorMetadata => ConnectorReadResponse::success(
            &request,
            serde_json::to_value(hello_response(&state))
                .map_err(|error| ApiError::Internal(error.to_string()))?,
        ),
        openfdd_contracts::ReadTarget::BacnetPoint {
            device_instance,
            object_type,
            object_instance,
            property_id,
        } => {
            if !state.bacnet_client.is_configured_point(
                *device_instance,
                object_type,
                *object_instance,
            ) {
                return Err(ApiError::Forbidden(
                    "BACnet point is not in the trusted field-device inventory".into(),
                ));
            }
            let value = state
                .bacnet_client
                .read_property(*device_instance, object_type, *object_instance, property_id)
                .await
                .map_err(ApiError::Bacnet)?;
            ConnectorReadResponse::success(&request, value)
        }
        openfdd_contracts::ReadTarget::BacnetPriorityArray {
            device_instance,
            object_type,
            object_instance,
        } => {
            if !state.bacnet_client.is_configured_point(
                *device_instance,
                object_type,
                *object_instance,
            ) {
                return Err(ApiError::Forbidden(
                    "BACnet object is not in the trusted field-device inventory".into(),
                ));
            }
            let value = state
                .bacnet_client
                .read_priority_array(*device_instance, object_type, *object_instance)
                .await
                .map_err(ApiError::Bacnet)?;
            ConnectorReadResponse::success(&request, value)
        }
    };
    Ok(Json(response))
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/connector/hello", get(connector_hello))
        .route("/api/connector/read", post(connector_read))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hello_is_explicit_about_unconfigured_optional_connectors() {
        assert_eq!(source_state(false, false), CapabilityState::NotConfigured);
        assert_eq!(source_state(true, false), CapabilityState::Disabled);
        assert_eq!(source_state(true, true), CapabilityState::Ready);
    }
}
