//! Application settings and config loaders (mirrors `app/config.py`).

use std::net::Ipv4Addr;
use std::path::{Path, PathBuf};

use serde::Deserialize;

use openfdd_contracts::HaystackRecordKind;

#[derive(Debug, Clone)]
pub struct BacnetServerSettings {
    pub device_instance: u32,
    pub device_name: String,
    pub interface: Ipv4Addr,
    pub port: u16,
    pub broadcast: Ipv4Addr,
}

impl Default for BacnetServerSettings {
    fn default() -> Self {
        Self {
            device_instance: 599_999,
            device_name: "OpenFDD".into(),
            interface: Ipv4Addr::UNSPECIFIED,
            port: 0xBAC0,
            broadcast: Ipv4Addr::new(192, 168, 204, 255),
        }
    }
}

#[derive(Debug, Clone)]
pub struct BacnetClientSettings {
    pub interface: Ipv4Addr,
    pub broadcast: Ipv4Addr,
    pub whois_bind_port: u16,
    pub read_bind_port: u16,
    pub apdu_timeout_ms: u32,
    pub whois_timeout_secs: f64,
}

impl Default for BacnetClientSettings {
    fn default() -> Self {
        Self {
            interface: Ipv4Addr::new(192, 168, 204, 55),
            broadcast: Ipv4Addr::new(192, 168, 204, 255),
            whois_bind_port: 0,
            read_bind_port: 0,
            apdu_timeout_ms: 6000,
            whois_timeout_secs: 8.0,
        }
    }
}

#[derive(Debug, Clone)]
pub struct WeatherSettings {
    pub city: String,
    pub interval_secs: u64,
    pub http_timeout_secs: f64,
    pub fallback_temp_f: f64,
    pub fallback_humidity: f64,
    pub fallback_wind_mph: f64,
    pub mirror_interval_secs: f64,
}

impl Default for WeatherSettings {
    fn default() -> Self {
        Self {
            city: "Madison Wisconsin".into(),
            interval_secs: 1200,
            http_timeout_secs: 20.0,
            fallback_temp_f: 70.0,
            fallback_humidity: 50.0,
            fallback_wind_mph: 0.0,
            mirror_interval_secs: 2.0,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ModbusSettings {
    pub default_host: String,
    pub default_port: u16,
    pub default_unit_id: u8,
    pub default_timeout_secs: f64,
}

impl Default for ModbusSettings {
    fn default() -> Self {
        Self {
            default_host: "127.0.0.1".into(),
            default_port: 5502,
            default_unit_id: 1,
            default_timeout_secs: 5.0,
        }
    }
}

#[derive(Debug, Clone)]
pub struct RestSettings {
    pub default_timeout_secs: u64,
    pub default_tls_verify: bool,
    pub default_poll_interval_secs: u64,
    pub allow_write: bool,
}

impl Default for RestSettings {
    fn default() -> Self {
        Self {
            default_timeout_secs: 10,
            default_tls_verify: true,
            default_poll_interval_secs: 300,
            allow_write: false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RestAuth {
    None,
    Bearer,
    ApiKeyHeader,
    Basic,
}

impl RestAuth {
    pub fn as_str(&self) -> &'static str {
        match self {
            RestAuth::None => "none",
            RestAuth::Bearer => "bearer",
            RestAuth::ApiKeyHeader => "api_key_header",
            RestAuth::Basic => "basic",
        }
    }
}

fn parse_rest_auth(raw: &str) -> Result<RestAuth, String> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "" | "none" => Ok(RestAuth::None),
        "bearer" => Ok(RestAuth::Bearer),
        "api_key_header" => Ok(RestAuth::ApiKeyHeader),
        "basic" => Ok(RestAuth::Basic),
        other => Err(format!(
            "invalid rest auth '{other}' (expected bearer | api_key_header | basic | none)"
        )),
    }
}

#[derive(Debug, Clone)]
pub struct RestPoint {
    pub point_name: String,
    /// Validated to GET at load time; retained for catalog parity.
    /// Catalog field loaded from rest_points.toml; not yet read on poll path.
    pub method: String,
    pub path: String,
    pub select: String,
    pub units: String,
    pub scale: f64,
}

#[derive(Debug, Clone)]
pub struct RestWriteBinding {
    pub name: String,
    pub enabled: bool,
    pub method: String,
    pub path: String,
    pub body_template: String,
    pub value_min: Option<f64>,
    pub value_max: Option<f64>,
}

#[derive(Debug, Clone)]
pub struct RestDevice {
    pub name: String,
    pub enabled: bool,
    pub base_url: String,
    pub auth: RestAuth,
    pub token_env: Option<String>,
    pub api_key_header: String,
    pub basic_username: Option<String>,
    pub tls_verify: bool,
    pub timeout_secs: u64,
    pub poll_interval_secs: u64,
    pub points: Vec<RestPoint>,
    pub writes: Vec<RestWriteBinding>,
}

/// Reject anything that is not a plain relative path joined below `base_url`
/// (SSRF guard: no absolute URLs, schemes, authority tricks, or traversal).
pub fn validate_rest_path(path: &str) -> Result<(), String> {
    let p = path.trim();
    if p.is_empty() {
        return Err("path must be non-empty".into());
    }
    if !p.starts_with('/') {
        return Err(format!(
            "path '{p}' must start with '/' (relative to base_url)"
        ));
    }
    if p.starts_with("//") {
        return Err(format!("path '{p}' must not start with '//'"));
    }
    if p.contains("://") || p.contains('\\') {
        return Err(format!(
            "path '{p}' must be relative (no scheme or backslashes)"
        ));
    }
    if p.split('/').any(|seg| seg == "..") {
        return Err(format!("path '{p}' must not contain '..' segments"));
    }
    if p.contains(char::is_whitespace) {
        return Err(format!("path '{p}' must not contain whitespace"));
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HaystackAuthMode {
    Scram,
    Basic,
}

#[derive(Debug, Clone)]
pub struct HaystackSettings {
    pub base_url: String,
    pub username: String,
    pub password: String,
    pub auth_mode: HaystackAuthMode,
    pub tls_verify: bool,
    /// Trusted mapping loaded at process startup. It is never accepted from
    /// a request and its source refs are never returned by the public API.
    pub catalog_path: Option<PathBuf>,
}

impl Default for HaystackSettings {
    fn default() -> Self {
        Self {
            base_url: String::new(),
            username: String::new(),
            password: String::new(),
            auth_mode: HaystackAuthMode::Scram,
            tls_verify: true,
            catalog_path: None,
        }
    }
}

impl HaystackSettings {
    /// Settings used by the BACnet/Modbus profile. Keeping the values empty
    /// prevents that process from carrying Haystack credentials or an
    /// endpoint in its in-memory configuration.
    pub fn unconfigured() -> Self {
        Self {
            base_url: String::new(),
            username: String::new(),
            password: String::new(),
            auth_mode: HaystackAuthMode::Scram,
            tls_verify: true,
            catalog_path: None,
        }
    }
}

/// One trusted public-key mapping to a private Haystack source reference.
///
/// `source_ref` and `nav_ref` are configuration-only values.  They must never
/// be copied into a connector response or a central proxy request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HaystackCatalogEntry {
    pub public_key: String,
    pub kind: HaystackRecordKind,
    pub display_name: String,
    pub equipment_key: Option<String>,
    pub role: Option<String>,
    pub unit: Option<String>,
    pub source_ref: String,
    pub nav_ref: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HaystackCatalog {
    pub revision: String,
    pub entries: Vec<HaystackCatalogEntry>,
}

#[derive(Debug, Clone)]
pub struct PollSettings {
    pub enabled: bool,
    pub interval_secs: f64,
    pub startup_delay_secs: f64,
    pub max_samples: usize,
    /// When true, poll only points whose names map to known HVAC health roles (~30% cap).
    pub health_roles_only: bool,
}

/// Wave N: fixed HVAC health / FDD poll interval (seconds). Not operator-adjustable.
pub const FIXED_POLL_INTERVAL_SECS: f64 = 300.0;

/// Fieldbus telemetry delivery profiles.
///
/// `mqtts` is the historical cloud/edge path. `local_fieldbus` sends the
/// same versioned envelope to a central instance over its authenticated local
/// HTTP ingest endpoint. `dual` enables both sinks; local delivery remains
/// independent of the optional MQTT connection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IngestMode {
    Mqtts,
    LocalFieldbus,
    Dual,
}

impl IngestMode {
    pub fn parse(raw: &str) -> Result<Self, String> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "mqtts" => Ok(Self::Mqtts),
            "local_fieldbus" => Ok(Self::LocalFieldbus),
            "dual" => Ok(Self::Dual),
            other => Err(format!(
                "invalid OPENFDD_INGEST_MODE '{other}' (expected mqtts | local_fieldbus | dual)"
            )),
        }
    }

    pub fn from_env() -> Result<Self, String> {
        Self::parse(&std::env::var("OPENFDD_INGEST_MODE").unwrap_or_else(|_| "mqtts".into()))
    }

    pub fn uses_mqtt(self) -> bool {
        matches!(self, Self::Mqtts | Self::Dual)
    }

    pub fn uses_local(self) -> bool {
        matches!(self, Self::LocalFieldbus | Self::Dual)
    }
}

impl Default for PollSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            interval_secs: FIXED_POLL_INTERVAL_SECS,
            startup_delay_secs: 5.0,
            max_samples: 5000,
            health_roles_only: false,
        }
    }
}

