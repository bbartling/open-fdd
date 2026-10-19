//! Bounded, read-only Haystack HTTP connector.
//!
//! The connector owns the upstream URL, authentication, operation paths, and
//! private refs. Callers address only keys from the trusted catalog. Both
//! Basic and SCRAM use the same bounded reqwest client; the SCRAM handshake is
//! implemented here so the bounds also apply before a bearer token exists.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use chrono::{DateTime, Utc};
use futures_util::StreamExt;
use haystack_core::codecs::zinc;
use haystack_core::data::HGrid;
use haystack_core::kinds::{HDateTime, HRef, Kind};
use openfdd_contracts::{
    HaystackAboutRequest, HaystackAboutResponse, HaystackCatalogRecord, HaystackCatalogRequest,
    HaystackCatalogResponse, HaystackCurrentReadRequest, HaystackCurrentReadResponse,
    HaystackHistoryReadRequest, HaystackHistoryReadResponse, HaystackHistorySeries,
    HaystackNavRequest, HaystackNavResponse, HaystackOperation, HaystackValue, Protocol, Quality,
    TelemetryEnvelope, TelemetryPoint, ValueKind, HAYSTACK_CATALOG_CONTRACT_V1,
    HAYSTACK_MAX_BODY_BYTES, HAYSTACK_READ_CONTRACT_V1,
};
use reqwest::redirect::Policy;
use reqwest::{Client, Response, StatusCode, Url};
use serde_json::{json, Value};
use subtle::ConstantTimeEq;
use tokio::sync::Mutex;

use crate::config::{
    load_haystack_catalog, HaystackAuthMode, HaystackCatalog, HaystackCatalogEntry,
    HaystackSettings,
};

const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
const READ_ONLY_OPS: &[&str] = &["about", "read", "nav", "hisRead"];

#[derive(Debug)]
pub struct HaystackNotAllowedError(pub String);

impl std::fmt::Display for HaystackNotAllowedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for HaystackNotAllowedError {}

#[derive(Clone)]
struct BoundedHaystackHttp {
    http: Client,
    base_url: Url,
    username: String,
    password: String,
    auth_mode: HaystackAuthMode,
    auth_token: Arc<Mutex<Option<String>>>,
}

impl BoundedHaystackHttp {
    fn new(settings: &HaystackSettings) -> Result<Self, String> {
        let base_url = validate_base_url(&settings.base_url)?;
        if settings.username.trim().is_empty() || settings.password.is_empty() {
            return Err("Haystack credentials are required explicitly".into());
        }
        let http = Client::builder()
            .redirect(Policy::none())
            .connect_timeout(CONNECT_TIMEOUT)
            .timeout(REQUEST_TIMEOUT)
            .danger_accept_invalid_certs(!settings.tls_verify)
            .build()
            .map_err(|_| "Haystack bounded HTTP client could not be initialized".to_string())?;
        Ok(Self {
            http,
            base_url,
            username: settings.username.clone(),
            password: settings.password.clone(),
            auth_mode: settings.auth_mode,
            auth_token: Arc::new(Mutex::new(None)),
        })
    }

    async fn request_grid(
        &self,
        op: &'static str,
        query: &[(&str, String)],
    ) -> Result<HGrid, String> {
        if !READ_ONLY_OPS.contains(&op) {
            return Err(HaystackNotAllowedError(format!(
                "Haystack operation '{op}' is not allowlisted"
            ))
            .to_string());
        }
        let endpoint = self
            .base_url
            .join(op)
            .map_err(|_| "Haystack operation path is invalid".to_string())?;
        let mut request = self
            .http
            .get(endpoint)
            .header("Accept", "text/zinc")
            .query(query);
        match self.auth_mode {
            HaystackAuthMode::Basic => {
                request = request.basic_auth(&self.username, Some(&self.password));
            }
            HaystackAuthMode::Scram => {
                let token = self.ensure_scram_token().await?;
                request = request.header("Authorization", format!("BEARER authToken={token}"));
            }
        }
        let response = request
            .send()
            .await
            .map_err(|_| "Haystack upstream request failed".to_string())?;
        decode_response(response).await
    }

    async fn ensure_scram_token(&self) -> Result<String, String> {
        if let Some(token) = self.auth_token.lock().await.clone() {
            return Ok(token);
        }
        let token = self.scram_authenticate().await?;
        let mut guard = self.auth_token.lock().await;
        if guard.is_none() {
            *guard = Some(token.clone());
        }
        Ok(guard.clone().unwrap_or(token))
    }

