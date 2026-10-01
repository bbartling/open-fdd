//! Versioned, scoped connector inventory contracts.
//!
//! Inventory is a configuration and registration projection.  It is not a
//! discovery command and it does not imply that an OT device was contacted.
//! A caller may use a point's typed reference with the existing read proxy;
//! availability, commandability, and actions remain separate fields.

use std::collections::HashSet;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::capabilities::{ConnectorAction, ConnectorProtocol};
use crate::proxy::ConnectorScope;

pub const CONNECTOR_INVENTORY_CONTRACT_V1: &str = "openfdd.connector.inventory.v1";
pub const INVENTORY_MAX_PAGE_SIZE: u16 = 100;
pub const INVENTORY_MAX_CURSOR_LENGTH: usize = 64;
const INVENTORY_MAX_RECORDS: usize = INVENTORY_MAX_PAGE_SIZE as usize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum InventoryAvailability {
    /// Present in trusted configuration. No live OT probe is implied.
    Configured,
    Disabled,
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
            return Err(format!(
                "unsupported connector inventory schema {}",
                self.schema
            ));
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

    pub fn offset(&self) -> Result<usize, String> {
        self.cursor
            .as_deref()
            .map(|cursor| {
                cursor
                    .parse::<usize>()
                    .map_err(|_| "inventory cursor is out of range".to_string())
            })
            .transpose()
            .map(|offset| offset.unwrap_or(0))
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
                display_name,
                actions,
                ..
            } => {
                validate_id(device_id, "inventory device id")?;
                validate_display_name(display_name)?;
                validate_actions(actions)?;
            }
            Self::Group {
                group_id,
                device_id,
                display_name,
                actions,
                ..
            } => {
                validate_id(group_id, "inventory group id")?;
                validate_id(device_id, "inventory group device id")?;
                validate_display_name(display_name)?;
                validate_actions(actions)?;
            }
            Self::Point {
                point_id,
                device_id,
                group_id,
                display_name,
                units,
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
        if self.records.len() > usize::from(request.page_size)
            || self.records.len() > INVENTORY_MAX_RECORDS
        {
            return Err("connector inventory page exceeds its bound".into());
        }
        if let Some(cursor) = self.next_cursor.as_deref() {
            validate_cursor(cursor)?;
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
    if cursor.is_empty()
        || cursor.len() > INVENTORY_MAX_CURSOR_LENGTH
        || !cursor.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err("inventory cursor is malformed".into());
    }
    cursor
        .parse::<usize>()
        .map(|_| ())
        .map_err(|_| "inventory cursor is out of range".into())
}

fn validate_id(value: &str, field: &str) -> Result<(), String> {
    validate_token(value, 256, field)
}

fn validate_display_name(value: &str) -> Result<(), String> {
    let lower = value.to_ascii_lowercase();
    if value.trim().is_empty()
        || value.len() > 128
        || value.chars().any(|ch| ch.is_control())
        || value.contains("://")
        || value.contains('@')
        || lower.contains("password")
        || lower.contains("authorization")
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

fn validate_reference(reference: &InventoryPointReference) -> Result<(), String> {
    match reference {
        InventoryPointReference::Bacnet {
            object_type,
            property_id,
            ..
        } => {
            validate_token(object_type, 64, "BACnet object type")?;
            validate_token(property_id, 64, "BACnet property id")?;
        }
        InventoryPointReference::Modbus { function, .. } => {
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
    }
}