#[derive(Debug, Clone)]
pub struct FieldPoint {
    pub object_type: String,
    pub object_instance: u32,
    pub point_name: String,
    /// Loaded from field_devices.toml and exposed as a typed inventory unit.
    pub units: String,
}

#[derive(Debug, Clone)]
pub struct FieldDevice {
    pub name: String,
    pub enabled: bool,
    pub device_instance: u32,
    pub host: String,
    pub port: u16,
    pub mstp_network: Option<u16>,
    pub mstp_mac: Vec<u8>,
    /// Maximum ReadPropertyMultiple object specifications per request. Lower
    /// this for small, non-segmenting MS/TP controllers (for example 206-byte APDU devices).
    pub rpm_chunk: usize,
    /// Advertised maximum APDU for a manually seeded routed device.
    pub max_apdu: u32,
    pub points: Vec<FieldPoint>,
}

impl FieldDevice {
    pub fn address(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }

    pub fn is_routed(&self) -> bool {
        self.mstp_network.is_some() && !self.mstp_mac.is_empty()
    }
}

#[derive(Debug, Clone)]
pub struct HostedObjectRow {
    pub name: String,
    pub point_type: String,
    pub units: String,
    pub commandable: bool,
    pub default: String,
    pub instance: u32,
    pub description: String,
}

