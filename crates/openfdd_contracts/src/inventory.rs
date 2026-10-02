//! Versioned, scoped connector inventory contracts.
//!
//! Inventory is a configuration and registration projection.  It is not a
//! discovery command and it does not imply that an OT device was contacted.
//! A caller may use a point's typed reference with the existing read proxy;
//! availability, commandability, and actions remain separate fields.

use std::collections::HashSet;
use std::net::IpAddr;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::capabilities::{ConnectorAction, ConnectorProtocol};
use crate::proxy::ConnectorScope;

pub const CONNECTOR_INVENTORY_CONTRACT_V1: &str = "openfdd.connector.inventory.v1";
pub const INVENTORY_MAX_PAGE_SIZE: u16 = 100;
pub const INVENTORY_MAX_CURSOR_LENGTH: usize = 96;
const INVENTORY_MAX_RECORDS: usize = INVENTORY_MAX_PAGE_SIZE as usize;
const INVENTORY_CURSOR_VERSION: &str = "v1";
const INVENTORY_CURSOR_BINDING_LENGTH: usize = 16;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum InventoryAvailability {
    /// Present in trusted configuration. No live OT probe is implied.
    Configured,
    Disabled,
    /// The protocol is configured, but this phase has no typed catalog/read
    /// projection for it. The record is intentionally not actionable.
    Unavailable,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum InventoryCommandability {
    Supported,
    Unsupported,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum InventoryProvenance {
    TrustedConfiguration,
    LocalRegistration,
}

/// A protocol-specific, non-network address for a configured point.
///
/// Host names, ports, URLs, MQTT topics, and credentials are deliberately not
/// part of this public contract.  BACnet object identity is sufficient for the
/// existing scoped read proxy to perform an explicitly requested read.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum InventoryPointReference {
    Bacnet {
        device_instance: u32,
        object_type: String,
        object_instance: u32,
        property_id: String,
    },
    Modbus {
        unit_id: u8,
        register: u16,
        function: String,
    },
    Haystack {
        id: String,
    },
    Rest {
        device: String,
        point: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ConnectorInventoryRequest {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    /// Empty means all protocols represented by the trusted connector.
    #[serde(default)]
    pub protocols: Vec<ConnectorProtocol>,
    #[serde(default = "default_page_size")]
    pub page_size: u16,
    #[serde(default)]
    pub cursor: Option<String>,
}

fn default_page_size() -> u16 {
    INVENTORY_MAX_PAGE_SIZE
}

impl ConnectorInventoryRequest {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != CONNECTOR_INVENTORY_CONTRACT_V1 {
            return Err("unsupported connector inventory schema".into());
        }
        self.scope.validate()?;
        if self.page_size == 0 || self.page_size > INVENTORY_MAX_PAGE_SIZE {
            return Err(format!(
                "inventory page_size must be between 1 and {INVENTORY_MAX_PAGE_SIZE}"
            ));
        }
        validate_protocol_filter(&self.protocols)?;
        if let Some(cursor) = self.cursor.as_deref() {
            validate_cursor(cursor)?;
        }
        Ok(())
    }

    /// Decode a continuation only when it belongs to this exact query and
    /// configuration revision. A cursor cannot be reused across scopes,
    /// filters, page sizes, or changed configuration.
    pub fn offset_for_revision(&self, revision: &str) -> Result<usize, String> {
        self.cursor
            .as_deref()
            .map(|cursor| decode_cursor(self, cursor, revision))
            .transpose()
            .map(|offset| offset.unwrap_or(0))
    }

    pub fn cursor_for_revision(&self, revision: &str, offset: usize) -> Result<String, String> {
        validate_token(revision, 128, "inventory revision")?;
        let cursor = format!(
            "{INVENTORY_CURSOR_VERSION}.{}.{}.{}",
            revision,
            cursor_binding(self),
            offset
        );
        validate_cursor(&cursor)?;
        Ok(cursor)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct ConnectorInventoryResponse {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    /// Protocols represented by this page, in stable enum order.
    pub protocols: Vec<ConnectorProtocol>,
    /// Stable revision of the trusted configuration snapshot.
    pub revision: String,
    pub captured_at: DateTime<Utc>,
    pub provenance: InventoryProvenance,
    pub records: Vec<InventoryRecord>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum InventoryRecord {
    Device {
        device_id: String,
        protocol: ConnectorProtocol,
        display_name: String,
        availability: InventoryAvailability,
        commandability: InventoryCommandability,
        #[serde(default)]
        actions: Vec<ConnectorAction>,
    },
    Group {
        group_id: String,
        device_id: String,
        protocol: ConnectorProtocol,
        display_name: String,
        availability: InventoryAvailability,
        commandability: InventoryCommandability,
        #[serde(default)]
        actions: Vec<ConnectorAction>,
    },
    Point {
        point_id: String,
        device_id: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        group_id: Option<String>,
        protocol: ConnectorProtocol,
        display_name: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        units: Option<String>,
        availability: InventoryAvailability,
        commandability: InventoryCommandability,
        #[serde(default)]
        actions: Vec<ConnectorAction>,
        reference: InventoryPointReference,
    },
}

impl InventoryRecord {
    fn key(&self) -> (&'static str, &str) {
        match self {
            Self::Device { device_id, .. } => ("device", device_id),
            Self::Group { group_id, .. } => ("group", group_id),
            Self::Point { point_id, .. } => ("point", point_id),
        }
    }

    pub fn protocol(&self) -> ConnectorProtocol {
        match self {
            Self::Device { protocol, .. }
            | Self::Group { protocol, .. }
            | Self::Point { protocol, .. } => *protocol,
        }
    }

    /// Stable ordering key for pagination. The kind prefix keeps device and
    /// group records ahead of their points without exposing an address.
    pub fn key_for_order(&self) -> (u8, &str) {
        let (kind, id) = self.key();
        let rank = match kind {
            "device" => 0,
            "group" => 1,
            _ => 2,
        };
        (rank, id)
    }

    fn validate(&self) -> Result<(), String> {
        match self {
            Self::Device {
                device_id,
                protocol,
                display_name,
                availability,
                commandability,
                actions,
                ..
            } => {
                validate_id(device_id, "inventory device id")?;
                validate_display_name(display_name)?;
                validate_actions(actions)?;
                validate_actions_for_record(*protocol, false, actions)?;
                validate_record_state(availability, *commandability, actions, false)?;
            }
            Self::Group {
                group_id,
                device_id,
                protocol,
                display_name,
                availability,
                commandability,
                actions,
                ..
            } => {
                validate_id(group_id, "inventory group id")?;
                validate_id(device_id, "inventory group device id")?;
                validate_display_name(display_name)?;
                validate_actions(actions)?;
                validate_actions_for_record(*protocol, false, actions)?;
                validate_record_state(availability, *commandability, actions, false)?;
            }
            Self::Point {
                point_id,
                device_id,
                group_id,
                display_name,
                units,
                protocol,
                availability,
                commandability,
                actions,
                reference,
                ..
            } => {
                validate_id(point_id, "inventory point id")?;
                validate_id(device_id, "inventory point device id")?;
                if let Some(group_id) = group_id {
                    validate_id(group_id, "inventory point group id")?;
                }
                validate_display_name(display_name)?;
                if let Some(units) = units {
                    validate_token(units, 64, "inventory units")?;
                }
                validate_actions(actions)?;
                validate_reference(reference)?;
                if !reference_matches_protocol(*protocol, reference) {
                    return Err("inventory point reference does not match protocol".into());
                }
                validate_actions_for_record(*protocol, true, actions)?;
                validate_record_state(availability, *commandability, actions, true)?;
            }
        }
        Ok(())
    }
}

impl ConnectorInventoryResponse {
    pub fn validate_for(&self, request: &ConnectorInventoryRequest) -> Result<(), String> {
        request.validate()?;
        if self.schema != CONNECTOR_INVENTORY_CONTRACT_V1
            || self.request_id != request.request_id
            || self.scope != request.scope
        {
            return Err("connector inventory response correlation failed".into());
        }
        validate_protocol_filter(&self.protocols)?;
        validate_token(&self.revision, 128, "inventory revision")?;
        let offset = request.offset_for_revision(&self.revision)?;
        if self.records.len() > usize::from(request.page_size)
            || self.records.len() > INVENTORY_MAX_RECORDS
        {
            return Err("connector inventory page exceeds its bound".into());
        }
        if let Some(cursor) = self.next_cursor.as_deref() {
            let next_offset = decode_cursor(request, cursor, &self.revision)?;
            if self.records.is_empty() {
                return Err("empty inventory pages cannot continue".into());
            }
            let expected_offset = offset.saturating_add(self.records.len());
            if next_offset != expected_offset {
                return Err("inventory continuation cursor skipped records".into());
            }
        }
        let protocols: HashSet<_> = self.protocols.iter().copied().collect();
        let requested: HashSet<_> = request.protocols.iter().copied().collect();
        let mut actual_protocols = HashSet::new();
        let mut keys = HashSet::new();
        for record in &self.records {
            record.validate()?;
            actual_protocols.insert(record.protocol());
            if !protocols.contains(&record.protocol()) {
                return Err("inventory record protocol is missing from response protocols".into());
            }
            if !requested.is_empty() && !requested.contains(&record.protocol()) {
                return Err("inventory record is outside the requested protocol filter".into());
            }
            if !keys.insert(record.key()) {
                return Err("inventory contains a duplicate record id".into());
            }
        }
        if actual_protocols != protocols {
            return Err("inventory response protocols do not match its page".into());
        }
        Ok(())
    }
}

fn validate_protocol_filter(protocols: &[ConnectorProtocol]) -> Result<(), String> {
    if protocols.len() > 5 {
        return Err("inventory protocol filter is too large".into());
    }
    let mut seen = HashSet::new();
    if protocols.iter().any(|protocol| !seen.insert(protocol)) {
        return Err("inventory protocol filter contains duplicates".into());
    }
    Ok(())
}

fn validate_cursor(cursor: &str) -> Result<(), String> {
    if cursor.is_empty() || cursor.len() > INVENTORY_MAX_CURSOR_LENGTH {
        return Err("inventory cursor is malformed".into());
    }
    let parts: Vec<_> = cursor.split('.').collect();
    if parts.len() != 4
        || parts[0] != INVENTORY_CURSOR_VERSION
        || parts[2].len() != INVENTORY_CURSOR_BINDING_LENGTH
        || !parts[2].bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        return Err("inventory cursor is malformed".into());
    }
    validate_token(parts[1], 128, "inventory cursor revision")?;
    parts[3]
        .parse::<usize>()
        .map(|_| ())
        .map_err(|_| "inventory cursor is out of range".into())
}

fn decode_cursor(
    request: &ConnectorInventoryRequest,
    cursor: &str,
    revision: &str,
) -> Result<usize, String> {
    validate_cursor(cursor)?;
    let parts: Vec<_> = cursor.split('.').collect();
    if parts[1] != revision {
        return Err("inventory cursor is stale for this configuration revision".into());
    }
    if parts[2] != cursor_binding(request) {
        return Err("inventory cursor is outside this scope or query".into());
    }
    parts[3]
        .parse::<usize>()
        .map_err(|_| "inventory cursor is out of range".into())
}

fn cursor_binding(request: &ConnectorInventoryRequest) -> String {
    let mut hash = 0xcbf29ce484222325_u64;
    fn feed(hash: &mut u64, bytes: &[u8]) {
        for byte in bytes {
            *hash ^= u64::from(*byte);
            *hash = hash.wrapping_mul(0x100000001b3);
        }
        *hash ^= 0xff;
        *hash = hash.wrapping_mul(0x100000001b3);
    }
    feed(&mut hash, request.scope.tenant_id.as_bytes());
    feed(&mut hash, request.scope.building_id.as_bytes());
    feed(&mut hash, request.scope.edge_id.as_bytes());
    feed(&mut hash, request.page_size.to_string().as_bytes());
    for protocol in &request.protocols {
        feed(&mut hash, protocol_key(*protocol).as_bytes());
    }
    format!("{hash:016x}")
}

fn protocol_key(protocol: ConnectorProtocol) -> &'static str {
    match protocol {
        ConnectorProtocol::Bacnet => "bacnet",
        ConnectorProtocol::Modbus => "modbus",
        ConnectorProtocol::Haystack => "haystack",
        ConnectorProtocol::Rest => "rest",
        ConnectorProtocol::Mqtt => "mqtt",
    }
}

fn validate_id(value: &str, field: &str) -> Result<(), String> {
    validate_token(value, 256, field)?;
    let lower = value.to_ascii_lowercase();
    if looks_like_network_address(value)
        || lower.contains("password")
        || lower.contains("authorization")
        || lower.contains("credential")
        || lower.contains("bearer ")
        || lower.contains("api_key")
        || lower.contains("token=")
    {
        return Err(format!("{field} contains private connection data"));
    }
    Ok(())
}

fn validate_display_name(value: &str) -> Result<(), String> {
    let lower = value.to_ascii_lowercase();
    if value.trim().is_empty()
        || value.len() > 128
        || value.chars().any(|ch| ch.is_control())
        || value.contains("://")
        || value.contains('@')
        || looks_like_network_address(value)
        || lower.contains("password")
        || lower.contains("authorization")
        || lower.contains("credential")
        || lower.contains("bearer ")
        || lower.contains("api_key")
        || lower.contains("token=")
    {
        return Err("inventory display name is invalid".into());
    }
    Ok(())
}

fn validate_token(value: &str, max: usize, field: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > max
        || value.contains("@")
        || value.contains("://")
        || !value
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.' | ':' | '/'))
    {
        return Err(format!("{field} is invalid"));
    }
    Ok(())
}

fn looks_like_network_address(value: &str) -> bool {
    for token in value.split(|ch: char| {
        ch.is_whitespace()
            || matches!(
                ch,
                '=' | ',' | ';' | '|' | '(' | ')' | '{' | '}' | '<' | '>'
            )
    }) {
        let trimmed = token.trim().trim_matches(['[', ']', '"', '\'']);
        if trimmed.is_empty() {
            continue;
        }
        if trimmed.parse::<IpAddr>().is_ok() {
            return true;
        }
        if let Some((host, port)) = trimmed.rsplit_once(':') {
            let host = host.trim().trim_matches(['[', ']']);
            let numeric_port = !port.is_empty() && port.bytes().all(|byte| byte.is_ascii_digit());
            let hostname_or_address = host.eq_ignore_ascii_case("localhost")
                || host.contains('.')
                || host.parse::<IpAddr>().is_ok()
                || (port.parse::<u16>().is_ok_and(|port| port >= 1024) && !host.contains(':'));
            if numeric_port && hostname_or_address {
                return true;
            }
        }
    }
    false
}

fn validate_actions(actions: &[ConnectorAction]) -> Result<(), String> {
    if actions.len() > 8 {
        return Err("inventory action list is too large".into());
    }
    let mut seen = HashSet::new();
    if actions.iter().any(|action| !seen.insert(action)) {
        return Err("inventory action list contains duplicates".into());
    }
    Ok(())
}

fn validate_actions_for_record(
    protocol: ConnectorProtocol,
    point: bool,
    actions: &[ConnectorAction],
) -> Result<(), String> {
    for action in actions {
        let allowed = match (protocol, point, action) {
            (_, false, ConnectorAction::MetadataRead) => true,
            (_, false, _) => false,
            (ConnectorProtocol::Bacnet, true, _) => true,
            (_, true, ConnectorAction::MetadataRead | ConnectorAction::PointRead) => true,
            (
                _,
                true,
                ConnectorAction::PriorityArrayRead
                | ConnectorAction::PriorityHistoryRead
                | ConnectorAction::PriorityHistoryTrigger,
            ) => false,
        };
        if !allowed {
            return Err("inventory action is unsupported for this record".into());
        }
    }
    Ok(())
}

fn validate_record_state(
    availability: &InventoryAvailability,
    commandability: InventoryCommandability,
    actions: &[ConnectorAction],
    point: bool,
) -> Result<(), String> {
    if !point && commandability != InventoryCommandability::Unknown {
        return Err("device and group commandability must remain unknown".into());
    }
    if matches!(
        availability,
        InventoryAvailability::Disabled | InventoryAvailability::Unavailable
    ) && !actions.is_empty()
    {
        return Err("disabled or unavailable inventory records cannot advertise actions".into());
    }
    if matches!(availability, InventoryAvailability::Unavailable)
        && commandability != InventoryCommandability::Unknown
    {
        return Err("unavailable inventory records cannot advertise commandability".into());
    }
    Ok(())
}

fn reference_matches_protocol(
    protocol: ConnectorProtocol,
    reference: &InventoryPointReference,
) -> bool {
    matches!(
        (protocol, reference),
        (
            ConnectorProtocol::Bacnet,
            InventoryPointReference::Bacnet { .. }
        ) | (
            ConnectorProtocol::Modbus,
            InventoryPointReference::Modbus { .. }
        ) | (
            ConnectorProtocol::Haystack,
            InventoryPointReference::Haystack { .. }
        ) | (
            ConnectorProtocol::Rest,
            InventoryPointReference::Rest { .. }
        )
    )
}

/// Project configuration labels into the constrained public inventory text
/// surface. Unsafe labels become a generic fallback so one bad entry cannot
/// fail an otherwise valid page.
pub fn sanitize_inventory_label(value: &str, fallback: &str) -> String {
    let cleaned: String = value
        .trim()
        .chars()
        .filter(|ch| !ch.is_control())
        .take(128)
        .collect();
    if validate_display_name(&cleaned).is_ok() {
        cleaned
    } else if validate_display_name(fallback).is_ok() {
        fallback.to_string()
    } else {
        "Unnamed connector record".into()
    }
}

fn validate_reference(reference: &InventoryPointReference) -> Result<(), String> {
    match reference {
        InventoryPointReference::Bacnet {
            device_instance,
            object_type,
            object_instance,
            property_id,
        } => {
            if *device_instance > 4_194_303 || *object_instance > 4_194_303 {
                return Err("BACnet instance is out of range".into());
            }
            validate_token(object_type, 64, "BACnet object type")?;
            validate_token(property_id, 64, "BACnet property id")?;
        }
        InventoryPointReference::Modbus {
            unit_id, function, ..
        } => {
            if *unit_id > 247 {
                return Err("Modbus unit id is out of range".into());
            }
            validate_token(function, 32, "Modbus function")?;
        }
        InventoryPointReference::Haystack { id } => validate_token(id, 256, "Haystack id")?,
        InventoryPointReference::Rest { device, point } => {
            validate_display_name(device)?;
            validate_display_name(point)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scope() -> ConnectorScope {
        ConnectorScope {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
        }
    }

    fn request() -> ConnectorInventoryRequest {
        ConnectorInventoryRequest {
            schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
            request_id: Uuid::nil(),
            scope: scope(),
            protocols: vec![ConnectorProtocol::Bacnet],
            page_size: 10,
            cursor: None,
        }
    }

    fn point() -> InventoryRecord {
        InventoryRecord::Point {
            point_id: "bacnet:7:analog-value:1:present-value".into(),
            device_id: "bacnet:device:7".into(),
            group_id: Some("bacnet:device:7:analog-value".into()),
            protocol: ConnectorProtocol::Bacnet,
            display_name: "Supply temperature".into(),
            units: Some("degF".into()),
            availability: InventoryAvailability::Configured,
            commandability: InventoryCommandability::Unknown,
            actions: vec![
                ConnectorAction::PointRead,
                ConnectorAction::PriorityArrayRead,
            ],
            reference: InventoryPointReference::Bacnet {
                device_instance: 7,
                object_type: "analog-value".into(),
                object_instance: 1,
                property_id: "present-value".into(),
            },
        }
    }

    #[test]
    fn inventory_contract_round_trips_typed_scope_and_reference() {
        let request = request();
        let response = ConnectorInventoryResponse {
            schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            protocols: vec![ConnectorProtocol::Bacnet],
            revision: "config-0123".into(),
            captured_at: Utc::now(),
            provenance: InventoryProvenance::TrustedConfiguration,
            records: vec![point()],
            next_cursor: None,
        };
        response.validate_for(&request).unwrap();
        let decoded: ConnectorInventoryResponse =
            serde_json::from_value(serde_json::to_value(&response).unwrap()).unwrap();
        assert_eq!(decoded.scope, request.scope);
        assert!(matches!(
            decoded.records[0],
            InventoryRecord::Point {
                reference: InventoryPointReference::Bacnet { .. },
                ..
            }
        ));
    }

    #[test]
    fn inventory_request_bounds_page_and_cursor() {
        let mut request = request();
        request.page_size = INVENTORY_MAX_PAGE_SIZE + 1;
        assert!(request.validate().is_err());
        request.page_size = 1;
        request.cursor = Some("x".into());
        assert!(request.validate().is_err());
        request.cursor = Some("9".repeat(INVENTORY_MAX_CURSOR_LENGTH + 1));
        assert!(request.validate().is_err());
    }

    #[test]
    fn inventory_cursor_is_bound_to_revision_scope_filter_and_page_size() {
        let request = request();
        let cursor = request.cursor_for_revision("config-0123", 1).unwrap();
        assert_eq!(
            request
                .clone()
                .with_cursor(cursor.clone())
                .offset_for_revision("config-0123")
                .unwrap(),
            1
        );

        let mut changed_scope = request.clone().with_cursor(cursor.clone());
        changed_scope.scope.tenant_id = "tenant-b".into();
        assert!(changed_scope.offset_for_revision("config-0123").is_err());

        let mut changed_filter = request.clone().with_cursor(cursor.clone());
        changed_filter.protocols = vec![ConnectorProtocol::Modbus];
        assert!(changed_filter.offset_for_revision("config-0123").is_err());

        let mut changed_page = request.clone().with_cursor(cursor);
        changed_page.page_size = 20;
        assert!(changed_page.offset_for_revision("config-0123").is_err());
        assert!(request
            .clone()
            .with_cursor(request.cursor_for_revision("config-0123", 1).unwrap())
            .offset_for_revision("config-9999")
            .is_err());
    }

    #[test]
    fn inventory_continuation_must_advance_and_cannot_be_empty() {
        let request = request();
        let record = point();
        let make_response = |next_cursor| ConnectorInventoryResponse {
            schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            protocols: vec![ConnectorProtocol::Bacnet],
            revision: "config-0123".into(),
            captured_at: Utc::now(),
            provenance: InventoryProvenance::TrustedConfiguration,
            records: vec![record.clone()],
            next_cursor,
        };
        let valid = request.cursor_for_revision("config-0123", 1).unwrap();
        assert!(make_response(Some(valid)).validate_for(&request).is_ok());
        let repeated = request.cursor_for_revision("config-0123", 0).unwrap();
        assert!(make_response(Some(repeated))
            .validate_for(&request)
            .is_err());
        assert!(make_response(Some(String::new()))
            .validate_for(&request)
            .is_err());
        let backwards = request.cursor_for_revision("config-0123", 0).unwrap();
        let mut continued = request.clone().with_cursor(backwards);
        continued.cursor = Some(request.cursor_for_revision("config-0123", 1).unwrap());
        let same_page_cursor = request.cursor_for_revision("config-0123", 1).unwrap();
        assert!(make_response(Some(same_page_cursor))
            .validate_for(&continued)
            .is_err());
        let empty_page = ConnectorInventoryResponse {
            records: Vec::new(),
            next_cursor: Some(request.cursor_for_revision("config-0123", 1).unwrap()),
            ..make_response(None)
        };
        assert!(empty_page.validate_for(&request).is_err());
        let skipped_page =
            make_response(Some(request.cursor_for_revision("config-0123", 3).unwrap()));
        assert!(skipped_page.validate_for(&request).is_err());
    }

    #[test]
    fn inventory_rejects_protocol_reference_and_action_mismatches() {
        let request = request();
        let mut response = make_response_for_record(request.clone(), point());
        if let InventoryRecord::Point {
            protocol,
            reference,
            ..
        } = &mut response.records[0]
        {
            *protocol = ConnectorProtocol::Modbus;
            *reference = InventoryPointReference::Bacnet {
                device_instance: 7,
                object_type: "analog-value".into(),
                object_instance: 1,
                property_id: "present-value".into(),
            };
        }
        assert!(response.validate_for(&request).is_err());

        let mut response = make_response_for_record(request.clone(), point());
        if let InventoryRecord::Point {
            protocol, actions, ..
        } = &mut response.records[0]
        {
            *protocol = ConnectorProtocol::Modbus;
            *actions = vec![ConnectorAction::PriorityArrayRead];
        }
        assert!(response.validate_for(&request).is_err());
    }

    #[test]
    fn inventory_rejects_out_of_range_identifiers_and_false_availability() {
        let request = request();
        let mut response = make_response_for_record(request.clone(), point());
        if let InventoryRecord::Point { reference, .. } = &mut response.records[0] {
            *reference = InventoryPointReference::Bacnet {
                device_instance: 4_194_304,
                object_type: "analog-value".into(),
                object_instance: 1,
                property_id: "present-value".into(),
            };
        }
        assert!(response.validate_for(&request).is_err());

        let mut response = make_response_for_record(request.clone(), point());
        if let InventoryRecord::Point {
            availability,
            actions,
            ..
        } = &mut response.records[0]
        {
            *availability = InventoryAvailability::Unavailable;
            *actions = vec![ConnectorAction::PointRead];
        }
        assert!(response.validate_for(&request).is_err());
    }

    #[test]
    fn inventory_response_rejects_scope_protocol_and_duplicate_mismatches() {
        let request = request();
        let mut response = ConnectorInventoryResponse {
            schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            protocols: vec![ConnectorProtocol::Bacnet],
            revision: "config-0123".into(),
            captured_at: Utc::now(),
            provenance: InventoryProvenance::LocalRegistration,
            records: vec![point()],
            next_cursor: None,
        };
        response.scope.tenant_id = "foreign".into();
        assert!(response.validate_for(&request).is_err());
        response.scope = request.scope.clone();
        response.protocols = vec![ConnectorProtocol::Modbus];
        assert!(response.validate_for(&request).is_err());
        response.protocols = vec![ConnectorProtocol::Bacnet];
        response.records.push(point());
        assert!(response.validate_for(&request).is_err());
    }

    #[test]
    fn inventory_public_text_rejects_addresses_and_credentials() {
        let request = request();
        let mut response = ConnectorInventoryResponse {
            schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            protocols: vec![ConnectorProtocol::Bacnet],
            revision: "config-test".into(),
            captured_at: Utc::now(),
            provenance: InventoryProvenance::TrustedConfiguration,
            records: vec![point()],
            next_cursor: None,
        };
        if let InventoryRecord::Point { display_name, .. } = &mut response.records[0] {
            *display_name = "https://user:secret@example.test".into();
        }
        assert!(response.validate_for(&request).is_err());
        assert_eq!(
            sanitize_inventory_label("127.0.0.1:47808", "safe fallback"),
            "safe fallback"
        );
        assert_eq!(
            sanitize_inventory_label("token=secret", "safe fallback"),
            "safe fallback"
        );
        assert_eq!(
            sanitize_inventory_label("Gateway at 192.168.204.11:47808", "safe fallback"),
            "safe fallback"
        );
        assert_eq!(
            sanitize_inventory_label("BACnet gateway [fe80::1]:47808", "safe fallback"),
            "safe fallback"
        );
    }

    #[test]
    fn inventory_rejects_address_derived_public_ids() {
        let request = request();
        let mut response = make_response_for_record(request.clone(), point());
        if let InventoryRecord::Point { point_id, .. } = &mut response.records[0] {
            *point_id = "127.0.0.1:47808".into();
        }
        assert!(response.validate_for(&request).is_err());
    }

    trait RequestCursorExt {
        fn with_cursor(self, cursor: String) -> Self;
    }

    impl RequestCursorExt for ConnectorInventoryRequest {
        fn with_cursor(mut self, cursor: String) -> Self {
            self.cursor = Some(cursor);
            self
        }
    }

    fn make_response_for_record(
        request: ConnectorInventoryRequest,
        record: InventoryRecord,
    ) -> ConnectorInventoryResponse {
        ConnectorInventoryResponse {
            schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope,
            protocols: vec![record.protocol()],
            revision: "config-0123".into(),
            captured_at: Utc::now(),
            provenance: InventoryProvenance::TrustedConfiguration,
            records: vec![record],
            next_cursor: None,
        }
    }
}
