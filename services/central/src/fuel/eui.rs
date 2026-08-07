//! Static peer EUI table (EPA Portfolio Manager national medians + CBECS fallback).

use serde_json::{json, Value};

#[derive(Debug, Clone, Copy)]
struct PeerRow {
    property_type: &'static str,
    p20: f64,
    p50: f64,
    p80: f64,
    benchmark_name: &'static str,
    source: &'static str,
    confidence: &'static str,
}

const PEERS: &[PeerRow] = &[
    PeerRow {
        property_type: "office",
        p20: 34.0,
        p50: 52.9,
        p80: 71.0,
        benchmark_name: "epa_pm_national_median",
        source: "EPA Portfolio Manager U.S. national median site EUI",
        confidence: "high",
    },
    PeerRow {
        property_type: "k12_school",
        p20: 31.0,
        p50: 48.5,
        p80: 65.0,
        benchmark_name: "epa_pm_national_median",
        source: "EPA Portfolio Manager U.S. national median site EUI",
        confidence: "high",
    },
    PeerRow {
        property_type: "retail_store",
        p20: 33.0,
        p50: 51.4,
        p80: 69.0,
        benchmark_name: "epa_pm_national_median",
        source: "EPA Portfolio Manager U.S. national median site EUI",
        confidence: "high",
    },
    PeerRow {
        property_type: "hospital",
        p20: 139.0,
        p50: 214.2,
        p80: 289.0,
        benchmark_name: "epa_pm_national_median",
        source: "EPA Portfolio Manager U.S. national median site EUI",
        confidence: "high",
    },
    PeerRow {
        property_type: "hotel",
        p20: 41.0,
        p50: 63.0,
        p80: 85.0,
        benchmark_name: "epa_pm_national_median",
        source: "EPA Portfolio Manager U.S. national median site EUI",
        confidence: "high",
    },
    PeerRow {
        property_type: "warehouse_nonrefrigerated",
        p20: 15.0,
        p50: 22.7,
        p80: 31.0,
        benchmark_name: "epa_pm_national_median",
        source: "EPA Portfolio Manager U.S. national median site EUI",
        confidence: "high",
    },
    PeerRow {
        property_type: "commercial_all",
        p20: 46.0,
        p50: 70.6,
        p80: 95.0,
        benchmark_name: "cbecs_2018_average",
        source: "EIA CBECS 2018 average U.S. commercial-building site energy intensity",
        confidence: "high",
    },
];

const FALLBACK: &str = "commercial_all";

pub fn normalize_property_type(property_type: &str) -> String {
    let key = property_type
        .trim()
        .to_ascii_lowercase()
        .replace(' ', "_")
        .replace('-', "_");
    match key.as_str() {
        "office" | "offices" | "office_building" => "office".into(),
        "school" | "k_12" | "k12" | "k12_school" | "primary_school" | "secondary_school" => {
            "k12_school".into()
        }
        "retail" | "retail_store" | "store" => "retail_store".into(),
        "hospital" | "healthcare" => "hospital".into(),
        "hotel" | "lodging" => "hotel".into(),
        "warehouse" | "warehouse_nonrefrigerated" => "warehouse_nonrefrigerated".into(),
        other => other.to_string(),
    }
}

fn lookup(property_type: &str) -> (PeerRow, &'static str) {
    let norm = normalize_property_type(property_type);
    if let Some(r) = PEERS.iter().find(|r| r.property_type == norm) {
        return (*r, "exact");
    }
    let fb = PEERS
        .iter()
        .find(|r| r.property_type == FALLBACK)
        .copied()
        .expect("commercial_all peer row");
    (fb, "fallback_commercial_all")
}

/// Compare a site EUI (kBtu/ft²·yr) against its peer-group band.
pub fn compare_eui(site_eui_kbtu_ft2: f64, property_type: &str) -> Value {
    let (bm, matched) = lookup(property_type);
    let eui = site_eui_kbtu_ft2;
    let band = if eui < bm.p20 {
        "below_p20"
    } else if eui > bm.p80 {
        "above_p80"
    } else {
        "within_band"
    };
    json!({
        "site_eui_kbtu_ft2": (eui * 10.0).round() / 10.0,
        "property_type": normalize_property_type(property_type),
        "property_type_matched": matched,
        "benchmark_name": bm.benchmark_name,
        "p20": bm.p20,
        "p50": bm.p50,
        "p80": bm.p80,
        "vs_median_pct": ((eui - bm.p50) / bm.p50 * 1000.0).round() / 10.0,
        "band": band,
        "source": bm.source,
        "confidence": bm.confidence,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn office_peers() {
        let c = compare_eui(52.9, "office");
        assert_eq!(c["band"], "within_band");
        assert_eq!(c["p50"], 52.9);
        assert_eq!(c["p20"], 34.0);
        assert_eq!(c["p80"], 71.0);
    }

    #[test]
    fn fallback_unknown_type() {
        let c = compare_eui(80.0, "data_center_unknown");
        assert_eq!(c["property_type_matched"], "fallback_commercial_all");
        assert_eq!(c["p50"], 70.6);
    }
}