#[derive(Debug, Clone)]
pub struct Settings {
    pub bacnet_server: BacnetServerSettings,
    pub bacnet_client: BacnetClientSettings,
    pub weather: WeatherSettings,
    pub modbus: ModbusSettings,
    /// True only when the Modbus section or supported MODBUS_* settings were
    /// explicitly supplied; defaults do not advertise an upstream.
    pub modbus_configured: bool,
    pub haystack: HaystackSettings,
    /// True only when an explicit Haystack endpoint was supplied. Credentials
    /// or auth mode alone must not create a connector.
    pub haystack_configured: bool,
    pub rest: RestSettings,
    pub poll: PollSettings,
    pub http_host: String,
    pub http_port: u16,
    pub objects_csv: PathBuf,
    pub field_devices_toml: PathBuf,
    pub openapi_enabled: bool,
    pub swagger_servers_url: Option<String>,
    /// Trusted connector identity loaded once at startup. Route handlers use
    /// this snapshot instead of reading process environment per request.
    pub connector_tenant_id: Option<String>,
    pub connector_building_id: Option<String>,
    pub connector_edge_id: Option<String>,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SettingsProfile {
    /// Historical all-protocol `openfdd-fieldbus` behavior.
    Legacy,
    /// BACnet/Modbus only; Haystack settings are not loaded.
    BacnetModbus,
    /// Outbound Haystack only; endpoint and Haystack credentials are loaded.
    Haystack,
}

impl Default for Settings {
    fn default() -> Self {
        let config_dir = config_dir();
        Self {
            bacnet_server: BacnetServerSettings::default(),
            bacnet_client: BacnetClientSettings::default(),
            weather: WeatherSettings::default(),
            modbus: ModbusSettings::default(),
            modbus_configured: false,
            haystack: HaystackSettings::default(),
            haystack_configured: false,
            rest: RestSettings::default(),
            poll: PollSettings::default(),
            http_host: "127.0.0.1".into(),
            http_port: 8080,
            objects_csv: config_dir.join("objects.csv"),
            field_devices_toml: config_dir.join("field_devices.toml"),
            openapi_enabled: true,
            swagger_servers_url: None,
            connector_tenant_id: None,
            connector_building_id: None,
            connector_edge_id: None,
        }
    }
}

#[derive(Debug, Deserialize, Default)]
struct GatewayToml {
    bacnet_server: Option<BacnetServerToml>,
    bacnet_client: Option<BacnetClientToml>,
    weather: Option<WeatherToml>,
    modbus: Option<ModbusToml>,
    haystack: Option<HaystackToml>,
    rest: Option<RestToml>,
    poll: Option<PollToml>,
}

#[derive(Debug, Deserialize)]
struct RestToml {
    default_timeout_secs: Option<u64>,
    default_tls_verify: Option<bool>,
    default_poll_interval_secs: Option<u64>,
    allow_write: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct BacnetServerToml {
    device_instance: Option<u32>,
    device_name: Option<String>,
    interface: Option<String>,
    port: Option<u16>,
    broadcast: Option<String>,
}

#[derive(Debug, Deserialize)]
struct BacnetClientToml {
    interface: Option<String>,
    broadcast: Option<String>,
    whois_bind_port: Option<u16>,
    read_bind_port: Option<u16>,
    apdu_timeout_ms: Option<u32>,
    whois_timeout_secs: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct WeatherToml {
    city: Option<String>,
    interval_secs: Option<u64>,
    http_timeout_secs: Option<f64>,
    fallback_temp_f: Option<f64>,
    fallback_humidity: Option<f64>,
    fallback_wind_mph: Option<f64>,
    mirror_interval_secs: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct ModbusToml {
    default_host: Option<String>,
    default_port: Option<u16>,
    default_unit_id: Option<u8>,
    default_timeout_secs: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct HaystackToml {
    base_url: Option<String>,
    username: Option<String>,
    password: Option<String>,
    auth_mode: Option<String>,
    tls_verify: Option<bool>,
    catalog_path: Option<String>,
}

#[derive(Debug, Deserialize)]
struct HaystackCatalogToml {
    revision: Option<String>,
    #[serde(default)]
    records: Vec<HaystackCatalogRecordToml>,
}

#[derive(Debug, Deserialize)]
struct HaystackCatalogRecordToml {
    key: String,
    kind: String,
    display_name: String,
    equipment_key: Option<String>,
    role: Option<String>,
    unit: Option<String>,
    source_ref: String,
    nav_ref: Option<String>,
}

#[derive(Debug, Deserialize)]
struct PollToml {
    enabled: Option<bool>,
    interval_secs: Option<f64>,
    startup_delay_secs: Option<f64>,
    max_samples: Option<usize>,
    health_roles_only: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct FieldDevicesToml {
    devices: Vec<FieldDeviceToml>,
}

#[derive(Debug, Deserialize)]
struct FieldDeviceToml {
    name: String,
    enabled: Option<bool>,
    device_instance: u32,
    host: String,
    port: Option<u16>,
    mstp_network: Option<u16>,
    mstp_mac: Option<Vec<u8>>,
    rpm_chunk: Option<usize>,
    max_apdu: Option<u32>,
    points: Option<Vec<FieldPointToml>>,
}

#[derive(Debug, Deserialize)]
struct FieldPointToml {
    object_type: String,
    object_instance: u32,
    point_name: Option<String>,
    units: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
struct RestDevicesToml {
    #[serde(default)]
    devices: Vec<RestDeviceToml>,
}

#[derive(Debug, Deserialize)]
struct RestDeviceToml {
    name: String,
    enabled: Option<bool>,
    base_url: String,
    auth: Option<String>,
    token_env: Option<String>,
    api_key_header: Option<String>,
    basic_username: Option<String>,
    tls_verify: Option<bool>,
    timeout_secs: Option<u64>,
    poll_interval_secs: Option<u64>,
    points: Option<Vec<RestPointToml>>,
    writes: Option<Vec<RestWriteToml>>,
}

#[derive(Debug, Deserialize)]
struct RestPointToml {
    point_name: String,
    method: Option<String>,
    path: String,
    select: Option<String>,
    units: Option<String>,
    scale: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct RestWriteToml {
    name: String,
    enabled: Option<bool>,
    method: Option<String>,
    path: String,
    body_template: String,
    value_min: Option<f64>,
    value_max: Option<f64>,
}

pub fn config_dir() -> PathBuf {
    for key in ["OPENFDD_FIELDBUS_CONFIG_DIR", "RUSTY_GATEWAY_CONFIG_DIR"] {
        if let Ok(v) = std::env::var(key) {
            if !v.is_empty() {
                return PathBuf::from(v);
            }
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../config/fieldbus")
}

fn env_first(names: &[&str]) -> Option<String> {
    for n in names {
        if let Ok(v) = std::env::var(n) {
            if !v.is_empty() {
                return Some(v);
            }
        }
    }
    None
}

fn parse_haystack_auth_mode(raw: &str) -> HaystackAuthMode {
    match raw.trim().to_ascii_lowercase().as_str() {
        "basic" | "http_basic" | "niagara" => HaystackAuthMode::Basic,
        _ => HaystackAuthMode::Scram,
    }
}

fn parse_haystack_record_kind(raw: &str) -> Result<HaystackRecordKind, String> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "site" => Ok(HaystackRecordKind::Site),
        "building" => Ok(HaystackRecordKind::Building),
        "equipment" | "equip" => Ok(HaystackRecordKind::Equipment),
        "point" => Ok(HaystackRecordKind::Point),
        "navigation" | "nav" => Ok(HaystackRecordKind::Navigation),
        _ => Err("Haystack catalog record kind is unsupported".into()),
    }
}

fn validate_catalog_token(value: &str, label: &str, max: usize) -> Result<(), String> {
    if value.trim().is_empty()
        || value.len() > max
        || value.chars().any(char::is_control)
        || value.contains("//")
        || value.contains("..")
        || value.contains('\\')
    {
        return Err(format!("Haystack catalog {label} is invalid"));
    }
    Ok(())
}

fn canonical_source_ref(value: &str, label: &str) -> Result<String, String> {
    let value = value.trim();
    let bare = value.strip_prefix('@').unwrap_or(value);
    validate_catalog_token(bare, label, 256)?;
    if !bare
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, ':' | '_' | '-' | '.' | '~'))
    {
        return Err(format!(
            "Haystack catalog {label} contains an unsafe ref token"
        ));
    }
    Ok(bare.to_string())
}

/// Load and validate the trusted public-key/source-ref mapping once at startup.
/// Missing configuration is an honest empty catalog; it never implies a live
/// Haystack connector is ready.
pub fn load_haystack_catalog(path: Option<&Path>) -> Result<HaystackCatalog, String> {
    let Some(path) = path else {
        return Ok(HaystackCatalog {
            revision: "catalog-empty".into(),
            entries: Vec::new(),
        });
    };
    if std::fs::metadata(path)
        .map(|metadata| metadata.len() > 1024 * 1024)
        .unwrap_or(true)
    {
        return Err("trusted Haystack catalog exceeds its configured byte bound".into());
    }
    let text = std::fs::read_to_string(path)
        .map_err(|_| "trusted Haystack catalog could not be read".to_string())?;
    let parsed: HaystackCatalogToml =
        toml::from_str(&text).map_err(|_| "trusted Haystack catalog is invalid".to_string())?;
    if parsed.records.len() > 10_000 {
        return Err("trusted Haystack catalog exceeds its configured bound".into());
    }
    let mut entries = Vec::with_capacity(parsed.records.len());
    let mut keys = std::collections::BTreeSet::new();
    for record in parsed.records {
        validate_catalog_token(&record.key, "key", 160)?;
        if record.key.contains('/')
            || record.key.contains("://")
            || record.key.contains(' ')
            || record.key.contains('"')
            || record.key.contains('\'')
        {
            return Err("Haystack catalog key is not a safe public key".into());
        }
        if !keys.insert(record.key.clone()) {
            return Err("trusted Haystack catalog contains duplicate keys".into());
        }
        validate_catalog_token(&record.display_name, "display_name", 160)?;
        let source_ref = canonical_source_ref(&record.source_ref, "source_ref")?;
        if let Some(value) = record.equipment_key.as_deref() {
            validate_catalog_token(value, "equipment_key", 160)?;
        }
        if let Some(value) = record.role.as_deref() {
            validate_catalog_token(value, "role", 96)?;
            if !fdd_core::columns::is_known_cookbook_role(&fdd_core::columns::normalize_role(value))
            {
                return Err("trusted Haystack catalog role is not canonical".into());
            }
        }
        if let Some(value) = record.unit.as_deref() {
            validate_catalog_token(value, "unit", 64)?;
        }
        let nav_ref = record
            .nav_ref
            .as_deref()
            .map(|value| canonical_source_ref(value, "nav_ref"))
            .transpose()?;
        entries.push(HaystackCatalogEntry {
            public_key: record.key,
            kind: parse_haystack_record_kind(&record.kind)?,
            display_name: record.display_name,
            equipment_key: record.equipment_key,
            role: record
                .role
                .map(|value| fdd_core::columns::normalize_role(&value)),
            unit: record.unit,
            source_ref,
            nav_ref,
        });
    }
    entries.sort_by(|left, right| left.public_key.cmp(&right.public_key));
    let revision = parsed
        .revision
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| catalog_revision(&entries));
    validate_catalog_token(&revision, "revision", 128)?;
    Ok(HaystackCatalog { revision, entries })
}

/// A Haystack endpoint is publicly configured only when its explicit
/// credentials and trusted catalog are present and valid. URL presence alone
/// is not an authenticated connector capability.
pub fn haystack_connector_configured(settings: &Settings) -> bool {
    settings.haystack_configured
        && !settings.haystack.username.trim().is_empty()
        && !settings.haystack.password.trim().is_empty()
        && settings
            .haystack
            .catalog_path
            .as_deref()
            .and_then(|path| load_haystack_catalog(Some(path)).ok())
            .is_some_and(|catalog| !catalog.entries.is_empty())
}

fn catalog_revision(entries: &[HaystackCatalogEntry]) -> String {
    let mut hash = 0xcbf29ce484222325_u64;
    for entry in entries {
        for byte in format!(
            "{}|{:?}|{}|{}|{}|{}|{}",
            entry.public_key,
            entry.kind,
            entry.display_name,
            entry.equipment_key.as_deref().unwrap_or_default(),
            entry.role.as_deref().unwrap_or_default(),
            entry.unit.as_deref().unwrap_or_default(),
            entry.source_ref,
        )
        .bytes()
        {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(0x100000001b3);
        }
    }
    format!("catalog-{hash:016x}")
}

fn env_bool(value: Option<&str>, default: bool) -> bool {
    match value {
        None => default,
        Some(v) => matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        ),
    }
}

pub fn git_sha() -> String {
    env_first(&["OPENFDD_FIELDBUS_GIT_SHA", "GIT_SHA"]).unwrap_or_else(|| "unknown".into())
}

fn parse_ipv4(s: &str) -> Option<Ipv4Addr> {
    s.parse().ok()
}

pub fn subnet_broadcast(ip: Ipv4Addr) -> Ipv4Addr {
    let o = ip.octets();
    Ipv4Addr::new(o[0], o[1], o[2], 255)
}

fn load_gateway_toml() -> GatewayToml {
    let path = config_dir().join("gateway.toml");
    if !path.exists() {
        return GatewayToml::default();
    }
    let text = std::fs::read_to_string(&path).unwrap_or_default();
    toml::from_str(&text).unwrap_or_default()
}

#[allow(dead_code)]
pub fn load_settings() -> Settings {
    load_settings_for(SettingsProfile::Legacy)
}

pub fn load_settings_for(profile: SettingsProfile) -> Settings {
    let raw = load_gateway_toml();
    let load_haystack = !matches!(profile, SettingsProfile::BacnetModbus);
    let haystack_configured = load_haystack
        && (raw
            .haystack
            .as_ref()
            .and_then(|settings| settings.base_url.as_deref())
            .is_some_and(|value| !value.trim().is_empty())
            || ["HAYSTACK_BASE_URL", "OPENFDD_HAYSTACK_BASE_URL"]
                .iter()
                .any(|name| std::env::var(name).is_ok_and(|value| !value.trim().is_empty())));
    let modbus_configured = !matches!(profile, SettingsProfile::BacnetModbus)
        && (raw.modbus.is_some()
            || std::env::var("MODBUS_DEFAULT_HOST").is_ok_and(|value| !value.trim().is_empty()));
    let mut s = Settings {
        haystack: if load_haystack {
            HaystackSettings::default()
        } else {
            HaystackSettings::unconfigured()
        },
        haystack_configured,
        modbus_configured,
        connector_tenant_id: env_first(&["OPENFDD_TENANT_ID"]),
        connector_building_id: env_first(&["OPENFDD_BUILDING_ID", "OPENFDD_SITE_ID"]),
        connector_edge_id: env_first(&["OPENFDD_EDGE_ID", "RUSTY_GATEWAY_EDGE_ID"]),
        ..Settings::default()
    };

    if let Some(bs) = raw.bacnet_server {
        if let Some(v) = bs.device_instance {
            s.bacnet_server.device_instance = v;
        }
        if let Some(v) = bs.device_name {
            s.bacnet_server.device_name = v;
        }
        if let Some(v) = bs.interface.and_then(|x| parse_ipv4(&x)) {
            s.bacnet_server.interface = v;
        }
        if let Some(v) = bs.port {
            s.bacnet_server.port = v;
        }
        if let Some(v) = bs.broadcast.and_then(|x| parse_ipv4(&x)) {
            s.bacnet_server.broadcast = v;
        }
    }
    if let Some(bc) = raw.bacnet_client {
        if let Some(v) = bc.interface.and_then(|x| parse_ipv4(&x)) {
            s.bacnet_client.interface = v;
        }
        if let Some(v) = bc.broadcast.and_then(|x| parse_ipv4(&x)) {
            s.bacnet_client.broadcast = v;
        }
        if let Some(v) = bc.whois_bind_port {
            s.bacnet_client.whois_bind_port = v;
        }
        if let Some(v) = bc.read_bind_port {
            s.bacnet_client.read_bind_port = v;
        }
        if let Some(v) = bc.apdu_timeout_ms {
            s.bacnet_client.apdu_timeout_ms = v;
        }
        if let Some(v) = bc.whois_timeout_secs {
            s.bacnet_client.whois_timeout_secs = v;
        }
    }
    if let Some(w) = raw.weather {
        if let Some(v) = w.city {
            s.weather.city = v;
        }
        if let Some(v) = w.interval_secs {
            s.weather.interval_secs = v;
        }
        if let Some(v) = w.http_timeout_secs {
            s.weather.http_timeout_secs = v;
        }
        if let Some(v) = w.fallback_temp_f {
            s.weather.fallback_temp_f = v;
        }
        if let Some(v) = w.fallback_humidity {
            s.weather.fallback_humidity = v;
        }
        if let Some(v) = w.fallback_wind_mph {
            s.weather.fallback_wind_mph = v;
        }
        if let Some(v) = w.mirror_interval_secs {
            s.weather.mirror_interval_secs = v;
        }
    }
    if let Some(m) = raw.modbus {
        if let Some(v) = m.default_host {
            s.modbus.default_host = v;
        }
        if let Some(v) = m.default_port {
            s.modbus.default_port = v;
        }
        if let Some(v) = m.default_unit_id {
            s.modbus.default_unit_id = v;
        }
        if let Some(v) = m.default_timeout_secs {
            s.modbus.default_timeout_secs = v;
        }
    }
    if load_haystack {
        if let Some(h) = raw.haystack {
            if let Some(v) = h.base_url {
                s.haystack.base_url = v;
            }
            if let Some(v) = h.username {
                s.haystack.username = v;
            }
            if let Some(v) = h.password {
                s.haystack.password = v;
            }
            if let Some(v) = h.auth_mode {
                s.haystack.auth_mode = parse_haystack_auth_mode(&v);
            }
            if let Some(v) = h.tls_verify {
                s.haystack.tls_verify = v;
            }
            if let Some(v) = h.catalog_path {
                s.haystack.catalog_path = Some(PathBuf::from(v));
            }
        }
    }
    if let Some(r) = raw.rest {
        if let Some(v) = r.default_timeout_secs {
            s.rest.default_timeout_secs = v;
        }
        if let Some(v) = r.default_tls_verify {
            s.rest.default_tls_verify = v;
        }
        if let Some(v) = r.default_poll_interval_secs {
            s.rest.default_poll_interval_secs = v;
        }
        if let Some(v) = r.allow_write {
            s.rest.allow_write = v;
        }
    }
    if let Some(p) = raw.poll {
        if let Some(v) = p.enabled {
            s.poll.enabled = v;
        }
        if let Some(_v) = p.interval_secs {
            // Wave N: TOML [poll].interval_secs ignored; fixed at FIXED_POLL_INTERVAL_SECS.
        }
        if let Some(v) = p.startup_delay_secs {
            s.poll.startup_delay_secs = v;
        }
        if let Some(v) = p.max_samples {
            s.poll.max_samples = v;
        }
        if let Some(v) = p.health_roles_only {
            s.poll.health_roles_only = v;
        }
    }

    if let Some(v) = env_first(&["OPENFDD_FIELDBUS_BIND", "RUSTY_GATEWAY_BIND"]) {
        if let Some(ip) = parse_ipv4(&v) {
            s.bacnet_client.interface = ip;
            let bcast = subnet_broadcast(ip);
            s.bacnet_server.broadcast = bcast;
            s.bacnet_client.broadcast = bcast;
        }
    }
    if let Some(v) = env_first(&["OPENFDD_FIELDBUS_SERVER_BIND", "RUSTY_GATEWAY_SERVER_BIND"]) {
        if let Some(ip) = parse_ipv4(&v) {
            s.bacnet_server.interface = ip;
        }
    }
    if let Some(v) = env_first(&["OPENFDD_FIELDBUS_BROADCAST", "RUSTY_GATEWAY_BROADCAST"]) {
        if let Some(ip) = parse_ipv4(&v) {
            s.bacnet_server.broadcast = ip;
            s.bacnet_client.broadcast = ip;
        }
    }
    if let Some(v) = env_first(&["OPENFDD_FIELDBUS_BACNET_PORT", "RUSTY_GATEWAY_BACNET_PORT"]) {
        if let Ok(port) = v.parse::<u16>() {
            s.bacnet_server.port = port;
        }
    }
    if let Some(v) = env_first(&[
        "OPENFDD_BACNET_DEVICE_INSTANCE",
        "OPENFDD_FIELDBUS_DEVICE_INSTANCE",
    ]) {
        if let Ok(instance) = v.parse::<u32>() {
            s.bacnet_server.device_instance = instance;
        }
    }
    if let Some(v) = env_first(&["OPENFDD_FIELDBUS_HTTP_HOST", "RUSTY_GATEWAY_HTTP_HOST"]) {
        s.http_host = v;
    }
    if let Some(v) = env_first(&["OPENFDD_FIELDBUS_HTTP_PORT", "RUSTY_GATEWAY_HTTP_PORT"]) {
        if let Ok(port) = v.parse() {
            s.http_port = port;
        }
    }
    if let Some(v) = env_first(&[
        "OPENFDD_FIELDBUS_POLL_ENABLED",
        "RUSTY_GATEWAY_POLL_ENABLED",
    ]) {
        s.poll.enabled = env_bool(Some(&v), s.poll.enabled);
    }
    // Wave N: ignore OPENFDD_FIELDBUS_POLL_INTERVAL_SECS / TOML overrides — fixed 300s.
    // Health-role subset remains the bandwidth throttle (not a faster poll).

    if load_haystack {
        if let Some(v) = env_first(&["HAYSTACK_BASE_URL", "OPENFDD_HAYSTACK_BASE_URL"]) {
            s.haystack.base_url = v;
        }
        if let Some(v) = env_first(&["HAYSTACK_USER", "OPENFDD_HAYSTACK_USER"]) {
            s.haystack.username = v;
        }
        if let Some(v) = env_first(&["HAYSTACK_PASS", "OPENFDD_HAYSTACK_PASS"]) {
            s.haystack.password = v;
        }
        if let Some(v) = env_first(&["HAYSTACK_AUTH_MODE", "OPENFDD_HAYSTACK_AUTH_MODE"]) {
            s.haystack.auth_mode = parse_haystack_auth_mode(&v);
        }
        if let Some(v) = env_first(&["HAYSTACK_TLS_VERIFY", "OPENFDD_HAYSTACK_TLS_VERIFY"]) {
            s.haystack.tls_verify = env_bool(Some(&v), s.haystack.tls_verify);
        }
        if let Some(v) = env_first(&["HAYSTACK_CATALOG_PATH", "OPENFDD_HAYSTACK_CATALOG_PATH"]) {
            s.haystack.catalog_path = Some(PathBuf::from(v));
        }
    }
    if let Some(v) = env_first(&["MODBUS_DEFAULT_HOST"]) {
        s.modbus.default_host = v;
    }

    s.openapi_enabled = env_bool(
        env_first(&["OPENFDD_FIELDBUS_OPENAPI", "RUSTY_GATEWAY_OPENAPI"]).as_deref(),
        true,
    );
    s.swagger_servers_url = env_first(&[
        "OPENFDD_FIELDBUS_SWAGGER_SERVERS_URL",
        "RUSTY_GATEWAY_SWAGGER_SERVERS_URL",
    ]);

    if env_bool(
        env_first(&["OPENFDD_POLL_HEALTH_ONLY"]).as_deref(),
        s.poll.health_roles_only,
    ) {
        s.poll.health_roles_only = true;
    }

    finalize_poll_interval(&mut s);
    s
}

/// Wave N: always lock poll (+ MQTT publish default) to FIXED_POLL_INTERVAL_SECS.
pub(crate) fn finalize_poll_interval(s: &mut Settings) {
    s.poll.interval_secs = FIXED_POLL_INTERVAL_SECS;
}

pub fn load_objects_csv(path: Option<&Path>) -> Result<Vec<HostedObjectRow>, String> {
    let csv_path = path
        .map(Path::to_path_buf)
        .unwrap_or_else(|| config_dir().join("objects.csv"));
    let mut rdr = csv::Reader::from_path(&csv_path)
        .map_err(|e| format!("failed to read {}: {e}", csv_path.display()))?;
    let mut rows = Vec::new();
    for result in rdr.records() {
        let row = result.map_err(|e| e.to_string())?;
        rows.push(HostedObjectRow {
            name: row.get(0).unwrap_or("").trim().to_string(),
            point_type: row.get(1).unwrap_or("").trim().to_string(),
            units: row.get(2).unwrap_or("").trim().to_string(),
            commandable: row.get(3).unwrap_or("N").trim().eq_ignore_ascii_case("Y"),
            default: row.get(4).unwrap_or("").trim().to_string(),
            instance: row
                .get(5)
                .unwrap_or("0")
                .trim()
                .parse()
                .map_err(|e| format!("invalid instance: {e}"))?,
            description: row.get(6).unwrap_or("").trim().to_string(),
        });
    }
    Ok(rows)
}

pub fn load_field_devices(path: Option<&Path>) -> Result<Vec<FieldDevice>, String> {
    let toml_path = path
        .map(Path::to_path_buf)
        .unwrap_or_else(|| config_dir().join("field_devices.toml"));
    let text = std::fs::read_to_string(&toml_path)
        .map_err(|e| format!("failed to read {}: {e}", toml_path.display()))?;
    let data: FieldDevicesToml = toml::from_str(&text).map_err(|e| e.to_string())?;
    Ok(data
        .devices
        .into_iter()
        .map(|d| FieldDevice {
            name: d.name,
            enabled: d.enabled.unwrap_or(true),
            device_instance: d.device_instance,
            host: d.host,
            port: d.port.unwrap_or(0xBAC0),
            mstp_network: d.mstp_network,
            mstp_mac: d.mstp_mac.unwrap_or_default(),
            rpm_chunk: d.rpm_chunk.unwrap_or(25).clamp(1, 100),
            max_apdu: d.max_apdu.unwrap_or(480),
            points: d
                .points
                .unwrap_or_default()
                .into_iter()
                .map(|p| FieldPoint {
                    object_type: p.object_type,
                    object_instance: p.object_instance,
                    point_name: p.point_name.unwrap_or_default(),
                    units: p.units.unwrap_or_default(),
                })
                .collect(),
        })
        .collect())
}

/// Load the REST/JSON device catalog. A missing file means "no REST devices"
/// (the driver is optional); a malformed file or invalid entry is a hard error.
pub fn load_rest_devices(
    path: Option<&Path>,
    defaults: &RestSettings,
) -> Result<Vec<RestDevice>, String> {
    let toml_path = path
        .map(Path::to_path_buf)
        .unwrap_or_else(|| config_dir().join("rest_devices.toml"));
    if !toml_path.exists() {
        return Ok(Vec::new());
    }
    let text = std::fs::read_to_string(&toml_path)
        .map_err(|e| format!("failed to read {}: {e}", toml_path.display()))?;
    let data: RestDevicesToml =
        toml::from_str(&text).map_err(|e| format!("{}: {e}", toml_path.display()))?;

    let mut devices = Vec::new();
    for d in data.devices {
        let auth = parse_rest_auth(d.auth.as_deref().unwrap_or("none"))
            .map_err(|e| format!("rest device '{}': {e}", d.name))?;
        let base = d.base_url.trim();
        if !(base.starts_with("http://") || base.starts_with("https://")) {
            return Err(format!(
                "rest device '{}': base_url must be http(s), got '{base}'",
                d.name
            ));
        }
        let mut points = Vec::new();
        for p in d.points.unwrap_or_default() {
            validate_rest_path(&p.path)
                .map_err(|e| format!("rest device '{}' point '{}': {e}", d.name, p.point_name))?;
            let method = p.method.unwrap_or_else(|| "GET".into()).to_uppercase();
            if method != "GET" {
                return Err(format!(
                    "rest device '{}' point '{}': only GET reads are supported",
                    d.name, p.point_name
                ));
            }
            let point = RestPoint {
                point_name: p.point_name,
                method,
                path: p.path,
                select: p.select.unwrap_or_default(),
                units: p.units.unwrap_or_default(),
                scale: p.scale.unwrap_or(1.0),
            };
            // Keep the validated method in the catalog for compatibility
            // consumers even though the current poll path is GET-only.
            let _ = &point.method;
            points.push(point);
        }
        let mut writes = Vec::new();
        for w in d.writes.unwrap_or_default() {
            validate_rest_path(&w.path)
                .map_err(|e| format!("rest device '{}' write '{}': {e}", d.name, w.name))?;
            let method = w.method.unwrap_or_else(|| "POST".into()).to_uppercase();
            if !matches!(method.as_str(), "POST" | "PUT" | "PATCH") {
                return Err(format!(
                    "rest device '{}' write '{}': method must be POST, PUT, or PATCH",
                    d.name, w.name
                ));
            }
            writes.push(RestWriteBinding {
                name: w.name,
                // Writes fail closed: bindings are disabled unless explicitly enabled.
                enabled: w.enabled.unwrap_or(false),
                method,
                path: w.path,
                body_template: w.body_template,
                value_min: w.value_min,
                value_max: w.value_max,
            });
        }
        devices.push(RestDevice {
            name: d.name,
            enabled: d.enabled.unwrap_or(false),
            base_url: base.trim_end_matches('/').to_string(),
            auth,
            token_env: d.token_env,
            api_key_header: d.api_key_header.unwrap_or_else(|| "X-API-Key".into()),
            basic_username: d.basic_username,
            tls_verify: d.tls_verify.unwrap_or(defaults.default_tls_verify),
            timeout_secs: d.timeout_secs.unwrap_or(defaults.default_timeout_secs),
            poll_interval_secs: d
                .poll_interval_secs
                .unwrap_or(defaults.default_poll_interval_secs),
            points,
            writes,
        });
    }
    let mut names: Vec<&str> = devices.iter().map(|d| d.name.as_str()).collect();
    names.sort_unstable();
    names.dedup();
    if names.len() != devices.len() {
        return Err("rest_devices.toml: device names must be unique".into());
    }
    Ok(devices)
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Mutex;

    use super::*;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn repo_config_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../config/fieldbus")
    }

    #[test]
    fn load_objects_csv_contains_weather_points() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("OPENFDD_FIELDBUS_CONFIG_DIR", repo_config_dir());
        let rows = load_objects_csv(None).expect("objects.csv");
        let names: HashMap<_, _> = rows.iter().map(|r| (r.name.as_str(), r)).collect();
        assert!(names.contains_key("outside-air-temperature"));
        assert!(names.contains_key("weather-last-updated"));
        assert!(names.contains_key("openfdd-active-fault-count"));
        assert!(names.contains_key("openfdd-optimization-enabled"));
        assert!(names["openfdd-optimization-enabled"].commandable);
        assert!(names["outside-air-temperature"]
            .description
            .contains("Open-Meteo"));
        std::env::remove_var("OPENFDD_FIELDBUS_CONFIG_DIR");
    }