    async fn scram_authenticate(&self) -> Result<String, String> {
        let endpoint = self
            .base_url
            .join("about")
            .map_err(|_| "Haystack operation path is invalid".to_string())?;
        let (client_nonce, client_first) =
            haystack_core::auth::client_first_message(&self.username);
        let hello_header = format!(
            "HELLO username={}, data={}",
            BASE64.encode(self.username.as_bytes()),
            client_first
        );
        let hello = self
            .http
            .get(endpoint.clone())
            .header("Authorization", hello_header)
            .send()
            .await
            .map_err(|_| "Haystack SCRAM authentication failed".to_string())?;
        if hello.status() != StatusCode::UNAUTHORIZED {
            return Err("Haystack SCRAM authentication failed".into());
        }
        let challenge = hello
            .headers()
            .get("www-authenticate")
            .and_then(|value| value.to_str().ok())
            .map(str::to_string)
            .ok_or_else(|| "Haystack SCRAM authentication failed".to_string())?;
        let _ = bounded_response_bytes(hello).await?;
        let (handshake_token, server_first) = parse_scram_challenge(&challenge)?;
        let (client_final, expected_signature) = haystack_core::auth::client_final_message(
            &self.password,
            &client_nonce,
            &server_first,
            &self.username,
        )
        .map_err(|_| "Haystack SCRAM authentication failed".to_string())?;
        let scram_header = format!(
            "SCRAM handshakeToken={}, data={}",
            handshake_token, client_final
        );
        let response = self
            .http
            .get(endpoint)
            .header("Authorization", scram_header)
            .send()
            .await
            .map_err(|_| "Haystack SCRAM authentication failed".to_string())?;
        if !response.status().is_success() || response.status().is_redirection() {
            return Err("Haystack SCRAM authentication failed".into());
        }
        let authentication_info = response
            .headers()
            .get("authentication-info")
            .and_then(|value| value.to_str().ok())
            .map(str::to_string)
            .ok_or_else(|| "Haystack SCRAM authentication failed".to_string())?;
        let _ = bounded_response_bytes(response).await?;
        let (token, server_final) = parse_authentication_info(&authentication_info)?;
        let server_final_bytes = BASE64
            .decode(server_final)
            .map_err(|_| "Haystack SCRAM authentication failed".to_string())?;
        let server_final = std::str::from_utf8(&server_final_bytes)
            .map_err(|_| "Haystack SCRAM authentication failed".to_string())?;
        let server_signature = server_final
            .strip_prefix("v=")
            .ok_or_else(|| "Haystack SCRAM authentication failed".to_string())?;
        let server_signature = BASE64
            .decode(server_signature)
            .map_err(|_| "Haystack SCRAM authentication failed".to_string())?;
        if server_signature
            .as_slice()
            .ct_eq(&expected_signature)
            .unwrap_u8()
            != 1
        {
            return Err("Haystack SCRAM authentication failed".into());
        }
        if token.trim().is_empty() || token.len() > 512 {
            return Err("Haystack SCRAM authentication failed".into());
        }
        Ok(token)
    }

    async fn about(&self) -> Result<HGrid, String> {
        self.request_grid("about", &[]).await
    }

    async fn read_refs(&self, refs: &[String]) -> Result<HGrid, String> {
        let filter = refs
            .iter()
            .map(|source_ref| ref_literal(source_ref))
            .collect::<Result<Vec<_>, _>>()?
            .into_iter()
            .map(|reference| format!("id == {reference}"))
            .collect::<Vec<_>>()
            .join(" or ");
        self.request_grid("read", &[("filter", filter)]).await
    }

    async fn nav_ref(&self, source_ref: Option<&str>) -> Result<HGrid, String> {
        let query = source_ref
            .map(|value| ref_literal(value).map(|value| vec![("navId", value)]))
            .transpose()?
            .unwrap_or_default();
        self.request_grid("nav", &query).await
    }

    async fn his_ref(
        &self,
        source_ref: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    ) -> Result<HGrid, String> {
        let source_ref = ref_literal(source_ref)?;
        self.request_grid(
            "hisRead",
            &[
                ("id", source_ref),
                (
                    "range",
                    format!("{},{}", start.to_rfc3339(), end.to_rfc3339()),
                ),
            ],
        )
        .await
    }
}

fn ref_literal(source_ref: &str) -> Result<String, String> {
    let reference = HRef::from_val(source_ref);
    if !reference.is_valid() {
        return Err("Haystack trusted source ref is invalid".to_string());
    }
    Ok(reference.to_string())
}

async fn decode_response(response: Response) -> Result<HGrid, String> {
    if response.status().is_redirection() {
        return Err("Haystack redirects are not accepted".into());
    }
    if !response.status().is_success() {
        return Err("Haystack upstream returned an error".into());
    }
    let bytes = bounded_response_bytes(response).await?;
    let text =
        std::str::from_utf8(&bytes).map_err(|_| "Haystack response is not Zinc".to_string())?;
    zinc::decode_grid(text).map_err(|_| "Haystack response could not be decoded".to_string())
}

