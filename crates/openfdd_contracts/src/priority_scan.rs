//! Versioned, bounded priority-array scan and history contracts.
//!
//! The scheduled scan is deliberately a read-only observation.  It does not
//! discover devices, write values, release BACnet priorities, or perform
//! remediation.  Edge and central use the same DTOs so a cloud instance can
//! expose only history that an authenticated caller is already allowed to
//! read.

use std::collections::HashSet;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::proxy::{ConnectorReadResult, ConnectorScope, ReadPriorityArrayResult, ReadTarget};

pub const PRIORITY_SCAN_CONTRACT_V1: &str = "openfdd.connector.priority_scan.v1";
pub const PRIORITY_SCAN_CURSOR_VERSION: &str = "v1";
pub const PRIORITY_SCAN_MAX_PAGE_SIZE: u16 = 100;
pub const PRIORITY_SCAN_MAX_CURSOR_LENGTH: usize = 160;
pub const PRIORITY_SCAN_DEFAULT_INTERVAL_SECS: u64 = 3_600;
pub const PRIORITY_SCAN_MIN_INTERVAL_SECS: u64 = 300;
pub const PRIORITY_SCAN_MAX_INTERVAL_SECS: u64 = 7 * 24 * 3_600;
pub const PRIORITY_SCAN_DEFAULT_MAX_POINTS_PER_DEVICE: u16 = 100;
pub const PRIORITY_SCAN_MAX_POINTS_PER_DEVICE: u16 = 1_000;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct PriorityScanTarget {
    pub device_instance: u32,
    pub object_type: String,
    pub object_instance: u32,
}

impl PriorityScanTarget {
    pub fn validate(&self) -> Result<(), String> {
        if self.object_type.trim().is_empty()
            || self.object_type.len() > 64
            || !self
                .object_type
                .chars()
                .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.'))
        {
            return Err("priority scan target object_type is invalid".into());
        }
        Ok(())
    }

    /// Stable identity is independent of the configured display label.
    pub fn identity(&self) -> String {
        format!(
            "bacnet:{}:{}:{}",
            self.device_instance,
            self.object_type.to_ascii_lowercase(),
            self.object_instance
        )
    }

    pub fn read_target(&self) -> ReadTarget {
        ReadTarget::BacnetPriorityArray {
            device_instance: self.device_instance,
            object_type: self.object_type.clone(),
            object_instance: self.object_instance,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct PriorityScanConfig {
    /// The scheduler is opt-in.  A configured edge does not create OT reads
    /// unless this flag is explicitly enabled.
    pub enabled: bool,
    /// Delay between completed device scans.  There is no catch-up burst.
    pub interval_secs: u64,
    /// Maximum configured points read during one device visit.
    pub max_points_per_device: u16,
}

impl Default for PriorityScanConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            interval_secs: PRIORITY_SCAN_DEFAULT_INTERVAL_SECS,
            max_points_per_device: PRIORITY_SCAN_DEFAULT_MAX_POINTS_PER_DEVICE,
        }
    }
}

