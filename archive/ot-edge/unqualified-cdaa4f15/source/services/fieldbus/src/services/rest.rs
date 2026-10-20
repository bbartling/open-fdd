//! Generic REST/JSON edge driver (#540).
//!
//! One pooled `reqwest::Client` per configured device (never per operation —
//! see the #535 fd-leak regression), per-device auth via env indirection,
//! consecutive-failure circuit breaker, and an allowlisted fail-closed write
//! path with structured audit logging.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use tokio::sync::Mutex;
use tracing::{info, warn};

use crate::config::{RestAuth, RestDevice, RestSettings, RestWriteBinding};

const BREAKER_THRESHOLD: u32 = 3;
const BREAKER_MAX_BACKOFF_SECS: u64 = 300;

#[derive(Debug)]
pub enum RestError {
    BadRequest(String),
    Forbidden(String),
    NotFound(String),
    Upstream(String),
}

impl std::fmt::Display for RestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RestError::BadRequest(m)
            | RestError::Forbidden(m)
            | RestError::NotFound(m)
            | RestError::Upstream(m) => write!(f, "{m}"),
        }
    }
}

impl std::error::Error for RestError {}

/// Resolved (non-secret-logging) auth material for one device.
#[derive(Clone)]
enum ResolvedAuth {
    None,
    Bearer(String),
    ApiKeyHeader { header: String, key: String },
    Basic { username: String, password: String },
}

/// Exponential backoff once the consecutive-failure threshold is crossed.
fn backoff_secs(consecutive_failures: u32) -> u64 {
    if consecutive_failures < BREAKER_THRESHOLD {
        return 0;
    }
    let exp = (consecutive_failures - BREAKER_THRESHOLD).min(16);
    (5u64 << exp).min(BREAKER_MAX_BACKOFF_SECS)
}

#[derive(Debug, Default)]
struct CircuitBreaker {
    consecutive_failures: u32,
    open_until: Option<Instant>,
    last_error: Option<String>,
    last_ok_ts: Option<f64>,
}

impl CircuitBreaker {
    fn is_open(&self, now: Instant) -> bool {
        self.open_until.is_some_and(|t| now < t)
    }

    fn record_success(&mut self) {
        self.consecutive_failures = 0;
        self.open_until = None;
        self.last_error = None;
        self.last_ok_ts = Some(unix_ts());
    }

    fn record_failure(&mut self, now: Instant, err: &str) {
        self.consecutive_failures += 1;
        self.last_error = Some(err.to_string());
        let secs = backoff_secs(self.consecutive_failures);
        if secs > 0 {
            self.open_until = Some(now + Duration::from_secs(secs));
        }
    }
}

fn unix_ts() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

struct DeviceRuntime {
    config: RestDevice,
    client: reqwest::Client,
    auth: ResolvedAuth,
    breaker: Mutex<CircuitBreaker>,
    last_values: Mutex<HashMap<String, Value>>,
}

pub struct RestClientService {
    settings: RestSettings,
    devices: Vec<Arc<DeviceRuntime>>,
    tasks: Mutex<Vec<tokio::task::JoinHandle<()>>>,
}

fn require_env(device: &str, var: Option<&str>) -> Result<String, String> {
    let name = var
        .filter(|v| !v.trim().is_empty())
        .ok_or_else(|| format!("rest device '{device}': token_env is required for this auth"))?;
    match std::env::var(name) {
        Ok(v) if !v.trim().is_empty() => Ok(v.trim().to_string()),
        _ => Err(format!(
            "rest device '{device}': required env '{name}' is missing or empty (secrets are env-indirect only)"
        )),
    }
}

fn resolve_auth(device: &RestDevice) -> Result<ResolvedAuth, String> {
    match device.auth {
        RestAuth::None => Ok(ResolvedAuth::None),
        RestAuth::Bearer => Ok(ResolvedAuth::Bearer(require_env(
            &device.name,
            device.token_env.as_deref(),
        )?)),
        RestAuth::ApiKeyHeader => Ok(ResolvedAuth::ApiKeyHeader {
            header: device.api_key_header.clone(),
            key: require_env(&device.name, device.token_env.as_deref())?,
        }),
        RestAuth::Basic => {
            let username = device
                .basic_username
                .clone()
                .filter(|u| !u.trim().is_empty())
                .ok_or_else(|| {
                    format!(
                        "rest device '{}': basic auth requires basic_username",
                        device.name
                    )
                })?;
            Ok(ResolvedAuth::Basic {
                username,
                password: require_env(&device.name, device.token_env.as_deref())?,
            })
        }
    }
}

