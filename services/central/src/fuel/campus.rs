//! Campus model + annual EUI summary (vibe20 `wattlab.benchmarks.meters`).

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::bills::{load_bill_csv, BillRow};

pub const KBTU_PER_KWH: f64 = 3.412;
pub const KBTU_PER_MCF: f64 = 1037.0;
pub const THERMS_PER_MCF: f64 = 10.37;

pub const ALLOCATION_AREA_WEIGHTED: &str = "area_weighted";
pub const ALLOCATION_EQUAL: &str = "equal";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BuildingRef {
    pub building_id: String,
    pub label: String,
    pub floor_area_ft2: f64,
    #[serde(default = "default_office")]
    pub property_type: String,
}

fn default_office() -> String {
    "office".into()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeterAllocation {
    #[serde(default)]
    pub method: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeterSpec {
    pub meter_id: String,
    pub fuel: String,
    #[serde(default)]
    pub unit: Option<String>,
    pub file: String,
    #[serde(default)]
    pub serves: Vec<String>,
    #[serde(default)]
    pub allocation: Option<MeterAllocation>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CampusDoc {
    pub campus_id: String,
    #[serde(default)]
    pub label: Option<String>,
    #[serde(default)]
    pub notes: Option<String>,
    #[serde(default)]
    pub lat: Option<f64>,
    #[serde(default)]
    pub lon: Option<f64>,
    #[serde(default, alias = "siteRef", alias = "site_ref")]
    pub site_ref: Option<String>,
    #[serde(default)]
    pub buildings: Vec<BuildingRef>,
    #[serde(default)]
    pub meters: Vec<MeterSpec>,
}

#[derive(Debug, Clone)]
pub struct Meter {
    pub meter_id: String,
    pub fuel: String,
    pub unit: String,
    pub serves: Vec<String>,
    pub bills: Vec<BillRow>,
    #[allow(dead_code)]
    pub allocation: HashMap<String, Value>,
}

impl Meter {
    pub fn shared(&self) -> bool {
        self.serves.len() > 1
    }

    pub fn months(&self) -> std::collections::BTreeSet<String> {
        self.bills.iter().map(|b| b.month.clone()).collect()
    }

    pub fn usage_in(&self, window: &[String]) -> f64 {
        let set: std::collections::HashSet<&str> = window.iter().map(|s| s.as_str()).collect();
        self.bills
            .iter()
            .filter(|b| set.contains(b.month.as_str()))
            .map(|b| b.usage)
            .sum()
    }

    pub fn cost_in(&self, window: &[String]) -> f64 {
        let set: std::collections::HashSet<&str> = window.iter().map(|s| s.as_str()).collect();
        self.bills
            .iter()
            .filter(|b| set.contains(b.month.as_str()))
            .filter_map(|b| b.cost_usd)
            .sum()
    }
}

#[derive(Debug, Clone)]
pub struct Campus {
    pub campus_id: String,
    pub label: String,
    pub buildings: Vec<BuildingRef>,
    pub meters: Vec<Meter>,
    pub notes: String,
    pub source: PathBuf,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    pub site_ref: Option<String>,
}

impl Campus {
    pub fn total_area_ft2(&self) -> f64 {
        self.buildings.iter().map(|b| b.floor_area_ft2).sum()
    }

    pub fn building(&self, building_id: &str) -> Result<&BuildingRef> {
        self.buildings
            .iter()
            .find(|b| b.building_id == building_id)
            .with_context(|| format!("unknown building_id {building_id}"))
    }

    pub fn meta_json(&self) -> Value {
        json!({
            "campus_id": self.campus_id,
            "label": self.label,
            "notes": self.notes,
            "lat": self.lat,
            "lon": self.lon,
            "site_ref": self.site_ref,
            "source": self.source.display().to_string(),
            "buildings": self.buildings,
            "meters": self.meters.iter().map(|m| json!({
                "meter_id": m.meter_id,
                "fuel": m.fuel,
                "unit": m.unit,
                "serves": m.serves,
                "shared": m.shared(),
                "n_months": m.bills.len(),
            })).collect::<Vec<_>>(),
            "total_area_ft2": self.total_area_ft2(),
        })
    }
}

/// Load campus.json + sibling bill CSVs from a directory (or path to campus.json).
pub fn load_campus(dir_or_json: &Path) -> Result<Campus> {
    let json_path = if dir_or_json.is_file() {
        dir_or_json.to_path_buf()
    } else {
        dir_or_json.join("campus.json")
    };
    if !json_path.is_file() {
        bail!(
            "Campus config not found: {}. Expected campus.json + sibling bill CSVs.",
            json_path.display()
        );
    }
    let parent = json_path
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let raw = std::fs::read_to_string(&json_path)
        .with_context(|| format!("read {}", json_path.display()))?;
    let doc: CampusDoc = serde_json::from_str(&raw)
        .with_context(|| format!("parse campus.json {}", json_path.display()))?;

    let mut meters = Vec::with_capacity(doc.meters.len());
    for m in &doc.meters {
        let bill_path = parent.join(&m.file);
        if !bill_path.is_file() {
            bail!(
                "Campus {} references missing bill CSV: {}",
                doc.campus_id,
                m.file
            );
        }
        let unit = m.unit.clone().unwrap_or_else(|| {
            if m.fuel.eq_ignore_ascii_case("electricity") {
                "kwh".into()
            } else {
                "mcf".into()
            }
        });
        let mut allocation = HashMap::new();
        if let Some(a) = &m.allocation {
            if let Some(method) = &a.method {
                allocation.insert("method".into(), json!(method));
            }
        }
        meters.push(Meter {
            meter_id: m.meter_id.clone(),
            fuel: m.fuel.clone(),
            unit,
            serves: m.serves.clone(),
            bills: load_bill_csv(&bill_path)?,
            allocation,
        });
    }

    Ok(Campus {
        campus_id: doc.campus_id.clone(),
        label: doc.label.unwrap_or_else(|| doc.campus_id.clone()),
        buildings: doc.buildings,
        meters,
        notes: doc.notes.unwrap_or_default(),
        source: json_path,
        lat: doc.lat,
        lon: doc.lon,
        site_ref: doc.site_ref,
    })
}

fn month_index(month: &str) -> Option<i32> {
    let mut parts = month.split('-');
    let y: i32 = parts.next()?.parse().ok()?;
    let m: i32 = parts.next()?.parse().ok()?;
    Some(y * 12 + m - 1)
}

fn month_str(idx: i32) -> String {
    format!("{:04}-{:02}", idx / 12, idx % 12 + 1)
}

/// Latest run of `months` consecutive months present in every set.
pub fn latest_complete_window(
    month_sets: &[std::collections::BTreeSet<String>],
    months: usize,
) -> Option<Vec<String>> {
    if month_sets.is_empty() || months == 0 {
        return None;
    }
    let mut common = month_sets[0].clone();
    for s in &month_sets[1..] {
        common = common.intersection(s).cloned().collect();
    }
    let mut ends: Vec<_> = common.iter().cloned().collect();
    ends.sort();
    ends.reverse();
    for end in ends {
        let end_idx = month_index(&end)?;
        // Want end_idx-(months-1) .. end_idx inclusive.
        let seq: Vec<String> = (0..months as i32)
            .map(|i| month_str(end_idx - (months as i32 - 1 - i)))
            .collect();
        if seq.iter().all(|m| common.contains(m)) {
            return Some(seq);
        }
    }
    None
}

fn building_shares(
    campus: &Campus,
    meter: &Meter,
    method: &str,
    window: &[String],
) -> Result<HashMap<String, f64>> {
    let served = &meter.serves;
    if served.is_empty() {
        bail!("meter {} has empty serves", meter.meter_id);
    }
    if !meter.shared() {
        return Ok(HashMap::from([(served[0].clone(), 1.0)]));
    }
    match method {
        ALLOCATION_EQUAL => {
            let share = 1.0 / served.len() as f64;
            Ok(served.iter().cloned().map(|b| (b, share)).collect())
        }
        ALLOCATION_AREA_WEIGHTED => {
            let mut areas = HashMap::new();
            let mut total = 0.0;
            for b in served {
                let a = campus.building(b)?.floor_area_ft2;
                areas.insert(b.clone(), a);
                total += a;
            }
            if total <= 0.0 {
                bail!("area_weighted allocation needs positive floor area");
            }
            Ok(areas.into_iter().map(|(b, a)| (b, a / total)).collect())
        }
        "gas_share" => {
            let mut gas_use: HashMap<String, f64> =
                served.iter().cloned().map(|b| (b, 0.0)).collect();
            for m in &campus.meters {
                if m.fuel.eq_ignore_ascii_case("gas") && !m.shared() {
                    if let Some(bid) = m.serves.first() {
                        if let Some(slot) = gas_use.get_mut(bid) {
                            *slot += m.usage_in(window);
                        }
                    }
                }
            }
            let total: f64 = gas_use.values().sum();
            if total <= 0.0 {
                return building_shares(campus, meter, ALLOCATION_AREA_WEIGHTED, window);
            }
            Ok(gas_use.into_iter().map(|(b, u)| (b, u / total)).collect())
        }
        other => bail!("unknown allocation method: {other}"),
    }
}

/// Annualized per-building + campus energy/EUI over a common window.
pub fn annual_summary(
    campus: &Campus,
    allocation: &str,
    window: Option<Vec<String>>,
) -> Result<Value> {
    let window = match window {
        Some(w) => w,
        None => {
            let sets: Vec<_> = campus.meters.iter().map(|m| m.months()).collect();
            latest_complete_window(&sets, 12)
                .context("no common complete 12-month window across all meters")?
        }
    };

    let mut per: BTreeMap<String, (f64, f64, f64, f64)> = BTreeMap::new();
    // (kwh, mcf, elec_cost, gas_cost)
    for b in &campus.buildings {
        per.insert(b.building_id.clone(), (0.0, 0.0, 0.0, 0.0));
    }

    for meter in &campus.meters {
        let usage = meter.usage_in(&window);
        let cost = meter.cost_in(&window);
        let shares = building_shares(campus, meter, allocation, &window)?;
        for (bid, share) in shares {
            let slot = per.entry(bid).or_insert((0.0, 0.0, 0.0, 0.0));
            if meter.fuel.eq_ignore_ascii_case("electricity")
                || meter.unit.eq_ignore_ascii_case("kwh")
            {
                slot.0 += usage * share;
                slot.2 += cost * share;
            } else {
                slot.1 += usage * share;
                slot.3 += cost * share;
            }
        }
    }

    let mut rows = Vec::new();
    for b in &campus.buildings {
        let (kwh, mcf, elec_cost, gas_cost) = per.get(&b.building_id).copied().unwrap_or_default();
        let elec_kbtu = kwh * KBTU_PER_KWH;
        let gas_kbtu = mcf * KBTU_PER_MCF;
        let area = b.floor_area_ft2.max(1.0);
        rows.push(json!({
            "building_id": b.building_id,
            "label": b.label,
            "property_type": b.property_type,
            "floor_area_ft2": b.floor_area_ft2,
            "kwh": (kwh * 10.0).round() / 10.0,
            "kwh_per_ft2": (kwh / area * 100.0).round() / 100.0,
            "mcf": (mcf * 10.0).round() / 10.0,
            "therms": (mcf * THERMS_PER_MCF * 10.0).round() / 10.0,
            "elec_kbtu_ft2": (elec_kbtu / area * 10.0).round() / 10.0,
            "gas_kbtu_ft2": (gas_kbtu / area * 10.0).round() / 10.0,
            "site_eui_kbtu_ft2": ((elec_kbtu + gas_kbtu) / area * 10.0).round() / 10.0,
            "elec_cost_usd": (elec_cost * 100.0).round() / 100.0,
            "gas_cost_usd": (gas_cost * 100.0).round() / 100.0,
            "allocation": allocation,
        }));
    }

    let tot_kwh: f64 = rows
        .iter()
        .filter_map(|r| r.get("kwh").and_then(|v| v.as_f64()))
        .sum();
    let tot_mcf: f64 = rows
        .iter()
        .filter_map(|r| r.get("mcf").and_then(|v| v.as_f64()))
        .sum();
    let area = campus.total_area_ft2().max(1.0);
    let campus_row = json!({
        "kwh": (tot_kwh * 10.0).round() / 10.0,
        "mcf": (tot_mcf * 10.0).round() / 10.0,
        "kwh_per_ft2": (tot_kwh / area * 100.0).round() / 100.0,
        "site_eui_kbtu_ft2": ((tot_kwh * KBTU_PER_KWH + tot_mcf * KBTU_PER_MCF) / area * 10.0).round() / 10.0,
        "floor_area_ft2": campus.total_area_ft2(),
        "cost_usd": rows.iter().map(|r| {
            r.get("elec_cost_usd").and_then(|v| v.as_f64()).unwrap_or(0.0)
                + r.get("gas_cost_usd").and_then(|v| v.as_f64()).unwrap_or(0.0)
        }).sum::<f64>(),
    });

    Ok(json!({
        "campus_id": campus.campus_id,
        "window": {
            "start": window.first(),
            "end": window.last(),
            "months": window.len(),
        },
        "allocation": allocation,
        "buildings": rows,
        "campus": campus_row,
    }))
}

/// Convert native usage to site kBtu.
pub fn usage_to_kbtu(usage: f64, fuel: &str, unit: &str) -> f64 {
    let u = unit.to_ascii_lowercase();
    let f = fuel.to_ascii_lowercase();
    if f.starts_with("elec") || u == "kwh" {
        usage * KBTU_PER_KWH
    } else if u == "therm" || u == "therms" {
        usage * 100.0
    } else {
        usage * KBTU_PER_MCF
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fuel")
    }

    #[test]
    fn loads_liberty_campus_and_annual_summary() {
        let dir = fixture_dir();
        if !dir.join("campus.json").is_file() {
            return;
        }
        let campus = load_campus(&dir).expect("load liberty campus");
        assert_eq!(campus.campus_id, "liberty_practice_bensbench");
        assert_eq!(campus.buildings.len(), 2);
        assert_eq!(campus.meters.len(), 3);

        let summary = annual_summary(&campus, ALLOCATION_AREA_WEIGHTED, None).expect("summary");
        let buildings = summary["buildings"].as_array().unwrap();
        assert_eq!(buildings.len(), 2);
        let eui = buildings[0]["site_eui_kbtu_ft2"].as_f64().unwrap();
        assert!(eui > 20.0 && eui < 150.0, "unexpected eui {eui}");
        let campus_eui = summary["campus"]["site_eui_kbtu_ft2"].as_f64().unwrap();
        assert!(campus_eui > 20.0);
    }

    #[test]
    fn latest_window_finds_12() {
        let mk = |months: &[&str]| -> std::collections::BTreeSet<String> {
            months.iter().map(|s| (*s).to_string()).collect()
        };
        let a = mk(&[
            "2020-01", "2020-02", "2020-03", "2020-04", "2020-05", "2020-06", "2020-07", "2020-08",
            "2020-09", "2020-10", "2020-11", "2020-12", "2021-01",
        ]);
        let w = latest_complete_window(&[a.clone(), a], 12).unwrap();
        assert_eq!(w.len(), 12);
        assert_eq!(w[0], "2020-02");
        assert_eq!(w[11], "2021-01");
    }
}