async fn bounded_response_bytes(response: Response) -> Result<Vec<u8>, String> {
    if response
        .content_length()
        .is_some_and(|length| length > HAYSTACK_MAX_BODY_BYTES as u64)
    {
        return Err("Haystack upstream response exceeds 1 MiB".into());
    }
    let mut stream = response.bytes_stream();
    let mut bytes = Vec::new();
    while let Some(chunk) = stream.next().await {
        let chunk =
            chunk.map_err(|_| "Haystack upstream response could not be read".to_string())?;
        if bytes.len().saturating_add(chunk.len()) > HAYSTACK_MAX_BODY_BYTES {
            return Err("Haystack upstream response exceeds 1 MiB".into());
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

fn validate_base_url(raw: &str) -> Result<Url, String> {
    let mut url = Url::parse(raw).map_err(|_| "Haystack base URL is invalid".to_string())?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("Haystack base URL must be a credential-free HTTP(S) origin".into());
    }
    if !url.path().ends_with('/') {
        let path = format!("{}/", url.path());
        url.set_path(&path);
    }
    Ok(url)
}

fn parse_scram_challenge(header: &str) -> Result<(String, String), String> {
    let rest = header
        .trim()
        .strip_prefix("SCRAM ")
        .ok_or_else(|| "Haystack SCRAM authentication failed".to_string())?;
    let mut handshake_token = None;
    let mut data = None;
    for part in rest.split(',') {
        let part = part.trim();
        if let Some(value) = part.strip_prefix("handshakeToken=") {
            handshake_token = Some(value.trim().to_string());
        } else if let Some(value) = part.strip_prefix("data=") {
            data = Some(value.trim().to_string());
        }
    }
    match (handshake_token, data) {
        (Some(token), Some(data))
            if !token.is_empty()
                && !data.is_empty()
                && token.len() <= 512
                && data.len() <= 8192 =>
        {
            Ok((token, data))
        }
        _ => Err("Haystack SCRAM authentication failed".into()),
    }
}

fn parse_authentication_info(header: &str) -> Result<(String, String), String> {
    let mut token = None;
    let mut data = None;
    for part in header.split(',') {
        let part = part.trim();
        if let Some(value) = part.strip_prefix("authToken=") {
            token = Some(value.trim().to_string());
        } else if let Some(value) = part.strip_prefix("data=") {
            data = Some(value.trim().to_string());
        }
    }
    match (token, data) {
        (Some(token), Some(data))
            if !token.is_empty()
                && token.len() <= 512
                && !data.is_empty()
                && data.len() <= 8192 =>
        {
            Ok((token, data))
        }
        _ => Err("Haystack SCRAM authentication failed".into()),
    }
}

pub struct HaystackService {
    settings: HaystackSettings,
    catalog: HaystackCatalog,
    client: Arc<Mutex<Option<BoundedHaystackHttp>>>,
}

impl HaystackService {
    pub fn new(settings: HaystackSettings) -> Self {
        let catalog =
            load_haystack_catalog(settings.catalog_path.as_deref()).unwrap_or_else(|_| {
                HaystackCatalog {
                    revision: "catalog-invalid".into(),
                    entries: Vec::new(),
                }
            });
        let service = Self::with_catalog(settings, catalog);
        let _ = service.has_trusted_catalog();
        service
    }

    pub fn with_catalog(settings: HaystackSettings, catalog: HaystackCatalog) -> Self {
        Self {
            settings,
            catalog,
            client: Arc::new(Mutex::new(None)),
        }
    }

    pub fn has_trusted_catalog(&self) -> bool {
        !self.catalog.entries.is_empty() && self.catalog.revision != "catalog-invalid"
    }

    pub async fn close(&self) {
        self.client.lock().await.take();
    }

    fn check_op(&self, op: &str) -> Result<(), HaystackNotAllowedError> {
        if READ_ONLY_OPS.contains(&op) {
            Ok(())
        } else {
            Err(HaystackNotAllowedError(format!(
                "Haystack operation '{op}' is not allowlisted"
            )))
        }
    }

    async fn http(&self) -> Result<BoundedHaystackHttp, String> {
        let mut guard = self.client.lock().await;
        if guard.is_none() {
            *guard = Some(BoundedHaystackHttp::new(&self.settings)?);
        }
        guard
            .as_ref()
            .cloned()
            .ok_or_else(|| "Haystack bounded HTTP client unavailable".into())
    }

    pub async fn about_typed(
        &self,
        request: &HaystackAboutRequest,
    ) -> Result<HaystackAboutResponse, String> {
        request.validate()?;
        self.check_op("about").map_err(|error| error.to_string())?;
        let grid = self.http().await?.about().await?;
        let fields = first_row(&grid);
        let response = HaystackAboutResponse {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            revision: self.catalog.revision.clone(),
            vendor: text_field(fields, &["vendorName", "vendor"]),
            product: text_field(fields, &["productName", "product"]),
            product_version: text_field(fields, &["productVersion", "version"]),
            timezone: text_field(fields, &["tz", "timezone"]),
            operations: vec![
                HaystackOperation::About,
                HaystackOperation::Catalog,
                HaystackOperation::Navigation,
                HaystackOperation::CurrentRead,
                HaystackOperation::HistoryRead,
            ],
        };
        response.validate_for(request)?;
        Ok(response)
    }

    pub fn catalog_page(
        &self,
        request: &HaystackCatalogRequest,
    ) -> Result<HaystackCatalogResponse, String> {
        request.validate()?;
        let offset = request.offset_for_revision(&self.catalog.revision)?;
        if offset > self.catalog.entries.len() {
            return Err("Haystack catalog cursor is stale".into());
        }
        let end = offset
            .saturating_add(usize::from(request.page_size))
            .min(self.catalog.entries.len());
        let records = self.catalog.entries[offset..end]
            .iter()
            .map(public_catalog_record)
            .collect::<Vec<_>>();
        let response = HaystackCatalogResponse {
            schema: HAYSTACK_CATALOG_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            revision: self.catalog.revision.clone(),
            records,
            next_cursor: (end < self.catalog.entries.len())
                .then(|| request.cursor_for_revision(&self.catalog.revision, end))
                .transpose()?,
        };
        response.validate_for(request)?;
        Ok(response)
    }

    pub async fn nav_typed(
        &self,
        request: &HaystackNavRequest,
    ) -> Result<HaystackNavResponse, String> {
        request.validate()?;
        self.check_op("nav").map_err(|error| error.to_string())?;
        let nav_ref = request
            .parent_key
            .as_deref()
            .and_then(|key| {
                self.catalog
                    .entries
                    .iter()
                    .find(|entry| entry.public_key == key)
            })
            .and_then(|entry| entry.nav_ref.as_deref());
        if request.parent_key.is_some() && nav_ref.is_none() {
            return Err("Haystack navigation key is not in the trusted catalog".into());
        }
        let grid = self.http().await?.nav_ref(nav_ref).await?;
        let mut records = Vec::new();
        for row in grid.iter() {
            let Some(source_ref) = row_string(row, &["id", "ref"]) else {
                continue;
            };
            if let Some(entry) = self
                .catalog
                .entries
                .iter()
                .find(|entry| entry.source_ref == source_ref)
            {
                records.push(public_catalog_record(entry));
            }
        }
        if records.is_empty() && request.parent_key.is_none() {
            records = self
                .catalog
                .entries
                .iter()
                .map(public_catalog_record)
                .collect();
        }
        let response = HaystackNavResponse {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            revision: self.catalog.revision.clone(),
            entries: records,
        };
        response.validate_for(request)?;
        Ok(response)
    }

    pub async fn current_read_typed(
        &self,
        request: &HaystackCurrentReadRequest,
    ) -> Result<HaystackCurrentReadResponse, String> {
        request.validate()?;
        self.check_op("read").map_err(|error| error.to_string())?;
        let entries = self.map_keys(&request.public_keys)?;
        let refs = entries
            .iter()
            .map(|entry| entry.source_ref.clone())
            .collect::<Vec<_>>();
        let grid = self.http().await?.read_refs(&refs).await?;
        let values = normalize_current_rows(&grid, &entries)?;
        let response = HaystackCurrentReadResponse {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            revision: self.catalog.revision.clone(),
            values,
        };
        response.validate_for(request)?;
        Ok(response)
    }

    /// Convert one bounded typed current read into the canonical envelope used
    /// by the authenticated local sink. This is deliberately an explicit
    /// caller action; the Haystack process never starts a polling loop.
    pub fn telemetry_envelope_from_current(
        &self,
        request: &HaystackCurrentReadRequest,
        response: &HaystackCurrentReadResponse,
        sequence: u64,
    ) -> Result<TelemetryEnvelope, String> {
        response.validate_for(request)?;
        let mut points = Vec::with_capacity(response.values.len());
        for value in &response.values {
            let entry = self
                .catalog
                .entries
                .iter()
                .find(|entry| entry.public_key == value.key)
                .ok_or_else(|| "Haystack response key is not in the trusted catalog".to_string())?;
            let equipment_id = entry
                .equipment_key
                .as_deref()
                .filter(|value| !value.trim().is_empty())
                .ok_or_else(|| "Haystack catalog point has no equipment mapping".to_string())?;
            let role = entry
                .role
                .as_deref()
                .filter(|value| !value.trim().is_empty())
                .ok_or_else(|| "Haystack catalog point has no role mapping".to_string())?;
            let mut tags = serde_json::Map::new();
            tags.insert(
                "building_id".into(),
                serde_json::Value::String(request.scope.building_id.clone()),
            );
            tags.insert(
                "equipment_id".into(),
                serde_json::Value::String(equipment_id.to_string()),
            );
            tags.insert("role".into(), serde_json::Value::String(role.to_string()));
            points.push(TelemetryPoint {
                id: value.key.clone(),
                display_name: Some(entry.display_name.clone()),
                kind: Some(value.kind),
                value: value.value.clone(),
                unit: value.unit.clone(),
                quality: value.quality,
                observed_at: value.observed_at,
                tags,
            });
        }
        let mut envelope = TelemetryEnvelope::new(
            request.scope.building_id.clone(),
            request.scope.edge_id.clone(),
            Protocol::Haystack,
            sequence,
            points,
        );
        // The caller's operation UUID is also the durable delivery identity.
        // Retrying the same bounded operation therefore cannot mint a second
        // telemetry message after an uncertain Central response.
        envelope.message_id = request.request_id;
        envelope.validate()?;
        Ok(envelope)
    }

    pub async fn history_read_typed(
        &self,
        request: &HaystackHistoryReadRequest,
    ) -> Result<HaystackHistoryReadResponse, String> {
        request.validate()?;
        self.check_op("hisRead")
            .map_err(|error| error.to_string())?;
        let entries = self.map_keys(&request.public_keys)?;
        let http = self.http().await?;
        let mut series = Vec::new();
        let mut sample_count = 0usize;
        for entry in entries {
            let grid = http
                .his_ref(&entry.source_ref, request.start, request.end)
                .await?;
            let values = normalize_history_rows(&grid, entry, request.start, request.end)?;
            sample_count = sample_count.saturating_add(values.len());
            if sample_count > request.max_samples {
                return Err("Haystack upstream history exceeds the requested sample bound".into());
            }
            series.push(HaystackHistorySeries {
                key: entry.public_key.clone(),
                values,
            });
        }
        let response = HaystackHistoryReadResponse {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            revision: self.catalog.revision.clone(),
            series,
            sample_count,
        };
        response.validate_for(request)?;
        Ok(response)
    }

    fn map_keys<'a>(&'a self, keys: &[String]) -> Result<Vec<&'a HaystackCatalogEntry>, String> {
        keys.iter()
            .map(|key| {
                self.catalog
                    .entries
                    .iter()
                    .find(|entry| {
                        entry.public_key == *key
                            && entry.kind == openfdd_contracts::HaystackRecordKind::Point
                    })
                    .ok_or_else(|| "Haystack key is not in the trusted catalog".to_string())
            })
            .collect()
    }
}