/// Minimal JSONPath-style selector: `$.a.b[0].c` (dot keys + numeric indexes).
pub fn select_json(body: &Value, select: &str) -> Result<Value, String> {
    let s = select.trim();
    let s = s.strip_prefix('$').unwrap_or(s);
    let mut current = body;
    let mut rest = s;
    while !rest.is_empty() {
        rest = rest.strip_prefix('.').unwrap_or(rest);
        if rest.is_empty() {
            break;
        }
        if let Some(idx_body) = rest.strip_prefix('[') {
            let end = idx_body
                .find(']')
                .ok_or_else(|| format!("select '{select}': unterminated '['"))?;
            let idx: usize = idx_body[..end]
                .parse()
                .map_err(|_| format!("select '{select}': bad array index"))?;
            current = current
                .get(idx)
                .ok_or_else(|| format!("select '{select}': index {idx} not found"))?;
            rest = &idx_body[end + 1..];
        } else {
            let end = rest.find(['.', '[']).unwrap_or(rest.len());
            let key = &rest[..end];
            current = current
                .get(key)
                .ok_or_else(|| format!("select '{select}': key '{key}' not found"))?;
            rest = &rest[end..];
        }
    }
    Ok(current.clone())
}

/// Coerce a selected JSON value to f64 (numbers, bools, numeric strings).
pub fn value_as_f64(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        Value::String(s) => s.trim().parse().ok(),
        _ => None,
    }
}

/// Render `{{value}}` into a write body template.
pub fn render_body_template(template: &str, value: f64) -> String {
    let rendered = if value.fract() == 0.0 && value.abs() < 1e15 {
        format!("{}", value as i64)
    } else {
        format!("{value}")
    };
    template
        .replace("{{ value }}", &rendered)
        .replace("{{value}}", &rendered)
}

fn check_write_allowed(
    allow_write_global: bool,
    binding: &RestWriteBinding,
    value: f64,
) -> Result<(), RestError> {
    if !allow_write_global {
        return Err(RestError::Forbidden(
            "REST writes are disabled globally (rest.allow_write = false)".into(),
        ));
    }
    if !binding.enabled {
        return Err(RestError::Forbidden(format!(
            "write binding '{}' is disabled",
            binding.name
        )));
    }
    if let Some(min) = binding.value_min {
        if value < min {
            return Err(RestError::BadRequest(format!(
                "value {value} below value_min {min}"
            )));
        }
    }
    if let Some(max) = binding.value_max {
        if value > max {
            return Err(RestError::BadRequest(format!(
                "value {value} above value_max {max}"
            )));
        }
    }
    Ok(())
}

impl RestClientService {
    /// Build the service from settings + catalog. Fails loudly (startup abort)
    /// when an enabled device references a missing secret env var.
    pub fn from_config(settings: RestSettings, devices: Vec<RestDevice>) -> Result<Self, String> {
        let mut runtimes = Vec::new();
        for device in devices {
            if !device.enabled {
                // Disabled devices are listed but never built (no secrets needed).
                runtimes.push(Arc::new(DeviceRuntime {
                    client: reqwest::Client::new(),
                    auth: ResolvedAuth::None,
                    breaker: Mutex::new(CircuitBreaker::default()),
                    last_values: Mutex::new(HashMap::new()),
                    config: device,
                }));
                continue;
            }
            let auth = resolve_auth(&device)?;
            let client = reqwest::Client::builder()
                .timeout(Duration::from_secs(device.timeout_secs.max(1)))
                .danger_accept_invalid_certs(!device.tls_verify)
                .build()
                .map_err(|e| format!("rest device '{}': client build failed: {e}", device.name))?;
            if !device.tls_verify {
                warn!(device = %device.name, "REST device has tls_verify=false (certificate checks disabled)");
            }
            runtimes.push(Arc::new(DeviceRuntime {
                client,
                auth,
                breaker: Mutex::new(CircuitBreaker::default()),
                last_values: Mutex::new(HashMap::new()),
                config: device,
            }));
        }
        Ok(Self {
            settings,
            devices: runtimes,
            tasks: Mutex::new(Vec::new()),
        })
    }

