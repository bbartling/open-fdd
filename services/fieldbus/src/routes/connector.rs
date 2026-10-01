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
    sanitize_inventory_label, CapabilityState, ConnectorAction, ConnectorCapability,
    ConnectorHelloResponse, ConnectorInventoryRequest, ConnectorInventoryResponse,
    ConnectorProtocol, ConnectorReadRequest, ConnectorReadResponse, ConnectorReadResult,
    DeliveryStatus, InventoryAvailability, InventoryCommandability, InventoryPointReference,
    InventoryProvenance, InventoryRecord, ReadPointResult, ReadPriorityArrayResult,
    ReadPrioritySlot, ReadValueState, RecipeObservation, ServiceVersion, CAPABILITIES_CONTRACT_V1,
    CONNECTOR_INVENTORY_CONTRACT_V1,
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
                .filter(|value| matches!(value.as_str(), "edge" | "standalone" | "central" | "csv"))
        })
}

fn recipe_observation(
    configured_protocols: &[ConnectorProtocol],
    mqtt_connection: DeliveryStatus,
) -> RecipeObservation {
    let declared = declared_recipe();
    let mut configured_services = vec!["fieldbus".to_string()];
    if configured_protocols
        .iter()
        .any(|protocol| matches!(protocol, ConnectorProtocol::Mqtt))
    {
        configured_services.push("mqtt".into());
    }
    configured_services.sort();
    // Returning this hello is runtime evidence that the fieldbus service is
    // alive.  MQTT is observed only when a connector reports a live
    // connection; merely setting OPENFDD_MQTT_HOST or enabling the protocol
    // is configuration, not evidence.
    let mut observed_services = vec!["fieldbus".to_string()];
    if mqtt_connection == DeliveryStatus::Ready {
        observed_services.push("mqtt".into());
    }
    observed_services.sort();
    let reconciliation = RecipeObservation::reconcile(
        declared.as_deref(),
        &configured_services,
        &observed_services,
    );
    let unobserved_services =
        RecipeObservation::missing_services(declared.as_deref(), &observed_services);
    RecipeObservation {
        declared,
        configured_services,
        observed_services,
        unobserved_services,
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
    const FRESHNESS_MS: u64 = 5 * 60 * 1000;
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
    let fails = ledger
        .get("publish_fails")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let last_ack_unix_ms = ledger
        .get("last_ack_unix_ms")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let fresh_ack =
        last_ack_unix_ms > 0 && now_unix_ms().saturating_sub(last_ack_unix_ms) <= FRESHNESS_MS;
    let mqtt = if !mode.uses_mqtt() || !mqtt_enabled() {
        DeliveryStatus::Disabled
    } else if std::env::var("OPENFDD_MQTT_HOST")
        .ok()
        .filter(|host| !host.trim().is_empty())
        .is_none()
    {
        DeliveryStatus::NotConfigured
    } else if fails > 0 && acks == 0 {
        DeliveryStatus::Degraded
    } else if attempts > 0 && fresh_ack {
        // The ledger records enqueue acceptance by the local MQTT client;
        // it is not proof of a broker PUBACK or durable historian delivery.
        DeliveryStatus::Unknown
    } else if attempts > 0 {
        DeliveryStatus::Stale
    } else {
        DeliveryStatus::Checking
    };
    let durable = if mode.uses_local() {
        // The in-memory process mode is not proof that a row reached durable
        // storage. A separate durable receipt/readiness signal is required.
        DeliveryStatus::Unknown
    } else if mode.uses_mqtt() && mqtt_enabled() {
        // A broker acceptance counter is not a durable receipt.
        DeliveryStatus::Unknown
    } else {
        DeliveryStatus::Disabled
    };
    (mqtt, durable)
}

fn now_unix_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
        .unwrap_or(0)
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
    // Haystack is configured through the loaded Settings/TOML mechanism. It
    // is intentionally not advertised as an isolated capability in phase 2;
    // the default settings must never create a fake upstream.
    let haystack_configured = state.settings.haystack_configured;
    let modbus_configured = state.settings.modbus_configured;
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
            false,
            Vec::new(),
            mqtt,
            durable,
            Some("Haystack capability advertisement is reserved for a later phase".into()),
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
            mqtt,
        ),
        connectors,
        observed_at: Utc::now(),
    }
}