fn public_catalog_record(entry: &HaystackCatalogEntry) -> HaystackCatalogRecord {
    HaystackCatalogRecord {
        key: entry.public_key.clone(),
        kind: entry.kind,
        display_name: entry.display_name.clone(),
        equipment_key: entry.equipment_key.clone(),
        role: entry.role.clone(),
        unit: entry.unit.clone(),
    }
}

fn first_row(grid: &HGrid) -> Option<&haystack_core::data::HDict> {
    grid.iter().next()
}

fn text_field(row: Option<&haystack_core::data::HDict>, names: &[&str]) -> Option<String> {
    row.and_then(|row| {
        names
            .iter()
            .find_map(|name| row.get(name).and_then(kind_to_text))
    })
}

fn row_string(row: &haystack_core::data::HDict, names: &[&str]) -> Option<String> {
    names
        .iter()
        .find_map(|name| row.get(name).and_then(kind_to_text))
}

fn row_value(row: &haystack_core::data::HDict) -> Option<&Kind> {
    ["curVal", "value", "val", "hisVal"]
        .iter()
        .find_map(|name| row.get(name))
}

fn row_timestamp(row: &haystack_core::data::HDict) -> Option<DateTime<Utc>> {
    ["ts", "timestamp", "observedAt", "observed_at"]
        .iter()
        .find_map(|name| row.get(name).and_then(kind_to_datetime))
}

