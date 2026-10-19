//! Offline contractor gate for a new `DataProvider`.
//!
//! A new adapter must parse fixture bytes with no network, then pass
//! [`assert_contractor_samples`]. Roles come from the explicit point map.
//! Display names are decoys and must not resolve. Ace stays `NotImplemented`.

use chrono::{DateTime, Utc};

use super::ace_stub::AceIotStubDriver;
use super::map::{map_provider_samples, PointMapEntry, RawProviderPoint, RoleResolver};
use super::types::{NormalizedSample, ProviderHealthStatus};

#[derive(Debug, Clone)]
pub struct ExpectedSample {
    pub provider_point_id: &'static str,
    pub equipment_id: &'static str,
    pub role: &'static str,
    pub equip_type: Option<&'static str>,
    pub ts: DateTime<Utc>,
    pub val: f64,
    pub unit: Option<&'static str>,
}

/// Map raw points the same way the poller does, then require the expected set.
pub fn assert_contractor_samples(
    raw: &[RawProviderPoint],
    resolver: &RoleResolver,
    building_id: &str,
    provider_instance_id: &str,
    decoy_names: &[&str],
    expected: &[ExpectedSample],
) -> Vec<NormalizedSample> {
    for decoy in decoy_names {
        assert!(
            resolver.resolve(decoy).is_none(),
            "display name {decoy} must not resolve to a role"
        );
        assert!(
            raw.iter().all(|point| point.provider_point_id != *decoy),
            "provider_point_id must not be the display name {decoy}"
        );
    }
    let samples = map_provider_samples(building_id, provider_instance_id, resolver, raw, &[]);
    assert_eq!(samples.len(), expected.len(), "sample count drifted");
    for sample in &samples {
        assert_eq!(sample.building_id, building_id);
        assert_eq!(sample.provider_instance_id, provider_instance_id);
        assert!(!sample.equipment_id.is_empty());
        assert!(!sample.role.is_empty());
        assert!(!sample.provider_point_id.is_empty());
        assert!(sample.val.is_finite());
        assert!(decoy_names.iter().all(|name| sample.role != *name));
        match sample.source_quality.as_deref() {
            None | Some("good" | "uncertain" | "bad" | "stale") => {}
            Some(other) => panic!("non-canonical quality {other}"),
        }
    }
    for want in expected {
        let found = samples.iter().find(|sample| {
            sample.provider_point_id == want.provider_point_id && sample.ts == want.ts
        });
        let Some(sample) = found else {
            panic!("missing {} at {}", want.provider_point_id, want.ts);
        };
        assert_eq!(sample.equipment_id, want.equipment_id);
        assert_eq!(sample.role, want.role);
        assert_eq!(sample.equip_type.as_deref(), want.equip_type);
        assert!(
            (sample.val - want.val).abs() < 1e-9,
            "{} val {} != {}",
            want.provider_point_id,
            sample.val,
            want.val
        );
        assert_eq!(sample.unit.as_deref(), want.unit);
    }
    samples
}