    #[test]
    fn bacnet_modbus_profile_does_not_load_haystack_credentials() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("OPENFDD_FIELDBUS_CONFIG_DIR", repo_config_dir());
        std::env::set_var("OPENFDD_HAYSTACK_BASE_URL", "https://secret.example.test");
        std::env::set_var("OPENFDD_HAYSTACK_USER", "secret-user");
        std::env::set_var("OPENFDD_HAYSTACK_PASS", "secret-pass");

        let settings = load_settings_for(SettingsProfile::BacnetModbus);
        assert!(!settings.haystack_configured);
        assert!(settings.haystack.base_url.is_empty());
        assert!(settings.haystack.username.is_empty());
        assert!(settings.haystack.password.is_empty());

        std::env::remove_var("OPENFDD_FIELDBUS_CONFIG_DIR");
        std::env::remove_var("OPENFDD_HAYSTACK_BASE_URL");
        std::env::remove_var("OPENFDD_HAYSTACK_USER");
        std::env::remove_var("OPENFDD_HAYSTACK_PASS");
    }

    #[test]
    fn point_names_lowercase_hyphenated() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("OPENFDD_FIELDBUS_CONFIG_DIR", repo_config_dir());
        for row in load_objects_csv(None).expect("objects.csv") {
            let ok = row
                .name
                .chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
                && !row.name.starts_with('-')
                && !row.name.ends_with('-')
                && !row.name.contains("--");
            assert!(ok, "{} is not lowercase-hyphenated", row.name);
        }
        std::env::remove_var("OPENFDD_FIELDBUS_CONFIG_DIR");
    }

