//! Open-Meteo weather fetch + BACnet mirror (mirrors `app/weather.py`).

use std::sync::atomic::{AtomicBool, Ordering};

use std::sync::Arc;

use chrono::{DateTime, Utc};
use reqwest::Client;
use serde_json::{json, Value};
use tokio::sync::Mutex;
use tracing::warn;

use crate::config::Settings;
use crate::services::bacnet_server::BacnetServerManager;

const AV_TEMP: u32 = 9101;
const AV_RH: u32 = 9102;
const AV_DP: u32 = 9103;
const AV_WIND: u32 = 9104;
const CSV_LOC: u32 = 9105;
const BI_APP_FAULT: u32 = 9106;
const CSV_LAST_UPDATED: u32 = 9107;

#[derive(Debug, Clone)]
pub(crate) struct WeatherReading {
    temp_f: f64,
    humidity: f64,
    wind_mph: f64,
    dewpoint_f: f64,
    location: String,
    timezone: String,
    from_api: bool,
    reason: String,
    updated_at: String,
}

pub struct WeatherService {
    settings: Settings,
    bacnet: Arc<BacnetServerManager>,
    cache: Mutex<Option<WeatherReading>>,
    stop: AtomicBool,
    task: Mutex<Option<tokio::task::JoinHandle<()>>>,
}

impl WeatherService {
    pub fn new(settings: Settings, bacnet: Arc<BacnetServerManager>) -> Self {
        Self {
            settings,
            bacnet,
            cache: Mutex::new(None),
            stop: AtomicBool::new(false),
            task: Mutex::new(None),
        }
    }

    pub async fn to_dict(&self) -> Value {
        match self.cache.lock().await.as_ref() {
            None => json!({ "ok": false, "reason": "no data yet" }),
            Some(c) => json!({
                "ok": true,
                "temp_f": c.temp_f,
                "humidity": c.humidity,
                "wind_mph": c.wind_mph,
                "dewpoint_f": c.dewpoint_f,
                "location": c.location,
                "timezone": c.timezone,
                "from_api": c.from_api,
                "reason": c.reason,
                "updated_at": c.updated_at,
                "last_updated_label": human_weather_timestamp(c),
            }),
        }
    }

    pub async fn start(self: &std::sync::Arc<Self>) -> Result<(), String> {
        self.bacnet.write_binary_active(BI_APP_FAULT, true).await?;
        let fallback = self.fallback("startup");
        *self.cache.lock().await = Some(fallback.clone());
        self.mirror_to_bacnet(&fallback).await?;
        self.stop.store(false, Ordering::SeqCst);
        let this = std::sync::Arc::clone(self);
        *self.task.lock().await = Some(tokio::spawn(async move {
            this.loop_task().await;
        }));
        Ok(())
    }