fn local_scope_matches(
    settings: &crate::config::Settings,
    scope: &openfdd_contracts::ConnectorScope,
) -> Result<(), ApiError> {
    let expected_edge = settings
        .connector_edge_id
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| ApiError::Forbidden("fieldbus edge identity is not configured".into()))?;
    if expected_edge.trim() != scope.edge_id {
        return Err(ApiError::Forbidden(
            "edge is outside this fieldbus scope".into(),
        ));
    }
    let expected_building = settings
        .connector_building_id
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| {
            ApiError::Forbidden("fieldbus building identity is not configured".into())
        })?;
    if expected_building.trim() != scope.building_id {
        return Err(ApiError::Forbidden(
            "building is outside this fieldbus scope".into(),
        ));
    }
    let expected_tenant = settings
        .connector_tenant_id
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| ApiError::Forbidden("fieldbus tenant identity is not configured".into()))?;
    if expected_tenant.trim() != scope.tenant_id {
        return Err(ApiError::Forbidden(
            "tenant is outside this fieldbus scope".into(),
        ));
    }
    Ok(())
}

async fn connector_hello(State(state): State<AppState>) -> Json<ConnectorHelloResponse> {
    Json(hello_response(&state))
}

fn safe_component(value: &str, fallback: &str) -> String {
    let mut component = String::new();
    for ch in value.trim().chars() {
        if component.len() >= 64 {
            break;
        }
        if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.') {
            component.push(ch.to_ascii_lowercase());
        } else if !component.ends_with('_') {
            component.push('_');
        }
    }
    let component = component.trim_matches('_').to_string();
    if component.is_empty() {
        fallback.into()
    } else {
        component
    }
}

fn inventory_units(value: &str) -> Option<String> {
    let mut cleaned = String::new();
    for ch in value.trim().chars() {
        if ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.' | ':' | '/') {
            cleaned.push(ch);
        } else if !cleaned.ends_with('_') {
            cleaned.push('_');
        }
        if cleaned.len() >= 64 {
            break;
        }
    }
    let cleaned = cleaned.trim_matches('_').to_string();
    (!cleaned.is_empty()).then_some(cleaned)
}

fn inventory_records(state: &AppState) -> Vec<InventoryRecord> {
    let mut records = Vec::new();
    for device in state.bacnet_client.configured_devices() {
        // BACnet instance/object identity is stable when a human label is
        // edited; labels are presentation only.
        let device_id = format!("bacnet:device:{}", device.device_instance);
        let availability = if device.enabled {
            InventoryAvailability::Configured
        } else {
            InventoryAvailability::Disabled
        };
        let actions = if device.enabled {
            vec![ConnectorAction::MetadataRead]
        } else {
            Vec::new()
        };
        records.push(InventoryRecord::Device {
            device_id: device_id.clone(),
            protocol: ConnectorProtocol::Bacnet,
            display_name: sanitize_inventory_label(
                &device.name,
                &format!("BACnet device {}", device.device_instance),
            ),
            availability: availability.clone(),
            commandability: InventoryCommandability::Unknown,
            actions,
        });

        let mut object_types = std::collections::BTreeSet::new();
        for point in &device.points {
            object_types.insert(point.object_type.to_ascii_lowercase());
        }
        for object_type in object_types {
            let object_component = safe_component(&object_type, "object");
            let group_id = format!("{device_id}:object-type:{object_component}");
            records.push(InventoryRecord::Group {
                group_id,
                device_id: device_id.clone(),
                protocol: ConnectorProtocol::Bacnet,
                display_name: sanitize_inventory_label(&object_type, "BACnet object type"),
                availability: availability.clone(),
                commandability: InventoryCommandability::Unknown,
                actions: if device.enabled {
                    vec![ConnectorAction::MetadataRead]
                } else {
                    Vec::new()
                },
            });
        }
        for point in device.points {
            let object_type = point.object_type.to_ascii_lowercase();
            let object_component = safe_component(&object_type, "object");
            let group_id = format!("{device_id}:object-type:{object_component}");
            let point_id = format!(
                "{device_id}:{object_component}:{}:present-value",
                point.object_instance
            );
            records.push(InventoryRecord::Point {
                point_id,
                device_id: device_id.clone(),
                group_id: Some(group_id),
                protocol: ConnectorProtocol::Bacnet,
                display_name: sanitize_inventory_label(
                    &point.point_name,
                    &format!("{object_type} {}", point.object_instance),
                ),
                units: inventory_units(&point.units),
                availability: availability.clone(),
                // Configured object type does not prove commandability. The
                // typed read seam determines this from an actual PA result.
                commandability: InventoryCommandability::Unknown,
                actions: if device.enabled {
                    vec![
                        ConnectorAction::PointRead,
                        ConnectorAction::PriorityArrayRead,
                    ]
                } else {
                    Vec::new()
                },
                reference: InventoryPointReference::Bacnet {
                    device_instance: device.device_instance,
                    object_type,
                    object_instance: point.object_instance,
                    property_id: "present-value".into(),
                },
            });
        }
    }
    if state.settings.modbus_configured {
        records.push(InventoryRecord::Device {
            device_id: "modbus:configured".into(),
            protocol: ConnectorProtocol::Modbus,
            display_name: "Configured Modbus connector".into(),
            availability: InventoryAvailability::Unavailable,
            commandability: InventoryCommandability::Unknown,
            actions: Vec::new(),
        });
    }
    if state.settings.haystack_configured {
        records.push(InventoryRecord::Device {
            device_id: "haystack:configured".into(),
            protocol: ConnectorProtocol::Haystack,
            display_name: "Configured Haystack connector".into(),
            availability: InventoryAvailability::Unavailable,
            commandability: InventoryCommandability::Unknown,
            actions: Vec::new(),
        });
    }
    records.sort_by(|left, right| left.key_for_order().cmp(&right.key_for_order()));
    records
}