    fn find_device(&self, name: &str) -> Result<&Arc<DeviceRuntime>, RestError> {
        self.devices
            .iter()
            .find(|d| d.config.name == name)
            .ok_or_else(|| RestError::NotFound(format!("unknown rest device '{name}'")))
    }

    fn find_enabled(&self, name: &str) -> Result<&Arc<DeviceRuntime>, RestError> {
        let d = self.find_device(name)?;
        if !d.config.enabled {
            return Err(RestError::Forbidden(format!(
                "rest device '{name}' is disabled"
            )));
        }
        Ok(d)
    }

    pub async fn list_devices(&self) -> Value {
        let mut out = Vec::new();
        for d in &self.devices {
            let breaker = d.breaker.lock().await;
            out.push(json!({
                "name": d.config.name,
                "enabled": d.config.enabled,
                "base_url": d.config.base_url,
                "auth": d.config.auth.as_str(),
                "tls_verify": d.config.tls_verify,
                "timeout_secs": d.config.timeout_secs,
                "poll_interval_secs": d.config.poll_interval_secs,
                "points": d.config.points.iter().map(|p| &p.point_name).collect::<Vec<_>>(),
                "writes": d.config.writes.iter().map(|w| json!({
                    "name": w.name,
                    "enabled": w.enabled,
                })).collect::<Vec<_>>(),
                "health": {
                    "consecutive_failures": breaker.consecutive_failures,
                    "circuit_open": breaker.is_open(Instant::now()),
                    "last_error": breaker.last_error,
                    "last_ok_ts": breaker.last_ok_ts,
                },
            }));
        }
        json!({ "ok": true, "allow_write": self.settings.allow_write, "devices": out })
    }

    async fn guard_breaker(&self, d: &DeviceRuntime) -> Result<(), RestError> {
        let breaker = d.breaker.lock().await;
        if breaker.is_open(Instant::now()) {
            return Err(RestError::Upstream(format!(
                "rest device '{}': circuit open after {} consecutive failures (last error: {})",
                d.config.name,
                breaker.consecutive_failures,
                breaker.last_error.as_deref().unwrap_or("unknown"),
            )));
        }
        Ok(())
    }

    fn apply_auth(
        &self,
        d: &DeviceRuntime,
        req: reqwest::RequestBuilder,
    ) -> reqwest::RequestBuilder {
        match &d.auth {
            ResolvedAuth::None => req,
            ResolvedAuth::Bearer(token) => req.bearer_auth(token),
            ResolvedAuth::ApiKeyHeader { header, key } => req.header(header.as_str(), key.as_str()),
            ResolvedAuth::Basic { username, password } => req.basic_auth(username, Some(password)),
        }
    }

    /// Execute a GET against a device-relative path, breaker-gated.
    async fn device_get(&self, d: &DeviceRuntime, path: &str) -> Result<(u16, Value), RestError> {
        crate::config::validate_rest_path(path).map_err(RestError::BadRequest)?;
        self.guard_breaker(d).await?;
        let url = format!("{}{}", d.config.base_url, path);
        let req = self.apply_auth(d, d.client.get(&url));
        let result = async {
            let resp = req.send().await.map_err(|e| e.to_string())?;
            let status = resp.status();
            let text = resp.text().await.map_err(|e| e.to_string())?;
            if status.is_server_error() {
                return Err(format!("HTTP {status}: {}", truncate(&text, 200)));
            }
            let body = serde_json::from_str(&text)
                .unwrap_or_else(|_| json!({ "raw": truncate(&text, 2000) }));
            Ok((status.as_u16(), body))
        }
        .await;
        let mut breaker = d.breaker.lock().await;
        match result {
            Ok(ok) => {
                breaker.record_success();
                Ok(ok)
            }
            Err(e) => {
                breaker.record_failure(Instant::now(), &e);
                Err(RestError::Upstream(format!(
                    "rest device '{}' GET {path}: {e}",
                    d.config.name
                )))
            }
        }
    }