    pub async fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(h) = self.task.lock().await.take() {
            h.abort();
            let _ = h.await;
        }
    }

    pub async fn refresh_now(&self) -> Result<Value, String> {
        let reading = self.poll_once().await?;
        *self.cache.lock().await = Some(reading.clone());
        self.mirror_to_bacnet(&reading).await?;
        Ok(json!({
            "ok": true,
            "temp_f": reading.temp_f,
            "humidity": reading.humidity,
            "wind_mph": reading.wind_mph,
            "dewpoint_f": reading.dewpoint_f,
            "location": reading.location,
            "timezone": reading.timezone,
            "from_api": reading.from_api,
            "reason": reading.reason,
            "updated_at": reading.updated_at,
            "last_updated_label": human_weather_timestamp(&reading),
        }))
    }

    async fn loop_task(self: std::sync::Arc<Self>) {
        let interval = self.settings.weather.interval_secs.max(60);
        while !self.stop.load(Ordering::SeqCst) {
            match self.poll_once().await {
                Ok(reading) => {
                    *self.cache.lock().await = Some(reading.clone());
                    if let Err(e) = self.mirror_to_bacnet(&reading).await {
                        warn!("weather mirror failed: {e}");
                    }
                }
                Err(e) => {
                    warn!("weather poll failed: {e}");
                    let fb = self.fallback(&e);
                    *self.cache.lock().await = Some(fb.clone());
                    let _ = self.mirror_to_bacnet(&fb).await;
                }
            }
            let mut elapsed = 0u64;
            while elapsed < interval && !self.stop.load(Ordering::SeqCst) {
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                elapsed += 1;
            }
        }
    }

    async fn mirror_to_bacnet(&self, r: &WeatherReading) -> Result<(), String> {
        use bacnet_types::primitives::PropertyValue;
        let stamp = human_weather_timestamp(r);
        let source = if r.from_api {
            "Open-Meteo live"
        } else {
            "fallback (Open-Meteo unavailable)"
        };

        self.bacnet
            .write_present_value("AV", AV_TEMP, PropertyValue::Real(r.temp_f as f32))
            .await?;
        self.bacnet
            .write_description(
                "AV",
                AV_TEMP,
                &format!(
                    "Open-Meteo outdoor air temperature — {:.1} °F ({source}; {stamp})",
                    r.temp_f
                ),
            )
            .await?;

        self.bacnet
            .write_present_value("AV", AV_RH, PropertyValue::Real(r.humidity as f32))
            .await?;
        self.bacnet
            .write_description(
                "AV",
                AV_RH,
                &format!(
                    "Open-Meteo outdoor relative humidity — {:.0}% ({source}; {stamp})",
                    r.humidity
                ),
            )
            .await?;

        self.bacnet
            .write_present_value("AV", AV_WIND, PropertyValue::Real(r.wind_mph as f32))
            .await?;
        self.bacnet
            .write_description(
                "AV",
                AV_WIND,
                &format!(
                    "Open-Meteo outdoor wind speed — {:.1} mph ({source}; {stamp})",
                    r.wind_mph
                ),
            )
            .await?;

        self.bacnet
            .write_present_value("AV", AV_DP, PropertyValue::Real(r.dewpoint_f as f32))
            .await?;
        self.bacnet
            .write_description(
                "AV",
                AV_DP,
                &format!(
                    "Open-Meteo outdoor dewpoint — {:.1} °F ({source}; {stamp})",
                    r.dewpoint_f
                ),
            )
            .await?;

        self.bacnet
            .write_present_value(
                "CSV",
                CSV_LOC,
                PropertyValue::CharacterString(r.location.clone()),
            )
            .await?;
        self.bacnet
            .write_description(
                "CSV",
                CSV_LOC,
                &format!("Open-Meteo geocoded location — {} ({stamp})", r.location),
            )
            .await?;

        self.bacnet
            .write_present_value(
                "CSV",
                CSV_LAST_UPDATED,
                PropertyValue::CharacterString(stamp.clone()),
            )
            .await?;
        self.bacnet
            .write_description(
                "CSV",
                CSV_LAST_UPDATED,
                &format!(
                    "Human-readable timestamp of last weather mirror ({source}; tz {})",
                    r.timezone
                ),
            )
            .await?;

        self.bacnet
            .write_binary_active(BI_APP_FAULT, !r.from_api)
            .await?;
        let fault_desc = if r.from_api {
            format!("Inactive — weather data is live from Open-Meteo ({stamp})")
        } else {
            format!("Active — weather data is fallback, not live Open-Meteo ({stamp})")
        };
        self.bacnet
            .write_description("BV", BI_APP_FAULT, &fault_desc)
            .await?;
        Ok(())
    }

    fn fallback(&self, reason: &str) -> WeatherReading {
        let cfg = &self.settings.weather;
        let dp = dewpoint_f_from_db_rh(cfg.fallback_temp_f, cfg.fallback_humidity);
        WeatherReading {
            temp_f: cfg.fallback_temp_f,
            humidity: cfg.fallback_humidity,
            wind_mph: cfg.fallback_wind_mph,
            dewpoint_f: dp,
            location: format!("{} (fallback)", cfg.city),
            timezone: "UTC".into(),
            from_api: false,
            reason: reason.to_string(),
            updated_at: Utc::now().to_rfc3339(),
        }
    }

    async fn poll_once(&self) -> Result<WeatherReading, String> {
        let cfg = &self.settings.weather;
        let client = Client::builder()
            .timeout(std::time::Duration::from_secs_f64(cfg.http_timeout_secs))
            .build()
            .map_err(|e| e.to_string())?;
        let loc = geocode_city(&client, &cfg.city).await?;
        let weather = fetch_current(&client, &loc).await?;
        let cur = &weather["current"];
        let temp_f = cur["temperature_2m"]
            .as_f64()
            .unwrap_or(cfg.fallback_temp_f);
        let humidity = cur["relative_humidity_2m"]
            .as_f64()
            .unwrap_or(cfg.fallback_humidity);
        let wind = cur["wind_speed_10m"]
            .as_f64()
            .unwrap_or(cfg.fallback_wind_mph);
        let dp = if humidity > 0.0 {
            dewpoint_f_from_db_rh(temp_f, humidity)
        } else {
            cur["dew_point_2m"]
                .as_f64()
                .unwrap_or_else(|| dewpoint_f_from_db_rh(temp_f, cfg.fallback_humidity))
        };
        let label = format!(
            "{}, {} {}",
            loc["name"].as_str().unwrap_or(&cfg.city),
            loc["admin1"].as_str().unwrap_or(""),
            loc["country"].as_str().unwrap_or("")
        )
        .trim()
        .to_string();
        Ok(WeatherReading {
            temp_f,
            humidity,
            wind_mph: wind,
            dewpoint_f: dp,
            location: label,
            timezone: loc["timezone"].as_str().unwrap_or("UTC").to_string(),
            from_api: true,
            reason: "ok".into(),
            updated_at: Utc::now().to_rfc3339(),
        })
    }
}

