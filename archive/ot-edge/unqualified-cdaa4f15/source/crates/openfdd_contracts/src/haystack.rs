//! Typed, bounded contracts for the configured Haystack connector.
//!
//! The public Haystack surface is deliberately keyed by a trusted catalog.
//! Callers never supply an URL, a Zinc filter, an upstream Haystack ref, an
//! authentication value, or a navigation path.  Those values stay inside the
//! connector's trusted configuration snapshot.

use std::collections::BTreeSet;

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::{ConnectorScope, Quality, ValueKind};

pub const HAYSTACK_CATALOG_CONTRACT_V1: &str = "openfdd.connector.haystack.catalog.v1";
pub const HAYSTACK_READ_CONTRACT_V1: &str = "openfdd.connector.haystack.read.v1";
pub const HAYSTACK_MAX_PAGE_SIZE: u16 = 100;
pub const HAYSTACK_MAX_HISTORY_POINTS: usize = 16;
pub const HAYSTACK_MAX_HISTORY_SAMPLES: usize = 5_000;
pub const HAYSTACK_MAX_RANGE_HOURS: i64 = 24;
pub const HAYSTACK_MAX_BODY_BYTES: usize = 1024 * 1024;
pub const HAYSTACK_MAX_CURSOR_LENGTH: usize = 96;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum HaystackRecordKind {
    Site,
    Building,
    Equipment,
    Point,
    Navigation,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
#[serde(rename_all = "snake_case")]
pub enum HaystackOperation {
    About,
    Catalog,
    Navigation,
    CurrentRead,
    HistoryRead,
}

/// Public catalog projection. The source ref and navigation ref are private
/// connector configuration and intentionally have no fields in this type.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackCatalogRecord {
    pub key: String,
    pub kind: HaystackRecordKind,
    pub display_name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub equipment_key: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackCatalogRequest {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    #[serde(default = "default_page_size")]
    pub page_size: u16,
    #[serde(default)]
    pub cursor: Option<String>,
}

fn default_page_size() -> u16 {
    HAYSTACK_MAX_PAGE_SIZE
}

impl HaystackCatalogRequest {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != HAYSTACK_CATALOG_CONTRACT_V1 {
            return Err("unsupported Haystack catalog schema".into());
        }
        self.scope.validate()?;
        if self.page_size == 0 || self.page_size > HAYSTACK_MAX_PAGE_SIZE {
            return Err(format!(
                "Haystack catalog page_size must be between 1 and {HAYSTACK_MAX_PAGE_SIZE}"
            ));
        }
        if let Some(cursor) = self.cursor.as_deref() {
            validate_cursor(cursor)?;
        }
        Ok(())
    }

    pub fn offset_for_revision(&self, revision: &str) -> Result<usize, String> {
        let Some(cursor) = self.cursor.as_deref() else {
            return Ok(0);
        };
        let pieces: Vec<_> = cursor.split('.').collect();
        if pieces.len() != 3 || pieces[0] != "v1" || pieces[1] != revision {
            return Err("Haystack catalog cursor is stale or malformed".into());
        }
        pieces[2]
            .parse::<usize>()
            .map_err(|_| "Haystack catalog cursor is out of range".into())
    }

    pub fn cursor_for_revision(&self, revision: &str, offset: usize) -> Result<String, String> {
        validate_token(revision, 128, "Haystack catalog revision")?;
        let cursor = format!("v1.{revision}.{offset}");
        validate_cursor(&cursor)?;
        Ok(cursor)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackCatalogResponse {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    /// Immutable revision of the connector's trusted catalog snapshot.
    pub revision: String,
    pub records: Vec<HaystackCatalogRecord>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub next_cursor: Option<String>,
}

impl HaystackCatalogResponse {
    pub fn validate_for(&self, request: &HaystackCatalogRequest) -> Result<(), String> {
        if self.schema != HAYSTACK_CATALOG_CONTRACT_V1
            || self.request_id != request.request_id
            || self.scope != request.scope
            || self.revision.trim().is_empty()
            || self.revision.len() > 128
            || self.records.len() > usize::from(request.page_size)
        {
            return Err("Haystack catalog response correlation or bounds failed".into());
        }
        let mut keys = BTreeSet::new();
        for record in &self.records {
            validate_public_key(&record.key, "Haystack catalog key")?;
            validate_display_name(&record.display_name)?;
            if !keys.insert(record.key.as_str()) {
                return Err("Haystack catalog contains duplicate keys".into());
            }
            if let Some(value) = record.equipment_key.as_deref() {
                validate_public_key(value, "Haystack equipment key")?;
            }
            if let Some(value) = record.role.as_deref() {
                validate_token(value, 96, "Haystack role")?;
            }
            if let Some(value) = record.unit.as_deref() {
                validate_token(value, 64, "Haystack unit")?;
            }
        }
        if let Some(cursor) = self.next_cursor.as_deref() {
            validate_cursor(cursor)?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackAboutRequest {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackAboutResponse {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    pub revision: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub vendor: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub product: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub product_version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timezone: Option<String>,
    pub operations: Vec<HaystackOperation>,
}

impl HaystackAboutRequest {
    pub fn validate(&self) -> Result<(), String> {
        validate_header(&self.schema, HAYSTACK_READ_CONTRACT_V1, &self.scope)
    }
}

impl HaystackAboutResponse {
    pub fn validate_for(&self, request: &HaystackAboutRequest) -> Result<(), String> {
        validate_header(&self.schema, HAYSTACK_READ_CONTRACT_V1, &self.scope)?;
        if self.request_id != request.request_id
            || self.scope != request.scope
            || self.revision.trim().is_empty()
        {
            return Err("Haystack about response correlation failed".into());
        }
        for value in [
            self.vendor.as_deref(),
            self.product.as_deref(),
            self.product_version.as_deref(),
            self.timezone.as_deref(),
        ]
        .into_iter()
        .flatten()
        {
            validate_token(value, 128, "Haystack about value")?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackNavRequest {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_key: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackNavResponse {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    pub revision: String,
    pub entries: Vec<HaystackCatalogRecord>,
}

impl HaystackNavRequest {
    pub fn validate(&self) -> Result<(), String> {
        validate_header(&self.schema, HAYSTACK_READ_CONTRACT_V1, &self.scope)?;
        if let Some(key) = self.parent_key.as_deref() {
            validate_public_key(key, "Haystack navigation key")?;
        }
        Ok(())
    }
}

impl HaystackNavResponse {
    pub fn validate_for(&self, request: &HaystackNavRequest) -> Result<(), String> {
        validate_header(&self.schema, HAYSTACK_READ_CONTRACT_V1, &self.scope)?;
        if self.request_id != request.request_id
            || self.scope != request.scope
            || self.revision.trim().is_empty()
        {
            return Err("Haystack navigation response correlation failed".into());
        }
        validate_catalog_records(&self.entries)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackValue {
    pub key: String,
    pub kind: ValueKind,
    #[cfg_attr(feature = "openapi", schema(value_type = Object))]
    pub value: serde_json::Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
    pub quality: Quality,
    /// A source timestamp. Missing source timestamps remain absent; the
    /// connector must never replace one with request or server time.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observed_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackCurrentReadRequest {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    #[serde(rename = "keys")]
    pub public_keys: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackCurrentReadResponse {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    pub revision: String,
    pub values: Vec<HaystackValue>,
}

impl HaystackCurrentReadRequest {
    pub fn validate(&self) -> Result<(), String> {
        validate_public_read_request(&self.schema, &self.scope, &self.public_keys, 100)
    }
}

impl HaystackCurrentReadResponse {
    pub fn validate_for(&self, request: &HaystackCurrentReadRequest) -> Result<(), String> {
        validate_header(&self.schema, HAYSTACK_READ_CONTRACT_V1, &self.scope)?;
        if self.request_id != request.request_id
            || self.scope != request.scope
            || self.revision.trim().is_empty()
        {
            return Err("Haystack current-read response correlation failed".into());
        }
        validate_values(&self.values, &request.public_keys)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackHistoryReadRequest {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    #[serde(rename = "keys")]
    pub public_keys: Vec<String>,
    #[serde(deserialize_with = "deserialize_explicit_utc")]
    pub start: DateTime<Utc>,
    #[serde(deserialize_with = "deserialize_explicit_utc")]
    pub end: DateTime<Utc>,
    #[serde(default = "default_history_sample_limit")]
    pub max_samples: usize,
}

fn default_history_sample_limit() -> usize {
    HAYSTACK_MAX_HISTORY_SAMPLES
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackHistorySeries {
    pub key: String,
    pub values: Vec<HaystackValue>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "openapi", derive(utoipa::ToSchema))]
pub struct HaystackHistoryReadResponse {
    pub schema: String,
    pub request_id: Uuid,
    pub scope: ConnectorScope,
    pub revision: String,
    pub series: Vec<HaystackHistorySeries>,
    pub sample_count: usize,
}

impl HaystackHistoryReadRequest {
    pub fn validate(&self) -> Result<(), String> {
        validate_public_read_request(
            &self.schema,
            &self.scope,
            &self.public_keys,
            HAYSTACK_MAX_HISTORY_POINTS,
        )?;
        if self.start >= self.end {
            return Err("Haystack history start must be before end".into());
        }
        if self.end - self.start > Duration::hours(HAYSTACK_MAX_RANGE_HOURS) {
            return Err("Haystack history range must be at most 24 hours".into());
        }
        if self.max_samples == 0 || self.max_samples > HAYSTACK_MAX_HISTORY_SAMPLES {
            return Err(format!(
                "Haystack history max_samples must be between 1 and {HAYSTACK_MAX_HISTORY_SAMPLES}"
            ));
        }
        Ok(())
    }
}

impl HaystackHistoryReadResponse {
    pub fn validate_for(&self, request: &HaystackHistoryReadRequest) -> Result<(), String> {
        validate_header(&self.schema, HAYSTACK_READ_CONTRACT_V1, &self.scope)?;
        if self.request_id != request.request_id
            || self.scope != request.scope
            || self.revision.trim().is_empty()
        {
            return Err("Haystack history response correlation failed".into());
        }
        if self.sample_count > request.max_samples {
            return Err("Haystack history response exceeds sample bound".into());
        }
        let mut keys = BTreeSet::new();
        let mut observed_count = 0usize;
        for series in &self.series {
            if !request.public_keys.iter().any(|key| key == &series.key)
                || !keys.insert(series.key.as_str())
            {
                return Err(
                    "Haystack history response contains an unknown or duplicate key".into(),
                );
            }
            for value in &series.values {
                if value.key != series.key {
                    return Err("Haystack history value key does not match its series".into());
                }
                if value.observed_at.is_none() {
                    return Err("Haystack history values require source observed_at".into());
                }
                if !safe_scalar(&value.value, value.kind) {
                    return Err("Haystack history value is not a typed scalar".into());
                }
                if let Some(unit) = value.unit.as_deref() {
                    validate_token(unit, 64, "Haystack history value unit")?;
                }
                let observed_at = value.observed_at.ok_or_else(|| {
                    "Haystack history values require source observed_at".to_string()
                })?;
                if observed_at < request.start || observed_at >= request.end {
                    return Err(
                        "Haystack history value is outside the requested time window".into(),
                    );
                }
                observed_count = observed_count
                    .checked_add(1)
                    .ok_or_else(|| "Haystack history sample count overflowed".to_string())?;
            }
        }
        if observed_count != self.sample_count {
            return Err("Haystack history sample_count does not match the response rows".into());
        }
        Ok(())
    }
}

fn validate_header(
    schema: &str,
    expected_schema: &str,
    scope: &ConnectorScope,
) -> Result<(), String> {
    if schema != expected_schema {
        return Err("unsupported Haystack read schema".into());
    }
    scope.validate()
}

fn validate_public_read_request(
    schema: &str,
    scope: &ConnectorScope,
    keys: &[String],
    max_keys: usize,
) -> Result<(), String> {
    validate_header(schema, HAYSTACK_READ_CONTRACT_V1, scope)?;
    if keys.is_empty() || keys.len() > max_keys {
        return Err("Haystack public key count is outside its bound".into());
    }
    let mut unique = BTreeSet::new();
    for key in keys {
        validate_public_key(key, "Haystack public key")?;
        if !unique.insert(key.as_str()) {
            return Err("Haystack public keys must be unique".into());
        }
    }
    Ok(())
}

fn validate_values(values: &[HaystackValue], keys: &[String]) -> Result<(), String> {
    let mut seen = BTreeSet::new();
    for value in values {
        if !keys.iter().any(|key| key == &value.key) || !seen.insert(value.key.as_str()) {
            return Err(
                "Haystack current-read response contains an unknown or duplicate key".into(),
            );
        }
        validate_public_key(&value.key, "Haystack value key")?;
        if let Some(unit) = value.unit.as_deref() {
            validate_token(unit, 64, "Haystack value unit")?;
        }
        if !safe_scalar(&value.value, value.kind) {
            return Err("Haystack value is not a typed scalar".into());
        }
    }
    Ok(())
}

fn safe_scalar(value: &serde_json::Value, kind: ValueKind) -> bool {
    match kind {
        ValueKind::Number => value.is_number(),
        ValueKind::Bool => value.is_boolean(),
        ValueKind::String => value.is_string(),
        ValueKind::Null => value.is_null(),
    }
}

fn validate_catalog_records(records: &[HaystackCatalogRecord]) -> Result<(), String> {
    let mut keys = BTreeSet::new();
    for record in records {
        validate_public_key(&record.key, "Haystack catalog key")?;
        validate_display_name(&record.display_name)?;
        if !keys.insert(record.key.as_str()) {
            return Err("Haystack catalog contains duplicate keys".into());
        }
    }
    Ok(())
}

fn validate_public_key(value: &str, label: &str) -> Result<(), String> {
    validate_token(value, 160, label)?;
    if value.contains("http")
        || value.contains("://")
        || value.contains('/')
        || value.contains('\\')
        || value.contains('"')
        || value.contains('\'')
        || value.contains(' ')
    {
        return Err(format!("{label} contains an unsafe path or URL token"));
    }
    Ok(())
}

fn deserialize_explicit_utc<'de, D>(deserializer: D) -> Result<DateTime<Utc>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let raw = String::deserialize(deserializer)?;
    let parsed = DateTime::parse_from_rfc3339(&raw).map_err(serde::de::Error::custom)?;
    if parsed.offset().local_minus_utc() != 0
        || !(raw.ends_with('Z') || raw.ends_with("+00:00") || raw.ends_with("-00:00"))
    {
        return Err(serde::de::Error::custom(
            "Haystack history timestamps must use an explicit UTC offset",
        ));
    }
    Ok(parsed.with_timezone(&Utc))
}

fn validate_display_name(value: &str) -> Result<(), String> {
    if value.trim().is_empty() || value.len() > 160 || value.chars().any(char::is_control) {
        return Err("Haystack display name is invalid".into());
    }
    Ok(())
}

fn validate_token(value: &str, max: usize, label: &str) -> Result<(), String> {
    if value.trim().is_empty() || value.len() > max || value.chars().any(char::is_control) {
        return Err(format!("{label} is invalid"));
    }
    Ok(())
}

fn validate_cursor(cursor: &str) -> Result<(), String> {
    if cursor.len() > HAYSTACK_MAX_CURSOR_LENGTH
        || cursor.is_empty()
        || cursor
            .chars()
            .any(|ch| !(ch.is_ascii_alphanumeric() || matches!(ch, '.' | '-')))
    {
        return Err("Haystack catalog cursor is malformed".into());
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

    #[test]
    fn history_requires_finite_utc_window_and_is_bounded() {
        let mut request = HaystackHistoryReadRequest {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: Uuid::nil(),
            scope: scope(),
            public_keys: (0..HAYSTACK_MAX_HISTORY_POINTS)
                .map(|idx| format!("point-{idx}"))
                .collect(),
            start: "2026-10-01T00:00:00Z".parse().unwrap(),
            end: "2026-10-01T23:59:59Z".parse().unwrap(),
            max_samples: HAYSTACK_MAX_HISTORY_SAMPLES,
        };
        request.validate().unwrap();
        request.end = request.start;
        assert!(request.validate().is_err());
        request.end = request.start + Duration::hours(25);
        assert!(request.validate().is_err());
    }

    #[test]
    fn public_requests_do_not_serialize_urls_or_raw_filters() {
        let request = HaystackCurrentReadRequest {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: Uuid::nil(),
            scope: scope(),
            public_keys: vec!["point-1".into()],
        };
        let json = serde_json::to_value(request).unwrap();
        assert!(json.get("url").is_none());
        assert!(json.get("filter").is_none());
        assert!(json.get("source_ref").is_none());
    }

    #[test]
    fn catalog_pages_are_limited_to_one_hundred() {
        let request = HaystackCatalogRequest {
            schema: HAYSTACK_CATALOG_CONTRACT_V1.into(),
            request_id: Uuid::nil(),
            scope: scope(),
            page_size: HAYSTACK_MAX_PAGE_SIZE + 1,
            cursor: None,
        };
        assert!(request.validate().is_err());
    }

    #[test]
    fn history_json_requires_explicit_utc_timestamps() {
        let value = serde_json::json!({
            "schema": HAYSTACK_READ_CONTRACT_V1,
            "request_id": Uuid::nil(),
            "scope": scope(),
            "keys": ["point-1"],
            "start": "2026-10-01T00:00:00+01:00",
            "end": "2026-10-01T01:00:00+01:00",
            "max_samples": 1
        });
        assert!(serde_json::from_value::<HaystackHistoryReadRequest>(value).is_err());
    }

    #[test]
    fn read_responses_reject_scope_mismatch_and_history_count_mismatch() {
        let request = HaystackCurrentReadRequest {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: Uuid::new_v4(),
            scope: scope(),
            public_keys: vec!["point-1".into()],
        };
        let mut current = HaystackCurrentReadResponse {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            revision: "catalog-v1".into(),
            values: Vec::new(),
        };
        current.scope.edge_id = "foreign-edge".into();
        assert!(current.validate_for(&request).is_err());

        let history_request = HaystackHistoryReadRequest {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: Uuid::new_v4(),
            scope: scope(),
            public_keys: vec!["point-1".into()],
            start: "2026-10-01T00:00:00Z".parse().unwrap(),
            end: "2026-10-01T01:00:00Z".parse().unwrap(),
            max_samples: 2,
        };
        let mut history = HaystackHistoryReadResponse {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: history_request.request_id,
            scope: history_request.scope.clone(),
            revision: "catalog-v1".into(),
            series: vec![HaystackHistorySeries {
                key: "point-1".into(),
                values: vec![HaystackValue {
                    key: "point-1".into(),
                    kind: ValueKind::Number,
                    value: serde_json::json!(1.0),
                    unit: Some("°F".into()),
                    quality: Quality::Good,
                    observed_at: Some("2026-10-01T00:30:00Z".parse().unwrap()),
                }],
            }],
            sample_count: 2,
        };
        assert!(history.validate_for(&history_request).is_err());
        history.sample_count = 1;
        history.series[0].values[0].observed_at = Some("2026-10-01T01:00:00Z".parse().unwrap());
        assert!(history.validate_for(&history_request).is_err());
    }
}