    /// Live read of one configured point (select + scale applied).
    pub async fn read_point(&self, device: &str, point: &str) -> Result<Value, RestError> {
        let d = self.find_enabled(device)?;
        let p = d
            .config
            .points
            .iter()
            .find(|p| p.point_name == point)
            .ok_or_else(|| {
                RestError::NotFound(format!("unknown point '{point}' on device '{device}'"))
            })?
            .clone();
        let (status, body) = self.device_get(d, &p.path).await?;
        let selected = if p.select.trim().is_empty() {
            body.clone()
        } else {
            select_json(&body, &p.select).map_err(RestError::Upstream)?
        };
        let value = value_as_f64(&selected).map(|v| v * p.scale);
        Ok(json!({
            "ok": true,
            "device": device,
            "point": p.point_name,
            "status": status,
            "value": value,
            "raw": selected,
            "units": p.units,
            "ts": unix_ts(),
        }))
    }

    /// Raw passthrough GET — path is relative-only, joined below base_url.
    pub async fn raw_get(&self, device: &str, path: &str) -> Result<Value, RestError> {
        let d = self.find_enabled(device)?;
        let (status, body) = self.device_get(d, path).await?;
        Ok(json!({
            "ok": true,
            "device": device,
            "path": path,
            "status": status,
            "body": body,
        }))
    }

    /// Allowlisted write. Fails closed unless BOTH rest.allow_write and the
    /// binding's enabled flag are true. Every attempt is audit-logged.
    pub async fn write(&self, device: &str, name: &str, value: f64) -> Result<Value, RestError> {
        let audit = |outcome: &str, detail: &str| {
            info!(
                target: "rest_audit",
                device,
                write = name,
                value,
                outcome,
                detail,
                "rest write audit"
            );
        };
        let d = match self.find_enabled(device) {
            Ok(d) => d,
            Err(e) => {
                audit("rejected", &e.to_string());
                return Err(e);
            }
        };
        let binding = match d.config.writes.iter().find(|w| w.name == name) {
            Some(b) => b.clone(),
            None => {
                let e = RestError::NotFound(format!(
                    "unknown write binding '{name}' on device '{device}'"
                ));
                audit("rejected", &e.to_string());
                return Err(e);
            }
        };
        if let Err(e) = check_write_allowed(self.settings.allow_write, &binding, value) {
            audit("rejected", &e.to_string());
            return Err(e);
        }
        if let Err(e) = self.guard_breaker(d).await {
            audit("rejected", &e.to_string());
            return Err(e);
        }

        let url = format!("{}{}", d.config.base_url, binding.path);
        let body = render_body_template(&binding.body_template, value);
        let req = match binding.method.as_str() {
            "PUT" => d.client.put(&url),
            "PATCH" => d.client.patch(&url),
            _ => d.client.post(&url),
        };
        let req = self
            .apply_auth(d, req)
            .header("content-type", "application/json")
            .body(body);
        let result = async {
            let resp = req.send().await.map_err(|e| e.to_string())?;
            let status = resp.status();
            let text = resp.text().await.map_err(|e| e.to_string())?;
            if !status.is_success() {
                return Err(format!("HTTP {status}: {}", truncate(&text, 200)));
            }
            Ok(status.as_u16())
        }
        .await;

        let mut breaker = d.breaker.lock().await;
        match result {
            Ok(status) => {
                breaker.record_success();
                audit("executed", &format!("HTTP {status}"));
                Ok(json!({
                    "ok": true,
                    "device": device,
                    "write": name,
                    "value": value,
                    "status": status,
                }))
            }
            Err(e) => {
                breaker.record_failure(Instant::now(), &e);
                audit("failed", &e);
                Err(RestError::Upstream(format!(
                    "rest device '{device}' write '{name}': {e}"
                )))
            }
        }
    }

    /// Spawn one poll task per enabled device with configured points.
    pub async fn start(self: &Arc<Self>) {
        let mut tasks = self.tasks.lock().await;
        if !tasks.is_empty() {
            return;
        }
        for d in &self.devices {
            if !d.config.enabled || d.config.points.is_empty() {
                continue;
            }
            let this = Arc::clone(self);
            let device = Arc::clone(d);
            let interval = device.config.poll_interval_secs.max(1);
            info!(
                device = %device.config.name,
                interval_secs = interval,
                points = device.config.points.len(),
                "rest poll task started"
            );
            tasks.push(tokio::spawn(async move {
                loop {
                    this.poll_device(&device).await;
                    tokio::time::sleep(Duration::from_secs(interval)).await;
                }
            }));
        }
    }