/// Human-readable BACnet label for weather-last-updated (CSV:9107).
pub fn human_weather_timestamp(r: &WeatherReading) -> String {
    let dt = DateTime::parse_from_rfc3339(&r.updated_at)
        .map(|d| d.with_timezone(&Utc))
        .unwrap_or_else(|_| Utc::now());
    let source = if r.from_api { "Open-Meteo" } else { "fallback" };
    format!(
        "Weather updated {} ({}; local tz: {})",
        dt.format("%B %d, %Y at %I:%M %p UTC"),
        source,
        r.timezone
    )
}

pub fn dewpoint_f_from_db_rh(temp_f: f64, rh_percent: f64) -> f64 {
    let t_c = (temp_f - 32.0) * 5.0 / 9.0;
    let rh = rh_percent.clamp(0.1, 100.0);
    let a = 17.27;
    let b = 237.7;
    let alpha = (a * t_c) / (b + t_c) + (rh / 100.0).ln();
    let dp_c = (b * alpha) / (a - alpha);
    dp_c * 9.0 / 5.0 + 32.0
}

async fn geocode_search(client: &Client, name: &str, count: u32) -> Result<Vec<Value>, String> {
    let url = format!(
        "https://geocoding-api.open-meteo.com/v1/search?name={}&count={}&language=en&format=json",
        pct_encode(name.trim()),
        count
    );
    let r = client.get(&url).send().await.map_err(|e| e.to_string())?;
    let body: Value = r.json().await.map_err(|e| e.to_string())?;
    Ok(body["results"].as_array().cloned().unwrap_or_default())
}

async fn geocode_city(client: &Client, city: &str) -> Result<Value, String> {
    let city = city.trim();
    let results = geocode_search(client, city, 1).await?;
    if let Some(first) = results.into_iter().next() {
        return Ok(first);
    }
    let normalized = city.replace(',', " ");
    let parts: Vec<_> = normalized.split_whitespace().collect();
    if parts.len() >= 2 {
        let candidates = geocode_search(client, parts[0], 10).await?;
        let hint = parts[1..].join(" ").to_ascii_lowercase();
        for c in &candidates {
            let admin = c["admin1"].as_str().unwrap_or("").to_ascii_lowercase();
            if !admin.is_empty()
                && (admin == hint || hint.contains(&admin) || admin.contains(&hint))
            {
                return Ok(c.clone());
            }
        }
        if let Some(first) = candidates.into_iter().next() {
            return Ok(first);
        }
    }
    Err(format!("no geocode result for city '{city}'"))
}

async fn fetch_current(client: &Client, loc: &Value) -> Result<Value, String> {
    let tz = loc["timezone"].as_str().unwrap_or("auto");
    let url = format!(
        "https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,dew_point_2m&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone={}",
        loc["latitude"].as_f64().unwrap_or(0.0),
        loc["longitude"].as_f64().unwrap_or(0.0),
        pct_encode(tz),
    );
    let r = client.get(&url).send().await.map_err(|e| e.to_string())?;
    r.json().await.map_err(|e| e.to_string())
}

fn pct_encode(input: &str) -> String {
    let mut out = String::new();
    for b in input.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            b' ' => out.push('+'),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dewpoint_magnus() {
        let dp = dewpoint_f_from_db_rh(70.0, 50.0);
        assert!(dp > 45.0 && dp < 55.0);
    }

    #[test]
    fn human_weather_timestamp_is_readable() {
        let r = WeatherReading {
            temp_f: 70.0,
            humidity: 50.0,
            wind_mph: 0.0,
            dewpoint_f: 50.0,
            location: "Madison".into(),
            timezone: "America/Chicago".into(),
            from_api: true,
            reason: "ok".into(),
            updated_at: "2026-07-09T14:32:00Z".into(),
        };
        let label = human_weather_timestamp(&r);
        assert!(label.contains("Open-Meteo"));
        assert!(label.contains("July"));
        assert!(label.contains("America/Chicago"));
    }
}