impl PriorityScanConfig {
    pub fn validate(&self) -> Result<(), String> {
        if !(PRIORITY_SCAN_MIN_INTERVAL_SECS..=PRIORITY_SCAN_MAX_INTERVAL_SECS)
            .contains(&self.interval_secs)
        {
            return Err(format!(
                "priority scan interval_secs must be between {} and {}",
                PRIORITY_SCAN_MIN_INTERVAL_SECS, PRIORITY_SCAN_MAX_INTERVAL_SECS
            ));
        }
        if self.max_points_per_device == 0
            || self.max_points_per_device > PRIORITY_SCAN_MAX_POINTS_PER_DEVICE
        {
            return Err(format!(
                "priority scan max_points_per_device must be between 1 and {}",
                PRIORITY_SCAN_MAX_POINTS_PER_DEVICE
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct PriorityScanStatus {
    pub schema: String,
    pub scope: ConnectorScope,
    pub enabled: bool,
    pub interval_secs: u64,
    pub max_points_per_device: u16,
    pub catch_up: bool,
    pub read_only: bool,
    pub discovery_enabled: bool,
    pub writes_enabled: bool,
    pub last_started_at: Option<DateTime<Utc>>,
    pub last_completed_at: Option<DateTime<Utc>>,
    pub next_due_at: Option<DateTime<Utc>>,
    pub last_device_identity: Option<String>,
    pub last_error: Option<String>,
    pub records_retained: u64,
}

impl PriorityScanStatus {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != PRIORITY_SCAN_CONTRACT_V1 {
            return Err("unsupported priority scan status schema".into());
        }
        self.scope.validate()?;
        let config = PriorityScanConfig {
            enabled: self.enabled,
            interval_secs: self.interval_secs,
            max_points_per_device: self.max_points_per_device,
        };
        config.validate()?;
        if self.catch_up || !self.read_only || self.discovery_enabled || self.writes_enabled {
            return Err("priority scheduler status advertises an unsafe mode".into());
        }
        if self
            .last_error
            .as_deref()
            .is_some_and(|value| value.len() > 256 || value.chars().any(|ch| ch.is_control()))
        {
            return Err("priority scheduler error is invalid".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct PriorityHistoryRecord {
    pub sequence: u64,
    pub target: PriorityScanTarget,
    pub snapshot: ReadPriorityArrayResult,
    /// Stable source label.  It intentionally does not contain a host, URL,
    /// MQTT topic, credential, or vendor detail.
    pub source: String,
}

impl PriorityHistoryRecord {
    pub fn validate(&self) -> Result<(), String> {
        if self.sequence == 0 || self.source != "scheduled_scan" {
            return Err("priority history record identity is invalid".into());
        }
        self.target.validate()?;
        ConnectorReadResult::PriorityArray(self.snapshot.clone())
            .validate_for_target(&self.target.read_target())
            .map_err(|_| "priority history snapshot does not match target".to_string())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct PriorityHistoryRequest {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    #[serde(default = "default_priority_history_page_size")]
    pub page_size: u16,
    #[serde(default)]
    pub cursor: Option<String>,
    /// Optional exact target filter.  The server still applies scope and
    /// inventory authorization before returning a matching record.
    #[serde(default)]
    pub target: Option<PriorityScanTarget>,
}

fn default_priority_history_page_size() -> u16 {
    PRIORITY_SCAN_MAX_PAGE_SIZE
}

impl PriorityHistoryRequest {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != PRIORITY_SCAN_CONTRACT_V1 {
            return Err("unsupported priority history schema".into());
        }
        self.scope.validate()?;
        if self.page_size == 0 || self.page_size > PRIORITY_SCAN_MAX_PAGE_SIZE {
            return Err(format!(
                "priority history page_size must be between 1 and {}",
                PRIORITY_SCAN_MAX_PAGE_SIZE
            ));
        }
        if let Some(target) = &self.target {
            target.validate()?;
        }
        if let Some(cursor) = self.cursor.as_deref() {
            validate_cursor(cursor)?;
        }
        Ok(())
    }

    pub fn offset_for_revision(&self, revision: &str) -> Result<usize, String> {
        self.cursor
            .as_deref()
            .map(|cursor| decode_cursor(self, cursor, revision))
            .transpose()
            .map(|offset| offset.unwrap_or(0))
    }

    pub fn cursor_for_revision(&self, revision: &str, offset: usize) -> Result<String, String> {
        if revision.is_empty()
            || revision.len() > 128
            || !revision
                .chars()
                .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.'))
        {
            return Err("priority history revision is invalid".into());
        }
        let cursor = format!(
            "{PRIORITY_SCAN_CURSOR_VERSION}.{}.{}.{}",
            revision,
            cursor_binding(self),
            offset
        );
        validate_cursor(&cursor)?;
        Ok(cursor)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct PriorityHistoryResponse {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    pub revision: String,
    pub captured_at: DateTime<Utc>,
    pub records: Vec<PriorityHistoryRecord>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub next_cursor: Option<String>,
    pub scanner: PriorityScanStatus,
}

impl PriorityHistoryResponse {
    pub fn validate_for(&self, request: &PriorityHistoryRequest) -> Result<(), String> {
        request.validate()?;
        if self.schema != PRIORITY_SCAN_CONTRACT_V1
            || self.request_id != request.request_id
            || self.scope != request.scope
        {
            return Err("priority history response correlation failed".into());
        }
        if self.records.len() > usize::from(request.page_size) {
            return Err("priority history page exceeds its bound".into());
        }
        self.scanner.validate()?;
        let offset = request.offset_for_revision(&self.revision)?;
        if let Some(cursor) = self.next_cursor.as_deref() {
            let next_offset = decode_cursor(request, cursor, &self.revision)?;
            if self.records.is_empty() || next_offset != offset.saturating_add(self.records.len()) {
                return Err("priority history continuation cursor is invalid".into());
            }
        }
        let mut sequences = HashSet::new();
        for record in &self.records {
            record.validate()?;
            if !sequences.insert(record.sequence) {
                return Err("priority history contains duplicate sequence values".into());
            }
            if request
                .target
                .as_ref()
                .is_some_and(|target| target != &record.target)
            {
                return Err("priority history record is outside requested target".into());
            }
        }
        Ok(())
    }
}

fn validate_cursor(cursor: &str) -> Result<(), String> {
    if cursor.is_empty() || cursor.len() > PRIORITY_SCAN_MAX_CURSOR_LENGTH {
        return Err("priority history cursor is malformed".into());
    }
    let parts: Vec<_> = cursor.split('.').collect();
    if parts.len() != 4
        || parts[0] != PRIORITY_SCAN_CURSOR_VERSION
        || parts[2].len() != 16
        || !parts[2].bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        return Err("priority history cursor is malformed".into());
    }
    if parts[1].is_empty()
        || parts[1].len() > 128
        || !parts[1]
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.'))
    {
        return Err("priority history cursor revision is malformed".into());
    }
    parts[3]
        .parse::<usize>()
        .map(|_| ())
        .map_err(|_| "priority history cursor offset is malformed".into())
}

fn decode_cursor(
    request: &PriorityHistoryRequest,
    cursor: &str,
    revision: &str,
) -> Result<usize, String> {
    validate_cursor(cursor)?;
    let parts: Vec<_> = cursor.split('.').collect();
    if parts[1] != revision {
        return Err("priority history cursor is stale for this revision".into());
    }
    if parts[2] != cursor_binding(request) {
        return Err("priority history cursor is outside this scope or query".into());
    }
    parts[3]
        .parse::<usize>()
        .map_err(|_| "priority history cursor offset is malformed".into())
}

fn cursor_binding(request: &PriorityHistoryRequest) -> String {
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
    if let Some(target) = &request.target {
        feed(&mut hash, target.identity().as_bytes());
    }
    format!("{hash:016x}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::proxy::{ReadPrioritySlot, ReadValueState, READ_PROXY_CONTRACT_V1};

    fn scope() -> ConnectorScope {
        ConnectorScope {
            tenant_id: "tenant".into(),
            building_id: "building".into(),
            edge_id: "edge".into(),
        }
    }

    fn target() -> PriorityScanTarget {
        PriorityScanTarget {
            device_instance: 7,
            object_type: "analog-output".into(),
            object_instance: 4,
        }
    }

    fn snapshot() -> ReadPriorityArrayResult {
        ReadPriorityArrayResult {
            device_instance: 7,
            object_type: "analog-output".into(),
            object_instance: 4,
            slots: (1..=16)
                .map(|priority_level| ReadPrioritySlot {
                    priority_level,
                    state: ReadValueState::Null,
                    value_type: "null".into(),
                    value: None,
                    error: None,
                })
                .collect(),
            state: "supported".into(),
            observed_at: Utc::now(),
        }
    }

    fn request() -> PriorityHistoryRequest {
        PriorityHistoryRequest {
            schema: PRIORITY_SCAN_CONTRACT_V1.into(),
            request_id: Uuid::nil(),
            scope: scope(),
            page_size: 2,
            cursor: None,
            target: None,
        }
    }

    fn status() -> PriorityScanStatus {
        PriorityScanStatus {
            schema: PRIORITY_SCAN_CONTRACT_V1.into(),
            scope: scope(),
            enabled: false,
            interval_secs: PRIORITY_SCAN_DEFAULT_INTERVAL_SECS,
            max_points_per_device: PRIORITY_SCAN_DEFAULT_MAX_POINTS_PER_DEVICE,
            catch_up: false,
            read_only: true,
            discovery_enabled: false,
            writes_enabled: false,
            last_started_at: None,
            last_completed_at: None,
            next_due_at: None,
            last_device_identity: None,
            last_error: None,
            records_retained: 0,
        }
    }

    #[test]
    fn scheduler_defaults_to_disabled_bounded_read_only_mode() {
        let config = PriorityScanConfig::default();
        assert!(!config.enabled);
        assert_eq!(config.interval_secs, 3_600);
        assert!(config.validate().is_ok());
    }

    #[test]
    fn interval_cannot_create_a_fast_scan() {
        let mut config = PriorityScanConfig::default();
        config.interval_secs = PRIORITY_SCAN_MIN_INTERVAL_SECS - 1;
        assert!(config.validate().is_err());
    }

    #[test]
    fn history_response_requires_exact_sixteen_slot_snapshot_and_cursor_binding() {
        let request = request();
        let record = PriorityHistoryRecord {
            sequence: 1,
            target: target(),
            snapshot: snapshot(),
            source: "scheduled_scan".into(),
        };
        let mut response = PriorityHistoryResponse {
            schema: PRIORITY_SCAN_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            revision: "history-1".into(),
            captured_at: Utc::now(),
            records: vec![record],
            next_cursor: None,
            scanner: status(),
        };
        response.validate_for(&request).unwrap();
        response.records[0].snapshot.slots.pop();
        assert!(response.validate_for(&request).is_err());
    }

    #[test]
    fn cursor_cannot_cross_target_filter_or_scope() {
        let request = request();
        let cursor = request.cursor_for_revision("history-1", 2).unwrap();
        let mut continued = request.clone();
        continued.cursor = Some(cursor.clone());
        assert_eq!(continued.offset_for_revision("history-1").unwrap(), 2);

        let mut foreign = request.clone();
        foreign.scope.edge_id = "other-edge".into();
        foreign.cursor = Some(cursor);
        assert!(foreign.offset_for_revision("history-1").is_err());
    }

    #[test]
    fn history_record_is_target_correlated() {
        let mut value = snapshot();
        value.object_instance = 99;
        let record = PriorityHistoryRecord {
            sequence: 1,
            target: target(),
            snapshot: value,
            source: "scheduled_scan".into(),
        };
        assert!(record.validate().is_err());
    }

    #[test]
    fn scan_contract_does_not_accidentally_reuse_read_schema() {
        assert_ne!(PRIORITY_SCAN_CONTRACT_V1, READ_PROXY_CONTRACT_V1);
    }
}