fn normalize_current_rows(
    grid: &HGrid,
    entries: &[&HaystackCatalogEntry],
) -> Result<Vec<HaystackValue>, String> {
    let by_ref: HashMap<&str, &HaystackCatalogEntry> = entries
        .iter()
        .map(|entry| (entry.source_ref.as_str(), *entry))
        .collect();
    let mut values = Vec::new();
    for row in grid.iter() {
        let Some(source_ref) = row_string(row, &["id", "ref"]) else {
            return Err("Haystack current-read row has no id ref".into());
        };
        let Some(entry) = by_ref.get(source_ref.as_str()) else {
            return Err("Haystack current-read row is outside the trusted catalog".into());
        };
        let Some((kind, value, source_unit)) = row_value(row).and_then(kind_to_value) else {
            return Err("Haystack current-read row has no typed value".into());
        };
        values.push(HaystackValue {
            key: entry.public_key.clone(),
            kind,
            value,
            unit: source_unit
                .or_else(|| row_string(row, &["unit", "units"]))
                .or_else(|| entry.unit.clone()),
            quality: row_quality(row),
            observed_at: row_timestamp(row),
        });
    }
    Ok(values)
}

fn normalize_history_rows(
    grid: &HGrid,
    entry: &HaystackCatalogEntry,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> Result<Vec<HaystackValue>, String> {
    let mut values = Vec::new();
    for row in grid.iter() {
        let Some(observed_at) = row_timestamp(row) else {
            return Err("Haystack history sample has no source timestamp".into());
        };
        if observed_at < start || observed_at >= end {
            return Err("Haystack history response exceeded the requested time window".into());
        }
        let Some((kind, value, source_unit)) = row_value(row).and_then(kind_to_value) else {
            return Err("Haystack history sample has no typed value".into());
        };
        values.push(HaystackValue {
            key: entry.public_key.clone(),
            kind,
            value,
            unit: source_unit
                .or_else(|| row_string(row, &["unit", "units"]))
                .or_else(|| entry.unit.clone()),
            quality: row_quality(row),
            observed_at: Some(observed_at),
        });
    }
    Ok(values)
}

fn row_quality(row: &haystack_core::data::HDict) -> Quality {
    match row_string(row, &["quality", "status"]).as_deref() {
        Some(value) if matches!(value.to_ascii_lowercase().as_str(), "bad" | "fault") => {
            Quality::Bad
        }
        Some(value) if value.eq_ignore_ascii_case("stale") => Quality::Stale,
        Some(value) if value.eq_ignore_ascii_case("uncertain") => Quality::Uncertain,
        _ => Quality::Good,
    }
}

fn kind_to_value(kind: &Kind) -> Option<(ValueKind, Value, Option<String>)> {
    match kind {
        Kind::Number(number) => serde_json::Number::from_f64(number.val)
            .map(|value| (ValueKind::Number, Value::Number(value), number.unit.clone())),
        Kind::Bool(value) => Some((ValueKind::Bool, json!(value), None)),
        Kind::Str(value) => Some((ValueKind::String, json!(value), None)),
        Kind::Ref(value) => Some((ValueKind::String, json!(value.val), None)),
        Kind::DateTime(value) => Some((
            ValueKind::String,
            Value::String(value.dt.to_rfc3339()),
            None,
        )),
        Kind::Null | Kind::NA => Some((ValueKind::Null, Value::Null, None)),
        _ => None,
    }
}

fn kind_to_text(kind: &Kind) -> Option<String> {
    match kind {
        Kind::Str(value) => Some(value.to_string()),
        Kind::Ref(value) => Some(value.val.clone()),
        Kind::Symbol(value) => Some(value.to_string()),
        Kind::Date(value) => Some(value.to_string()),
        Kind::DateTime(value) => Some(value.dt.to_rfc3339()),
        Kind::Number(value) => Some(value.val.to_string()),
        Kind::Bool(value) => Some(value.to_string()),
        _ => None,
    }
}

fn kind_to_datetime(kind: &Kind) -> Option<DateTime<Utc>> {
    match kind {
        Kind::DateTime(HDateTime { dt, .. }) => Some(dt.with_timezone(&Utc)),
        _ => {
            let value = kind_to_text(kind)?;
            DateTime::parse_from_rfc3339(&value)
                .ok()
                .map(|value| value.with_timezone(&Utc))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::HaystackSettings;
    use axum::body::Body;
    use axum::extract::{Query, State};
    use axum::http::{HeaderMap, StatusCode};
    use axum::response::IntoResponse;
    use axum::routing::get;
    use axum::Router;
    use base64::engine::general_purpose::STANDARD as BASE64;
    use base64::Engine;
    use bytes::Bytes;
    use openfdd_contracts::{
        ConnectorScope, HaystackAboutRequest, HaystackCurrentReadRequest,
        HaystackCurrentReadResponse, HaystackHistoryReadRequest,
    };
    use std::collections::BTreeMap;
    use tokio::net::TcpListener;

    #[test]
    fn transport_rejects_defaults_and_urls_with_credentials() {
        assert!(BoundedHaystackHttp::new(&HaystackSettings::default()).is_err());
        let settings = HaystackSettings {
            base_url: "https://u:p@example.test/api".into(),
            username: "u".into(),
            password: "p".into(),
            ..HaystackSettings::default()
        };
        assert!(BoundedHaystackHttp::new(&settings).is_err());
    }

    #[test]
    fn read_allowlist_has_no_write_or_discovery_operation() {
        let settings = HaystackSettings {
            base_url: "https://example.test/api".into(),
            username: "user".into(),
            password: "pass".into(),
            auth_mode: HaystackAuthMode::Basic,
            tls_verify: true,
            catalog_path: None,
        };
        let service = HaystackService::new(settings);
        assert!(service.check_op("read").is_ok());
        assert!(service.check_op("pointWrite").is_err());
        assert!(service.check_op("watchSub").is_err());
    }

    fn point_entry(unit: Option<&str>) -> HaystackCatalogEntry {
        HaystackCatalogEntry {
            public_key: "point-1".into(),
            kind: openfdd_contracts::HaystackRecordKind::Point,
            display_name: "Point 1".into(),
            equipment_key: Some("equipment-1".into()),
            role: Some("zone_t".into()),
            unit: unit.map(str::to_string),
            source_ref: "point-1".into(),
            nav_ref: None,
        }
    }

    #[test]
    fn zinc_fixture_normalizes_number_unit_labeled_ref_and_timezone_datetime() {
        let grid = zinc::decode_grid(
            "ver:\"3.0\"\nid,curVal,ts,siteRef\n@point-1 \"Labeled Point\",72.5°F,2026-10-02T12:00:00-05:00 New_York,@site-1 \"Main Site\"\n",
        )
        .unwrap();
        let entry = point_entry(None);
        let values = normalize_current_rows(&grid, &[&entry]).unwrap();
        assert_eq!(values.len(), 1);
        assert_eq!(values[0].key, "point-1");
        assert_eq!(values[0].kind, ValueKind::Number);
        assert_eq!(values[0].value, serde_json::json!(72.5));
        assert_eq!(values[0].unit.as_deref(), Some("°F"));
        assert_eq!(
            values[0].observed_at.unwrap().to_rfc3339(),
            "2026-10-02T17:00:00+00:00"
        );
        assert_eq!(
            row_string(grid.iter().next().unwrap(), &["siteRef"]),
            Some("site-1".into())
        );
    }

    #[test]
    fn zinc_fixture_normalizes_history_rows_and_rejects_window_escape() {
        let grid = zinc::decode_grid(
            "ver:\"3.0\"\nts,val\n2026-10-02T12:00:00-05:00 New_York,72.5°F\n2026-10-02T12:15:00-05:00 New_York,73.0°F\n",
        )
        .unwrap();
        let entry = point_entry(None);
        let start = "2026-10-02T17:00:00Z".parse().unwrap();
        let end = "2026-10-02T18:00:00Z".parse().unwrap();
        let values = normalize_history_rows(&grid, &entry, start, end).unwrap();
        assert_eq!(values.len(), 2);
        assert_eq!(values[1].value, serde_json::json!(73.0));
        assert_eq!(values[1].unit.as_deref(), Some("°F"));
        assert!(normalize_history_rows(&grid, &entry, start, start).is_err());
    }

    #[test]
    fn source_filter_uses_haystack_ref_literal() {
        let reference = HRef::from_val("point-1");
        assert_eq!(format!("id == {reference}"), "id == @point-1");
        assert_eq!(ref_literal("point-1").unwrap(), "@point-1");
        assert!(!HRef::from_val("point one").is_valid());
    }

    #[tokio::test]
    async fn loaded_toml_catalog_uses_canonical_ref_in_authenticated_http_read() {
        async fn read(
            headers: HeaderMap,
            Query(query): Query<BTreeMap<String, String>>,
        ) -> impl IntoResponse {
            if headers.get("authorization").and_then(|v| v.to_str().ok())
                != Some("Basic dXNlcjpwYXNz")
            {
                return (StatusCode::UNAUTHORIZED, "").into_response();
            }
            if query.get("filter").map(String::as_str) != Some("id == @ahu-1-sat") {
                return (StatusCode::BAD_REQUEST, "wrong Haystack ref filter").into_response();
            }
            (
                StatusCode::OK,
                "ver:\"3.0\"\nid,curVal,ts\n@ahu-1-sat \"Supply air temperature\",72.5°F,2026-10-02T12:00:00-05:00 New_York\n",
            )
                .into_response()
        }

        let catalog_path = std::env::temp_dir().join(format!(
            "openfdd-loaded-haystack-catalog-{}.toml",
            uuid::Uuid::new_v4()
        ));
        std::fs::write(
            &catalog_path,
            r#"revision = "fixture-loaded-v1"

[[records]]
key = "point:ahu-1:sat"
kind = "point"
display_name = "Supply air temperature"
equipment_key = "equipment:ahu-1"
role = "sat"
unit = "°F"
source_ref = "@ahu-1-sat"
nav_ref = "@ahu-1"
"#,
        )
        .unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            axum::serve(listener, Router::new().route("/read", get(read)))
                .await
                .unwrap();
        });
        let service = HaystackService::new(HaystackSettings {
            base_url: format!("http://{address}/"),
            username: "user".into(),
            password: "pass".into(),
            auth_mode: HaystackAuthMode::Basic,
            catalog_path: Some(catalog_path.clone()),
            ..HaystackSettings::default()
        });
        assert!(service.has_trusted_catalog());
        let response = service
            .current_read_typed(&HaystackCurrentReadRequest {
                schema: HAYSTACK_READ_CONTRACT_V1.into(),
                request_id: uuid::Uuid::new_v4(),
                scope: ConnectorScope {
                    tenant_id: "tenant".into(),
                    building_id: "building".into(),
                    edge_id: "edge".into(),
                },
                public_keys: vec!["point:ahu-1:sat".into()],
            })
            .await
            .unwrap();
        assert_eq!(response.values[0].key, "point:ahu-1:sat");
        assert_eq!(response.values[0].value, serde_json::json!(72.5));
        assert_eq!(response.values[0].unit.as_deref(), Some("°F"));
        server.abort();
        let _ = std::fs::remove_file(catalog_path);
    }

    #[tokio::test]
    async fn basic_zinc_server_fixture_drives_typed_current_and_history_reads() {
        async fn read(
            headers: HeaderMap,
            Query(query): Query<BTreeMap<String, String>>,
        ) -> impl IntoResponse {
            if headers.get("authorization").and_then(|v| v.to_str().ok())
                != Some("Basic dXNlcjpwYXNz")
            {
                return (StatusCode::UNAUTHORIZED, "").into_response();
            }
            if query.get("filter").map(String::as_str) != Some("id == @point-1") {
                return (StatusCode::BAD_REQUEST, "wrong filter").into_response();
            }
            (
                StatusCode::OK,
                "ver:\"3.0\"\nid,curVal,ts\n@point-1 \"Labeled Point\",72.5°F,2026-10-02T12:00:00-05:00 New_York\n",
            )
                .into_response()
        }

        async fn history(headers: HeaderMap) -> impl IntoResponse {
            if headers.get("authorization").and_then(|v| v.to_str().ok())
                != Some("Basic dXNlcjpwYXNz")
            {
                return (StatusCode::UNAUTHORIZED, "").into_response();
            }
            (
                StatusCode::OK,
                "ver:\"3.0\"\nts,val\n2026-10-02T12:00:00-05:00 New_York,72.5°F\n2026-10-02T12:15:00-05:00 New_York,73.0°F\n",
            )
                .into_response()
        }

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            axum::serve(
                listener,
                Router::new()
                    .route("/read", get(read))
                    .route("/hisRead", get(history)),
            )
            .await
            .unwrap();
        });
        let settings = HaystackSettings {
            base_url: format!("http://{address}/"),
            username: "user".into(),
            password: "pass".into(),
            auth_mode: HaystackAuthMode::Basic,
            ..HaystackSettings::default()
        };
        let service = HaystackService::with_catalog(
            settings,
            HaystackCatalog {
                revision: "fixture-v1".into(),
                entries: vec![point_entry(None)],
            },
        );
        let scope = ConnectorScope {
            tenant_id: "tenant".into(),
            building_id: "building".into(),
            edge_id: "edge".into(),
        };
        let current = service
            .current_read_typed(&HaystackCurrentReadRequest {
                schema: HAYSTACK_READ_CONTRACT_V1.into(),
                request_id: uuid::Uuid::new_v4(),
                scope: scope.clone(),
                public_keys: vec!["point-1".into()],
            })
            .await
            .unwrap();
        assert_eq!(current.values[0].unit.as_deref(), Some("°F"));
        assert_eq!(
            current.values[0].observed_at.unwrap().to_rfc3339(),
            "2026-10-02T17:00:00+00:00"
        );
        let history = service
            .history_read_typed(&HaystackHistoryReadRequest {
                schema: HAYSTACK_READ_CONTRACT_V1.into(),
                request_id: uuid::Uuid::new_v4(),
                scope,
                public_keys: vec!["point-1".into()],
                start: "2026-10-02T17:00:00Z".parse().unwrap(),
                end: "2026-10-02T18:00:00Z".parse().unwrap(),
                max_samples: 16,
            })
            .await
            .unwrap();
        assert_eq!(history.sample_count, 2);
        assert_eq!(history.series[0].values[1].value, serde_json::json!(73.0));
        server.abort();
    }

    #[tokio::test]
    async fn scram_server_fixture_authenticates_before_about_read() {
        type Handshake = Arc<tokio::sync::Mutex<Option<haystack_core::auth::ScramHandshake>>>;

        async fn about(
            headers: HeaderMap,
            State((handshake, credentials)): State<(
                Handshake,
                Arc<haystack_core::auth::ScramCredentials>,
            )>,
        ) -> axum::response::Response {
            let Some(header) = headers.get("authorization").and_then(|v| v.to_str().ok()) else {
                return (StatusCode::UNAUTHORIZED, "").into_response();
            };
            match haystack_core::auth::parse_auth_header(header) {
                Ok(haystack_core::auth::AuthHeader::Hello {
                    username,
                    data: Some(data),
                }) => {
                    let Ok(client_nonce) = haystack_core::auth::extract_client_nonce(&data) else {
                        return (StatusCode::UNAUTHORIZED, "").into_response();
                    };
                    let (state, server_first) = haystack_core::auth::server_first_message(
                        &username,
                        &client_nonce,
                        &credentials,
                    );
                    *handshake.lock().await = Some(state);
                    let challenge = haystack_core::auth::format_www_authenticate(
                        "fixture-token",
                        "SHA-256",
                        &server_first,
                    );
                    axum::response::Response::builder()
                        .status(StatusCode::UNAUTHORIZED)
                        .header("www-authenticate", challenge)
                        .body(Body::empty())
                        .unwrap()
                }
                Ok(haystack_core::auth::AuthHeader::Scram {
                    handshake_token,
                    data,
                }) if handshake_token == "fixture-token" => {
                    let Some(state) = handshake.lock().await.take() else {
                        return (StatusCode::UNAUTHORIZED, "").into_response();
                    };
                    let Ok(signature) = haystack_core::auth::server_verify_final(&state, &data)
                    else {
                        return (StatusCode::UNAUTHORIZED, "").into_response();
                    };
                    let server_final = BASE64.encode(format!("v={}", BASE64.encode(signature)));
                    let info = haystack_core::auth::format_auth_info("scram-token", &server_final);
                    axum::response::Response::builder()
                        .status(StatusCode::OK)
                        .header("authentication-info", info)
                        .body(Body::empty())
                        .unwrap()
                }
                Ok(haystack_core::auth::AuthHeader::Bearer { auth_token })
                    if auth_token == "scram-token" =>
                {
                    (
                        StatusCode::OK,
                        "ver:\"3.0\"\nvendorName,productName\n\"fixture\",\"scram\"\n",
                    )
                        .into_response()
                }
                _ => (StatusCode::UNAUTHORIZED, "").into_response(),
            }
        }

        let credentials = Arc::new(haystack_core::auth::derive_credentials(
            "pass",
            b"fixture-salt",
            4096,
        ));
        let handshake: Handshake = Arc::new(tokio::sync::Mutex::new(None));
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn({
            let state = (Arc::clone(&handshake), Arc::clone(&credentials));
            async move {
                axum::serve(
                    listener,
                    Router::new().route("/about", get(about)).with_state(state),
                )
                .await
                .unwrap();
            }
        });
        let settings = HaystackSettings {
            base_url: format!("http://{address}/"),
            username: "user".into(),
            password: "pass".into(),
            auth_mode: HaystackAuthMode::Scram,
            ..HaystackSettings::default()
        };
        let service = HaystackService::with_catalog(
            settings,
            HaystackCatalog {
                revision: "scram-fixture-v1".into(),
                entries: Vec::new(),
            },
        );
        let response = service
            .about_typed(&HaystackAboutRequest {
                schema: HAYSTACK_READ_CONTRACT_V1.into(),
                request_id: uuid::Uuid::new_v4(),
                scope: ConnectorScope {
                    tenant_id: "tenant".into(),
                    building_id: "building".into(),
                    edge_id: "edge".into(),
                },
            })
            .await
            .unwrap();
        assert_eq!(response.product.as_deref(), Some("scram"));
        server.abort();
    }

    #[tokio::test]
    async fn redirect_and_chunked_body_limits_are_enforced() {
        async fn redirect() -> axum::response::Response {
            axum::response::Response::builder()
                .status(StatusCode::FOUND)
                .header("location", "http://127.0.0.1/elsewhere")
                .body(Body::empty())
                .unwrap()
        }
        async fn oversized() -> axum::response::Response {
            let chunk = Bytes::from(vec![b'x'; HAYSTACK_MAX_BODY_BYTES + 1]);
            let body = Body::from_stream(futures_util::stream::iter(vec![Ok::<
                Bytes,
                std::convert::Infallible,
            >(chunk)]));
            axum::response::Response::builder()
                .status(StatusCode::OK)
                .body(body)
                .unwrap()
        }
        async fn run_current(
            address: std::net::SocketAddr,
        ) -> Result<HaystackCurrentReadResponse, String> {
            let settings = HaystackSettings {
                base_url: format!("http://{address}/"),
                username: "user".into(),
                password: "pass".into(),
                auth_mode: HaystackAuthMode::Basic,
                ..HaystackSettings::default()
            };
            HaystackService::with_catalog(
                settings,
                HaystackCatalog {
                    revision: "bounds-v1".into(),
                    entries: vec![point_entry(None)],
                },
            )
            .current_read_typed(&HaystackCurrentReadRequest {
                schema: HAYSTACK_READ_CONTRACT_V1.into(),
                request_id: uuid::Uuid::new_v4(),
                scope: ConnectorScope {
                    tenant_id: "tenant".into(),
                    building_id: "building".into(),
                    edge_id: "edge".into(),
                },
                public_keys: vec!["point-1".into()],
            })
            .await
        }

        let redirect_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let redirect_address = redirect_listener.local_addr().unwrap();
        let redirect_server = tokio::spawn(async move {
            axum::serve(
                redirect_listener,
                Router::new().route("/read", get(redirect)),
            )
            .await
            .unwrap();
        });
        let redirect_error = run_current(redirect_address).await.unwrap_err();
        assert!(redirect_error.contains("redirect"));
        redirect_server.abort();

        let oversized_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let oversized_address = oversized_listener.local_addr().unwrap();
        let oversized_server = tokio::spawn(async move {
            axum::serve(
                oversized_listener,
                Router::new().route("/read", get(oversized)),
            )
            .await
            .unwrap();
        });
        let oversized_error = run_current(oversized_address).await.unwrap_err();
        assert!(oversized_error.contains("1 MiB"));
        oversized_server.abort();
    }
}