fn inventory_revision(records: &[InventoryRecord]) -> String {
    let bytes = match serde_json::to_vec(records) {
        Ok(bytes) => bytes,
        Err(_) => return "config-invalid".into(),
    };
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in bytes {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("config-{hash:016x}")
}

fn build_inventory(
    state: &AppState,
    request: &ConnectorInventoryRequest,
) -> Result<ConnectorInventoryResponse, ApiError> {
    let all_records = inventory_records(state);
    let revision = inventory_revision(&all_records);
    let protocols = &request.protocols;
    let filtered: Vec<_> = all_records
        .into_iter()
        .filter(|record| protocols.is_empty() || protocols.contains(&record.protocol()))
        .collect();
    let offset = request
        .offset_for_revision(&revision)
        .map_err(|_| ApiError::BadRequest("inventory cursor is invalid or stale".into()))?;
    if offset > filtered.len() {
        return Err(ApiError::BadRequest(
            "inventory cursor is invalid or stale".into(),
        ));
    }
    let end = offset
        .saturating_add(usize::from(request.page_size))
        .min(filtered.len());
    let page = filtered[offset..end].to_vec();
    let mut page_protocols = page
        .iter()
        .map(InventoryRecord::protocol)
        .collect::<Vec<_>>();
    page_protocols.sort_by_key(|protocol| *protocol as u8);
    page_protocols.dedup();
    let response = ConnectorInventoryResponse {
        schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
        request_id: request.request_id,
        scope: request.scope.clone(),
        protocols: page_protocols,
        revision: revision.clone(),
        captured_at: Utc::now(),
        provenance: InventoryProvenance::TrustedConfiguration,
        records: page,
        next_cursor: (end < filtered.len())
            .then(|| request.cursor_for_revision(&revision, end))
            .transpose()
            .map_err(|_| {
                ApiError::Internal("connector returned an invalid inventory cursor".into())
            })?,
    };
    response
        .validate_for(request)
        .map_err(|_| ApiError::Internal("connector returned an invalid inventory page".into()))?;
    Ok(response)
}

async fn connector_read(
    State(state): State<AppState>,
    Json(request): Json<ConnectorReadRequest>,
) -> ApiResult<Json<ConnectorReadResponse>> {
    request.validate().map_err(ApiError::BadRequest)?;
    local_scope_matches(&state.settings, &request.scope)?;
    let response = match &request.target {
        openfdd_contracts::ReadTarget::ConnectorMetadata => ConnectorReadResponse::success(
            &request,
            ConnectorReadResult::Metadata {
                hello: hello_response(&state),
            },
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
                .map_err(|_| ApiError::Bacnet("connector read failed".into()))?;
            ConnectorReadResponse::success(
                &request,
                point_result(
                    value,
                    *device_instance,
                    object_type,
                    *object_instance,
                    property_id,
                )?,
            )
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
                .map_err(|_| ApiError::Bacnet("priority-array read failed".into()))?;
            ConnectorReadResponse::success(
                &request,
                priority_array_result(value, *device_instance, object_type, *object_instance)?,
            )
        }
    };
    response.validate_for(&request).map_err(|_| {
        ApiError::Internal("connector returned an invalid public read result".into())
    })?;
    Ok(Json(response))
}

async fn connector_inventory(
    State(state): State<AppState>,
    Json(request): Json<ConnectorInventoryRequest>,
) -> ApiResult<Json<ConnectorInventoryResponse>> {
    request.validate().map_err(ApiError::BadRequest)?;
    local_scope_matches(&state.settings, &request.scope)?;
    Ok(Json(build_inventory(&state, &request)?))
}

fn point_result(
    value: Value,
    device_instance: u32,
    object_type: &str,
    object_instance: u32,
    property_id: &str,
) -> Result<ConnectorReadResult, ApiError> {
    let object = value
        .as_object()
        .ok_or_else(|| ApiError::Internal("connector returned malformed point result".into()))?;
    let matches_target = object.get("device_instance").and_then(Value::as_u64)
        == Some(u64::from(device_instance))
        && object
            .get("object_type")
            .and_then(Value::as_str)
            .is_some_and(|actual| actual.eq_ignore_ascii_case(object_type))
        && object.get("object_instance").and_then(Value::as_u64)
            == Some(u64::from(object_instance))
        && object
            .get("property_id")
            .and_then(Value::as_str)
            .is_some_and(|actual| actual.eq_ignore_ascii_case(property_id));
    if !matches_target {
        return Err(ApiError::Internal(
            "connector returned mismatched point result".into(),
        ));
    }
    let value_type = object
        .get("tag")
        .and_then(Value::as_str)
        .filter(|tag| !tag.is_empty() && tag.len() <= 64)
        .ok_or_else(|| ApiError::Internal("connector returned invalid point type".into()))?;
    let quality = object
        .get("quality")
        .and_then(Value::as_str)
        .filter(|quality| matches!(*quality, "good" | "bad"))
        .ok_or_else(|| ApiError::Internal("connector returned invalid point quality".into()))?;
    Ok(ConnectorReadResult::Point(ReadPointResult {
        device_instance,
        object_type: object_type.into(),
        object_instance,
        property_id: property_id.into(),
        value_type: value_type.into(),
        value: object.get("value").cloned().unwrap_or(Value::Null),
        quality: quality.into(),
        observed_at: Utc::now(),
    }))
}

fn priority_array_result(
    value: Value,
    device_instance: u32,
    object_type: &str,
    object_instance: u32,
) -> Result<ConnectorReadResult, ApiError> {
    let object = value
        .as_object()
        .ok_or_else(|| ApiError::Internal("connector returned malformed priority array".into()))?;
    let expected_identifier = format!("{object_type},{object_instance}");
    let Some(actual_identifier) = object.get("object_identifier").and_then(Value::as_str) else {
        return Err(ApiError::Internal(
            "connector returned malformed priority identifier".into(),
        ));
    };
    if object.get("device_instance").and_then(Value::as_u64) != Some(u64::from(device_instance))
        || !actual_identifier.eq_ignore_ascii_case(&expected_identifier)
    {
        return Err(ApiError::Internal(
            "connector returned mismatched priority array".into(),
        ));
    }
    let raw_slots = object
        .get("priority_array")
        .and_then(Value::as_array)
        .ok_or_else(|| ApiError::Internal("connector returned no priority slots".into()))?;
    let mut slots = Vec::with_capacity(raw_slots.len());
    for raw in raw_slots {
        let mut slot: ReadPrioritySlot = serde_json::from_value(raw.clone())
            .map_err(|_| ApiError::Internal("connector returned malformed priority slot".into()))?;
        match slot.state {
            ReadValueState::Null if slot.value.is_some() || slot.error.is_some() => {
                return Err(ApiError::Internal(
                    "connector returned contradictory null priority slot".into(),
                ));
            }
            ReadValueState::Value if slot.value.is_none() || slot.error.is_some() => {
                return Err(ApiError::Internal(
                    "connector returned contradictory value priority slot".into(),
                ));
            }
            ReadValueState::Error if slot.value.is_some() => {
                return Err(ApiError::Internal(
                    "connector returned contradictory error priority slot".into(),
                ));
            }
            ReadValueState::Error => slot.error = Some("priority slot unavailable".into()),
            ReadValueState::Unknown if slot.value.is_some() => {
                return Err(ApiError::Internal(
                    "connector returned contradictory unknown priority slot".into(),
                ));
            }
            ReadValueState::Unknown => {
                slot.error = slot.error.map(|_| "priority slot unavailable".into());
            }
            ReadValueState::Null | ReadValueState::Value => {}
        }
        slots.push(slot);
    }
    let state = object
        .get("priority_array_state")
        .and_then(Value::as_str)
        .filter(|state| matches!(*state, "supported" | "unsupported" | "unknown"))
        .ok_or_else(|| ApiError::Internal("connector returned invalid priority state".into()))?;
    Ok(ConnectorReadResult::PriorityArray(
        ReadPriorityArrayResult {
            device_instance,
            object_type: object_type.into(),
            object_instance,
            slots,
            state: state.into(),
            observed_at: Utc::now(),
        },
    ))
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/connector/hello", get(connector_hello))
        .route("/api/connector/inventory", post(connector_inventory))
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