    pub async fn stop(&self) {
        for handle in self.tasks.lock().await.drain(..) {
            handle.abort();
        }
    }

    async fn poll_device(self: &Arc<Self>, d: &Arc<DeviceRuntime>) {
        let names: Vec<String> = d
            .config
            .points
            .iter()
            .map(|p| p.point_name.clone())
            .collect();
        for point in names {
            let row = match self.read_point(&d.config.name, &point).await {
                Ok(mut row) => {
                    row["error"] = Value::Null;
                    row
                }
                Err(e) => json!({
                    "device": d.config.name,
                    "point": point,
                    "value": Value::Null,
                    "ts": unix_ts(),
                    "error": e.to_string(),
                }),
            };
            d.last_values.lock().await.insert(point, row);
        }
    }

    /// Last polled rows across all devices (consumed by the MQTT bridge).
    pub async fn last_values(&self) -> Vec<Value> {
        let mut out = Vec::new();
        for d in &self.devices {
            out.extend(d.last_values.lock().await.values().cloned());
        }
        out
    }
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        return s.to_string();
    }
    let mut end = max;
    while end > 0 && !s.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}…", &s[..end])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn binding(enabled: bool) -> RestWriteBinding {
        RestWriteBinding {
            name: "chw_setpoint".into(),
            enabled,
            method: "POST".into(),
            path: "/points/chw_setpoint".into(),
            body_template: r#"{"value": {{value}}, "priority": 8}"#.into(),
            value_min: Some(40.0),
            value_max: Some(55.0),
        }
    }

    #[test]
    fn select_json_dotted_path() {
        let body = json!({"value": 54.2, "meta": {"units": "°F"}, "items": [{"v": 7}]});
        assert_eq!(select_json(&body, "$.value").unwrap(), json!(54.2));
        assert_eq!(select_json(&body, "$.meta.units").unwrap(), json!("°F"));
        assert_eq!(select_json(&body, "$.items[0].v").unwrap(), json!(7));
        assert_eq!(select_json(&body, "$").unwrap(), body);
        assert!(select_json(&body, "$.missing").is_err());
        assert!(select_json(&body, "$.items[9].v").is_err());
    }

    #[test]
    fn value_coercion_and_scale_types() {
        assert_eq!(value_as_f64(&json!(1.5)), Some(1.5));
        assert_eq!(value_as_f64(&json!(true)), Some(1.0));
        assert_eq!(value_as_f64(&json!("42.5")), Some(42.5));
        assert_eq!(value_as_f64(&json!({"nested": 1})), None);
    }

    #[test]
    fn body_template_renders_value() {
        let b = binding(true);
        assert_eq!(
            render_body_template(&b.body_template, 44.0),
            r#"{"value": 44, "priority": 8}"#
        );
        assert_eq!(
            render_body_template(&b.body_template, 44.5),
            r#"{"value": 44.5, "priority": 8}"#
        );
    }

    #[test]
    fn write_fails_closed_globally() {
        let err = check_write_allowed(false, &binding(true), 45.0).unwrap_err();
        assert!(matches!(err, RestError::Forbidden(_)));
    }

    #[test]
    fn write_fails_closed_per_binding() {
        let err = check_write_allowed(true, &binding(false), 45.0).unwrap_err();
        assert!(matches!(err, RestError::Forbidden(_)));
    }

    #[test]
    fn write_bounds_enforced() {
        assert!(check_write_allowed(true, &binding(true), 45.0).is_ok());
        assert!(matches!(
            check_write_allowed(true, &binding(true), 39.0).unwrap_err(),
            RestError::BadRequest(_)
        ));
        assert!(matches!(
            check_write_allowed(true, &binding(true), 56.0).unwrap_err(),
            RestError::BadRequest(_)
        ));
    }

    #[test]
    fn breaker_opens_after_consecutive_failures() {
        let mut b = CircuitBreaker::default();
        let now = Instant::now();
        b.record_failure(now, "timeout");
        b.record_failure(now, "timeout");
        assert!(!b.is_open(now));
        b.record_failure(now, "timeout");
        assert!(b.is_open(now));
        // Half-open after the backoff window elapses.
        assert!(!b.is_open(now + Duration::from_secs(6)));
        // Success resets everything.
        b.record_success();
        assert_eq!(b.consecutive_failures, 0);
        assert!(!b.is_open(now));
    }

    #[test]
    fn breaker_backoff_grows_and_caps() {
        assert_eq!(backoff_secs(0), 0);
        assert_eq!(backoff_secs(2), 0);
        assert_eq!(backoff_secs(3), 5);
        assert_eq!(backoff_secs(4), 10);
        assert_eq!(backoff_secs(5), 20);
        assert_eq!(backoff_secs(60), BREAKER_MAX_BACKOFF_SECS);
    }

    #[test]
    fn missing_env_fails_loudly_for_enabled_device() {
        std::env::remove_var("OPENFDD_REST_TOKEN_TEST_MISSING");
        let device = RestDevice {
            name: "unit-test".into(),
            enabled: true,
            base_url: "https://127.0.0.1:8443/api".into(),
            auth: RestAuth::Bearer,
            token_env: Some("OPENFDD_REST_TOKEN_TEST_MISSING".into()),
            api_key_header: "X-API-Key".into(),
            basic_username: None,
            tls_verify: true,
            timeout_secs: 10,
            poll_interval_secs: 60,
            points: vec![],
            writes: vec![],
        };
        let err = RestClientService::from_config(RestSettings::default(), vec![device.clone()])
            .err()
            .expect("must fail loudly");
        assert!(err.contains("OPENFDD_REST_TOKEN_TEST_MISSING"), "{err}");

        // The same device disabled must not require the secret.
        let disabled = RestDevice {
            enabled: false,
            ..device
        };
        assert!(RestClientService::from_config(RestSettings::default(), vec![disabled]).is_ok());
    }

    #[tokio::test]
    async fn write_403_when_disabled() {
        std::env::set_var("OPENFDD_REST_TOKEN_UNIT_WRITE", "secret");
        let device = RestDevice {
            name: "unit-write".into(),
            enabled: true,
            base_url: "https://127.0.0.1:9".into(),
            auth: RestAuth::Bearer,
            token_env: Some("OPENFDD_REST_TOKEN_UNIT_WRITE".into()),
            api_key_header: "X-API-Key".into(),
            basic_username: None,
            tls_verify: true,
            timeout_secs: 1,
            poll_interval_secs: 60,
            points: vec![],
            writes: vec![binding(false)],
        };
        // allow_write=false globally → Forbidden even before binding check.
        let svc =
            RestClientService::from_config(RestSettings::default(), vec![device.clone()]).unwrap();
        let err = svc
            .write("unit-write", "chw_setpoint", 45.0)
            .await
            .unwrap_err();
        assert!(matches!(err, RestError::Forbidden(_)), "{err}");

        // allow_write=true but binding disabled → still Forbidden (fail closed).
        let settings = RestSettings {
            allow_write: true,
            ..RestSettings::default()
        };
        let svc = RestClientService::from_config(settings, vec![device]).unwrap();
        let err = svc
            .write("unit-write", "chw_setpoint", 45.0)
            .await
            .unwrap_err();
        assert!(matches!(err, RestError::Forbidden(_)), "{err}");
    }

    #[tokio::test]
    async fn raw_get_rejects_absolute_and_traversal_paths() {
        std::env::set_var("OPENFDD_REST_TOKEN_UNIT_PATHS", "secret");
        let device = RestDevice {
            name: "unit-paths".into(),
            enabled: true,
            base_url: "https://127.0.0.1:9".into(),
            auth: RestAuth::Bearer,
            token_env: Some("OPENFDD_REST_TOKEN_UNIT_PATHS".into()),
            api_key_header: "X-API-Key".into(),
            basic_username: None,
            tls_verify: true,
            timeout_secs: 1,
            poll_interval_secs: 60,
            points: vec![],
            writes: vec![],
        };
        let svc = RestClientService::from_config(RestSettings::default(), vec![device]).unwrap();
        for bad in [
            "https://evil.example/steal",
            "//evil.example/steal",
            "points/no-leading-slash",
            "/points/../../admin",
            "",
        ] {
            let err = svc.raw_get("unit-paths", bad).await.unwrap_err();
            assert!(
                matches!(err, RestError::BadRequest(_)),
                "path {bad:?}: {err}"
            );
        }
    }
}