pub fn weather_point_map() -> Vec<PointMapEntry> {
    vec![
        PointMapEntry {
            provider_point_id: "temperature_2m".into(),
            equipment_id: "WEATHER".into(),
            role: "web-outside-air-temp".into(),
            equip_type: Some("weather".into()),
            unit: None,
        },
        PointMapEntry {
            provider_point_id: "relative_humidity_2m".into(),
            equipment_id: "WEATHER".into(),
            role: "web-outside-air-humidity".into(),
            equip_type: Some("weather".into()),
            unit: None,
        },
        PointMapEntry {
            provider_point_id: "dew_point_2m".into(),
            equipment_id: "WEATHER".into(),
            role: "web-outside-air-dewpoint".into(),
            equip_type: Some("weather".into()),
            unit: None,
        },
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::meteo::{parse_hourly_json, MAX_METEO_WINDOW};
    use chrono::TimeZone;

    const FIXTURE: &str = include_str!("fixtures/open_meteo_hourly.json");

    fn utc(y: i32, m: u32, d: u32, h: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, m, d, h, 0, 0).unwrap()
    }

    #[test]
    fn open_meteo_fixture_passes_contractor_conformance() {
        let from = utc(2026, 10, 18, 14);
        let to = utc(2026, 10, 18, 16);
        assert!(to - from <= MAX_METEO_WINDOW);
        let series = [
            "temperature_2m".to_string(),
            "relative_humidity_2m".to_string(),
            "dew_point_2m".to_string(),
        ];
        let raw = parse_hourly_json(FIXTURE, &series, from, to).unwrap();
        let resolver = RoleResolver::from_point_map(&weather_point_map()).unwrap();
        let expected = vec![
            ExpectedSample {
                provider_point_id: "temperature_2m",
                equipment_id: "WEATHER",
                role: "web-outside-air-temp",
                equip_type: Some("weather"),
                ts: utc(2026, 10, 18, 14),
                val: 55.4,
                unit: Some("°F"),
            },
            ExpectedSample {
                provider_point_id: "temperature_2m",
                equipment_id: "WEATHER",
                role: "web-outside-air-temp",
                equip_type: Some("weather"),
                ts: utc(2026, 10, 18, 16),
                val: 57.1,
                unit: Some("°F"),
            },
            ExpectedSample {
                provider_point_id: "relative_humidity_2m",
                equipment_id: "WEATHER",
                role: "web-outside-air-humidity",
                equip_type: Some("weather"),
                ts: utc(2026, 10, 18, 14),
                val: 60.0,
                unit: Some("%"),
            },
            ExpectedSample {
                provider_point_id: "relative_humidity_2m",
                equipment_id: "WEATHER",
                role: "web-outside-air-humidity",
                equip_type: Some("weather"),
                ts: utc(2026, 10, 18, 15),
                val: 61.0,
                unit: Some("%"),
            },
            ExpectedSample {
                provider_point_id: "relative_humidity_2m",
                equipment_id: "WEATHER",
                role: "web-outside-air-humidity",
                equip_type: Some("weather"),
                ts: utc(2026, 10, 18, 16),
                val: 58.0,
                unit: Some("%"),
            },
            ExpectedSample {
                provider_point_id: "dew_point_2m",
                equipment_id: "WEATHER",
                role: "web-outside-air-dewpoint",
                equip_type: Some("weather"),
                ts: utc(2026, 10, 18, 14),
                val: 41.2,
                unit: Some("°F"),
            },
            ExpectedSample {
                provider_point_id: "dew_point_2m",
                equipment_id: "WEATHER",
                role: "web-outside-air-dewpoint",
                equip_type: Some("weather"),
                ts: utc(2026, 10, 18, 15),
                val: 41.5,
                unit: Some("°F"),
            },
            ExpectedSample {
                provider_point_id: "dew_point_2m",
                equipment_id: "WEATHER",
                role: "web-outside-air-dewpoint",
                equip_type: Some("weather"),
                ts: utc(2026, 10, 18, 16),
                val: 42.0,
                unit: Some("°F"),
            },
        ];
        let samples = assert_contractor_samples(
            &raw,
            &resolver,
            "SITE",
            "open_meteo:conformance",
            &["Outside Air Temp", "display_name", "wind_speed_10m"],
            &expected,
        );
        assert!(samples.iter().all(|sample| sample.source_quality.is_none()));
        assert!(raw
            .iter()
            .all(|point| point.provider_point_id != "wind_speed_10m"));
    }

    #[test]
    fn synthetic_provider_uses_the_same_gate() {
        let ts = utc(2026, 10, 18, 12);
        let raw = vec![RawProviderPoint {
            provider_point_id: "series-1".into(),
            display_name: Some("Pretty Name".into()),
            ts,
            val: 70.0,
            unit: Some("°F".into()),
            source_quality: Some("good".into()),
            attrs: serde_json::Map::new(),
        }];
        let resolver = RoleResolver::from_point_map(&[PointMapEntry {
            provider_point_id: "series-1".into(),
            equipment_id: "AHU_1".into(),
            role: "sat".into(),
            equip_type: Some("ahu".into()),
            unit: None,
        }])
        .unwrap();
        let expected = [ExpectedSample {
            provider_point_id: "series-1",
            equipment_id: "AHU_1",
            role: "sat",
            equip_type: Some("ahu"),
            ts,
            val: 70.0,
            unit: Some("°F"),
        }];
        assert_contractor_samples(
            &raw,
            &resolver,
            "SITE",
            "example:synthetic",
            &["Pretty Name"],
            &expected,
        );
    }

    #[test]
    fn ace_stays_not_implemented() {
        let ace = AceIotStubDriver::new("ace_iot:conformance");
        let health = ace.health();
        assert_eq!(health.status, ProviderHealthStatus::NotImplemented);
        assert_eq!(health.kind, super::super::types::ProviderKind::AceIot);
        assert_eq!(ace.provider_id(), "ace_iot:conformance");
    }
}