    #[test]
    fn weather_and_fault_points_not_commandable() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("OPENFDD_FIELDBUS_CONFIG_DIR", repo_config_dir());
        let rows: HashMap<_, _> = load_objects_csv(None)
            .expect("objects.csv")
            .into_iter()
            .map(|r| (r.name.clone(), r))
            .collect();
        for name in [
            "outside-air-temperature",
            "outside-air-humidity",
            "outside-air-wind-speed",
            "outside-air-dewpoint",
            "weather-location",
            "weather-last-updated",
            "app-fault",
            "openfdd-active-fault-count",
            "openfdd-faults-present",
        ] {
            assert!(!rows[name].commandable, "{name} should not be commandable");
        }
        std::env::remove_var("OPENFDD_FIELDBUS_CONFIG_DIR");
    }

    #[test]
    fn weather_instances_match_openfdd() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("OPENFDD_FIELDBUS_CONFIG_DIR", repo_config_dir());
        let rows: HashMap<_, _> = load_objects_csv(None)
            .expect("objects.csv")
            .into_iter()
            .map(|r| (r.name.clone(), r))
            .collect();
        assert_eq!(rows["outside-air-temperature"].instance, 9101);
        assert_eq!(rows["outside-air-humidity"].instance, 9102);
        assert_eq!(rows["outside-air-dewpoint"].instance, 9103);
        assert_eq!(rows["weather-last-updated"].instance, 9107);
        std::env::remove_var("OPENFDD_FIELDBUS_CONFIG_DIR");
    }

    #[test]
    fn env_alias_precedence_and_poll_settings() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        for key in [
            "OPENFDD_FIELDBUS_DEV_FAST_POLL",
            "OPENFDD_FIELDBUS_POLL_INTERVAL_SECS",
            "RUSTY_GATEWAY_POLL_INTERVAL_SECS",
            "OPENFDD_FIELDBUS_POLL_ENABLED",
            "RUSTY_GATEWAY_POLL_ENABLED",
            "OPENFDD_FIELDBUS_HTTP_PORT",
            "RUSTY_GATEWAY_HTTP_PORT",
        ] {
            std::env::remove_var(key);
        }
        std::env::set_var("RUSTY_GATEWAY_HTTP_PORT", "8080");
        std::env::set_var("OPENFDD_FIELDBUS_HTTP_PORT", "9091");
        assert_eq!(load_settings().http_port, 9091);
        std::env::remove_var("OPENFDD_FIELDBUS_HTTP_PORT");
        assert_eq!(load_settings().http_port, 8080);

        std::env::set_var("OPENFDD_FIELDBUS_POLL_ENABLED", "false");
        assert!(!load_settings().poll.enabled);
        std::env::remove_var("OPENFDD_FIELDBUS_POLL_ENABLED");
        std::env::remove_var("RUSTY_GATEWAY_HTTP_PORT");
        std::env::remove_var("OPENFDD_FIELDBUS_HTTP_PORT");
    }

    #[test]
    fn poll_interval_finalize_locks_to_300() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let mut s = Settings::default();
        s.poll.interval_secs = 12.5;
        finalize_poll_interval(&mut s);
        assert!((s.poll.interval_secs - FIXED_POLL_INTERVAL_SECS).abs() < f64::EPSILON);
    }

    #[test]
    fn poll_interval_env_override_ignored_through_load_settings() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let tmp = std::env::temp_dir().join(format!("ofdd-cfg-test-{stamp}"));
        std::fs::create_dir_all(&tmp).expect("temp config dir");
        std::fs::write(
            tmp.join("gateway.toml"),
            "[bacnet_server]\ndevice_instance = 599999\n[poll]\ninterval_secs = 12.5\n",
        )
        .expect("write gateway.toml");
        std::env::set_var("OPENFDD_FIELDBUS_CONFIG_DIR", &tmp);
        for key in [
            "OPENFDD_FIELDBUS_DEV_FAST_POLL",
            "OPENFDD_FIELDBUS_POLL_INTERVAL_SECS",
            "RUSTY_GATEWAY_POLL_INTERVAL_SECS",
        ] {
            std::env::remove_var(key);
        }
        std::env::set_var("OPENFDD_FIELDBUS_POLL_INTERVAL_SECS", "12.5");
        std::env::set_var("OPENFDD_FIELDBUS_DEV_FAST_POLL", "1");
        let locked = load_settings().poll.interval_secs;
        assert!(
            (locked - FIXED_POLL_INTERVAL_SECS).abs() < 1e-9,
            "expected fixed 300s, got {locked}"
        );
        std::env::remove_var("OPENFDD_FIELDBUS_CONFIG_DIR");
        std::env::remove_var("OPENFDD_FIELDBUS_POLL_INTERVAL_SECS");
        std::env::remove_var("OPENFDD_FIELDBUS_DEV_FAST_POLL");
        let _ = std::fs::remove_dir_all(tmp);
    }

    #[test]
    fn bacnet_port_defaults_and_overrides() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::remove_var("OPENFDD_FIELDBUS_BACNET_PORT");
        std::env::remove_var("RUSTY_GATEWAY_BACNET_PORT");
        // Avoid poll-floor races from sibling tests that touch DEV_FAST_POLL.
        std::env::remove_var("OPENFDD_FIELDBUS_DEV_FAST_POLL");
        std::env::remove_var("OPENFDD_FIELDBUS_POLL_INTERVAL_SECS");
        std::env::remove_var("RUSTY_GATEWAY_POLL_INTERVAL_SECS");
        let s = load_settings();
        assert_eq!(s.bacnet_server.port, 47808);
        assert_eq!(s.bacnet_client.whois_bind_port, 0);

        std::env::set_var("OPENFDD_FIELDBUS_BACNET_PORT", "47809");
        let s = load_settings();
        assert_eq!(s.bacnet_server.port, 47809);
        assert_eq!(s.bacnet_client.whois_bind_port, 0);

        std::env::set_var("RUSTY_GATEWAY_BACNET_PORT", "47810");
        std::env::remove_var("OPENFDD_FIELDBUS_BACNET_PORT");
        assert_eq!(load_settings().bacnet_server.port, 47810);
        assert_eq!(load_settings().bacnet_client.whois_bind_port, 0);
        std::env::remove_var("RUSTY_GATEWAY_BACNET_PORT");
    }

    #[test]
    fn git_sha_from_env() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("OPENFDD_FIELDBUS_GIT_SHA", "deadbeef");
        assert_eq!(git_sha(), "deadbeef");
        std::env::remove_var("OPENFDD_FIELDBUS_GIT_SHA");
        std::env::remove_var("GIT_SHA");
        assert_eq!(git_sha(), "unknown");
    }

    #[test]
    fn haystack_auth_mode_parsing() {
        assert_eq!(parse_haystack_auth_mode("basic"), HaystackAuthMode::Basic);
        assert_eq!(parse_haystack_auth_mode("niagara"), HaystackAuthMode::Basic);
        assert_eq!(parse_haystack_auth_mode("scram"), HaystackAuthMode::Scram);
    }

    #[test]
    fn trusted_haystack_catalog_has_immutable_revision_and_rejects_injection() {
        let path = std::env::temp_dir().join(format!(
            "openfdd-haystack-catalog-{}-{}.toml",
            std::process::id(),
            std::thread::current().name().unwrap_or("test")
        ));
        std::fs::write(
            &path,
            r#"revision = "catalog-test-v1"

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
        let catalog = load_haystack_catalog(Some(&path)).unwrap();
        assert_eq!(catalog.revision, "catalog-test-v1");
        assert_eq!(catalog.entries[0].source_ref, "ahu-1-sat");
        assert_eq!(catalog.entries[0].nav_ref.as_deref(), Some("ahu-1"));
        let revision = catalog_revision(&catalog.entries);
        assert_ne!(revision, "catalog-test-v1");

        std::fs::write(
            &path,
            r#"[[records]]
key = "point:bad"
kind = "point"
display_name = "Bad"
source_ref = "@point' or true"
"#,
        )
        .unwrap();
        assert!(load_haystack_catalog(Some(&path)).is_err());
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn rest_settings_defaults_fail_closed() {
        let s = RestSettings::default();
        assert_eq!(s.default_timeout_secs, 10);
        assert!(s.default_tls_verify);
        assert_eq!(s.default_poll_interval_secs, 300);
        assert!(!s.allow_write);
    }

    #[test]
    fn load_rest_devices_repo_example() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("OPENFDD_FIELDBUS_CONFIG_DIR", repo_config_dir());
        let devices = load_rest_devices(None, &RestSettings::default()).expect("rest_devices");
        assert_eq!(devices.len(), 1);
        let d = &devices[0];
        assert_eq!(d.name, "example-disabled");
        assert!(!d.enabled, "shipped example must stay disabled");
        assert_eq!(d.auth, RestAuth::Bearer);
        assert_eq!(d.token_env.as_deref(), Some("OPENFDD_REST_TOKEN_EXAMPLE"));
        assert!(d.tls_verify);
        assert_eq!(d.points.len(), 1);
        assert_eq!(d.points[0].point_name, "CHW-ST");
        assert_eq!(d.points[0].select, "$.value");
        assert_eq!(d.writes.len(), 1);
        std::env::remove_var("OPENFDD_FIELDBUS_CONFIG_DIR");
        assert!(
            !d.writes[0].enabled,
            "shipped write binding must stay disabled"
        );
        assert_eq!(d.writes[0].value_min, Some(40.0));
        assert_eq!(d.writes[0].value_max, Some(55.0));
    }

    #[test]
    fn load_rest_devices_missing_file_is_empty() {
        let devices = load_rest_devices(
            Some(Path::new("/nonexistent/rest_devices.toml")),
            &RestSettings::default(),
        )
        .unwrap();
        assert!(devices.is_empty());
    }

    #[test]
    fn field_device_rpm_chunk_is_configurable_and_bounded() {
        // Parse only. The address is not contacted; CI has no path to the FEC LAN.
        let path = std::env::temp_dir().join(format!(
            "openfdd-field-devices-{}-{}.toml",
            std::process::id(),
            std::thread::current().name().unwrap_or("test")
        ));
        std::fs::write(
            &path,
            r#"[[devices]]
name = "small-spyder"
device_instance = 5007
host = "192.168.204.200"
mstp_network = 2000
mstp_mac = [7]
rpm_chunk = 10
max_apdu = 206
"#,
        )
        .unwrap();
        let devices = load_field_devices(Some(&path)).unwrap();
        assert_eq!(devices[0].rpm_chunk, 10);
        assert_eq!(devices[0].max_apdu, 206);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn rest_path_must_be_relative() {
        assert!(validate_rest_path("/points/chw_supply_temp").is_ok());
        assert!(validate_rest_path("/a/b?x=1").is_ok());
        assert!(validate_rest_path("").is_err());
        assert!(validate_rest_path("points/x").is_err());
        assert!(validate_rest_path("https://evil.example/x").is_err());
        assert!(validate_rest_path("//evil.example/x").is_err());
        assert!(validate_rest_path("/a/../secrets").is_err());
        assert!(validate_rest_path("/a b").is_err());
    }

    #[test]
    fn rest_auth_parsing() {
        assert_eq!(parse_rest_auth("bearer").unwrap(), RestAuth::Bearer);
        assert_eq!(
            parse_rest_auth("api_key_header").unwrap(),
            RestAuth::ApiKeyHeader
        );
        assert_eq!(parse_rest_auth("basic").unwrap(), RestAuth::Basic);
        assert_eq!(parse_rest_auth("none").unwrap(), RestAuth::None);
        assert!(parse_rest_auth("oauth-dance").is_err());
    }

    #[test]
    fn subnet_broadcast_derives_slash24() {
        let ip: Ipv4Addr = "192.168.204.55".parse().unwrap();
        assert_eq!(subnet_broadcast(ip), Ipv4Addr::new(192, 168, 204, 255));
    }
}
