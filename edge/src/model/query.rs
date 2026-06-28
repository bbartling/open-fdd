//! Haystack model query layer — SPARQL over the RDF projection of the Haystack grid.

use crate::model::rdf;
use crate::model::sparql;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

const SPARQL_PREFIXES: &str = r#"
PREFIX hs: <https://project-haystack.org/def/>
PREFIX ofdd: <https://open-fdd.dev/model#>
"#;

fn sparql_rows(query: &str) -> Vec<HashMap<String, String>> {
    rdf::sparql_select(query).unwrap_or_default()
}

fn sparql_predefined(id: &str) -> Vec<HashMap<String, String>> {
    sparql::run_predefined(id).unwrap_or_default()
}

fn sparql_opt(row: &HashMap<String, String>, key: &str) -> Value {
    match row.get(key) {
        Some(v) if !v.is_empty() => json!(v),
        _ => Value::Null,
    }
}

pub fn haystack_rows() -> Vec<Value> {
    crate::model::persist::haystack_model_value()
        .get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
}

pub fn list_sites() -> Value {
    let rows = sparql_predefined("eng_sites");
    let sites: Vec<Value> = rows
        .into_iter()
        .map(|row| {
            let site_id = row
                .get("site")
                .cloned()
                .unwrap_or_else(|| "site:unknown".into());
            let name = row.get("dis").cloned().unwrap_or_else(|| site_id.clone());
            json!({"site_id": site_id, "name": name})
        })
        .collect();
    if sites.is_empty() {
        return json!({
            "ok": true,
            "sites": sites,
            "active_site_id": Value::Null,
            "query_engine": "sparql"
        });
    }
    json!({
        "ok": true,
        "sites": sites,
        "active_site_id": sites.first().and_then(|s| s.get("site_id").and_then(|v| v.as_str())),
        "query_engine": "sparql"
    })
}

pub fn list_buildings(site_id: Option<&str>) -> Value {
    let sid = super::scope::resolve_site_id(site_id);
    json!({
        "ok": true,
        "site_id": sid,
        "buildings": if sid.is_some() {
            json!([{"building_id": "building:main", "name": "Main building", "site_id": sid}])
        } else {
            json!([])
        }
    })
}

pub fn list_equipment(site_id: &str) -> Value {
    let equips = list_equips(Some(site_id));
    let equipment: Vec<Value> = equips
        .get("equips")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|row| {
            let equipment_id = row.get("equipment_id").cloned().unwrap_or(json!(null));
            json!({
                "id": equipment_id.clone(),
                "equipment_id": equipment_id,
                "name": row.get("name").cloned().unwrap_or(json!(null)),
                "site_id": row.get("site_id").cloned().unwrap_or(json!(site_id)),
                "equipment_type": row.get("equipment_type").cloned().unwrap_or(json!(null))
            })
        })
        .collect();
    json!({
        "ok": true,
        "site_id": site_id,
        "equipment": equipment,
        "count": equipment.len()
    })
}

pub fn list_equips(site_id: Option<&str>) -> Value {
    let sid = super::scope::resolve_site_id(site_id);
    let filter = sid
        .as_deref()
        .map(|s| format!("FILTER (?site_id = \"{}\")", rdf::turtle_escape(s)))
        .unwrap_or_default();
    let query = format!(
        "{SPARQL_PREFIXES}
        SELECT ?equipment_id ?name ?site_id ?equipment_type WHERE {{
          ?s a hs:Equip .
          ?s ofdd:haystackId ?equipment_id .
          OPTIONAL {{ ?s hs:dis ?name . }}
          OPTIONAL {{ ?s hs:siteRef ?siteRes . ?siteRes ofdd:haystackId ?site_id . }}
          OPTIONAL {{ ?s ofdd:equipType ?equipment_type . }}
          {filter}
        }}"
    );
    let equips: Vec<Value> = sparql_rows(&query)
        .into_iter()
        .map(|row| {
            json!({
                "equipment_id": row.get("equipment_id").cloned().unwrap_or_default(),
                "name": row.get("name").cloned().unwrap_or_default(),
                "site_id": sparql_opt(&row, "site_id"),
                "equipment_type": sparql_opt(&row, "equipment_type")
            })
        })
        .collect();
    json!({
        "ok": true,
        "site_id": sid,
        "equips": equips,
        "count": equips.len(),
        "query_engine": "sparql"
    })
}

pub fn list_points(site_id: Option<&str>) -> Value {
    let sid = super::scope::resolve_site_id(site_id);
    let filter = sid
        .as_deref()
        .map(|s| format!("FILTER (?site_id = \"{}\")", rdf::turtle_escape(s)))
        .unwrap_or_default();
    let query = format!(
        "{SPARQL_PREFIXES}
        SELECT ?point_id ?name ?equip_ref ?site_id ?fdd_input ?bacnet_ref ?modbus_ref WHERE {{
          ?p a hs:Point .
          ?p ofdd:haystackId ?point_id .
          OPTIONAL {{ ?p hs:dis ?name . }}
          OPTIONAL {{ ?p hs:equipRef ?eq . ?eq ofdd:haystackId ?equip_ref . }}
          OPTIONAL {{ ?eq hs:siteRef ?siteRes . ?siteRes ofdd:haystackId ?site_id . }}
          OPTIONAL {{ ?p hs:fddInput ?fdd_input . }}
          OPTIONAL {{ ?p hs:bacnetRef ?bacnet_ref . }}
          OPTIONAL {{ ?p hs:modbusRef ?modbus_ref . }}
          {filter}
        }}"
    );
    let points: Vec<Value> = sparql_rows(&query)
        .into_iter()
        .map(|row| {
            let mapped = row.get("fdd_input").is_some()
                || row.get("bacnet_ref").is_some()
                || row.get("modbus_ref").is_some();
            json!({
                "point_id": row.get("point_id").cloned().unwrap_or_default(),
                "name": row.get("name").cloned().unwrap_or_default(),
                "equip_ref": sparql_opt(&row, "equip_ref"),
                "site_id": sparql_opt(&row, "site_id"),
                "mapped": mapped,
                "fdd_input": sparql_opt(&row, "fdd_input")
            })
        })
        .collect();
    json!({
        "ok": true,
        "site_id": sid,
        "points": points,
        "count": points.len(),
        "query_engine": "sparql"
    })
}

pub fn model_coverage() -> Value {
    let equip_rows = sparql_predefined("hvac_equipment");
    let point_rows = sparql_predefined("hvac_points");
    let unmapped_rows = sparql_predefined("hvac_unmapped_points");
    let point_count = point_rows.len();
    let unmapped = unmapped_rows.len();
    let mapped = point_count.saturating_sub(unmapped);
    let score = if point_count == 0 {
        0.0
    } else {
        (mapped as f64 / point_count as f64) * 100.0
    };
    json!({
        "ok": true,
        "equipment_count": equip_rows.len(),
        "point_count": point_count,
        "mapped_points": mapped,
        "unmapped_points": unmapped,
        "model_score": (score * 10.0).round() / 10.0,
        "query_engine": "sparql"
    })
}

pub fn source_coverage() -> Value {
    let query = format!(
        "{SPARQL_PREFIXES}
        SELECT ?protocol (COUNT(?point) AS ?point_count) WHERE {{
          ?p a hs:Point .
          ?p ofdd:haystackId ?point .
          BIND(
            IF(BOUND(?csv), \"csv\",
              IF(BOUND(?bacnet), \"bacnet\",
                IF(BOUND(?modbus), \"modbus\",
                  IF(BOUND(?fdd), \"json_api\", \"unmapped\"))))
            AS ?protocol)
          OPTIONAL {{ ?p hs:csvRef ?csv . }}
          OPTIONAL {{ ?p hs:bacnetRef ?bacnet . }}
          OPTIONAL {{ ?p hs:modbusRef ?modbus . }}
          OPTIONAL {{ ?p hs:fddInput ?fdd . }}
        }} GROUP BY ?protocol"
    );
    let protocols: Vec<Value> = sparql_rows(&query)
        .into_iter()
        .map(|row| {
            json!({
                "protocol": row.get("protocol").cloned().unwrap_or_else(|| "unmapped".into()),
                "point_count": row.get("point_count").and_then(|c| c.parse::<u64>().ok()).unwrap_or(0)
            })
        })
        .collect();
    json!({"ok": true, "protocols": protocols, "query_engine": "sparql"})
}

pub fn unmapped_points() -> Value {
    let rows = sparql_predefined("hvac_unmapped_points");
    let points: Vec<Value> = rows
        .into_iter()
        .map(|row| {
            json!({
                "point_id": row.get("point").cloned().unwrap_or_default(),
                "name": row.get("dis").cloned().unwrap_or_default(),
                "equip_ref": sparql_opt(&row, "equipRef")
            })
        })
        .collect();
    json!({
        "ok": true,
        "count": points.len(),
        "points": points,
        "query_engine": "sparql"
    })
}

pub fn group_points_by_equip() -> Value {
    let query = format!(
        "{SPARQL_PREFIXES}
        SELECT ?equip_ref ?point_id ?name ?mapped WHERE {{
          ?p a hs:Point .
          ?p ofdd:haystackId ?point_id .
          OPTIONAL {{ ?p hs:dis ?name . }}
          OPTIONAL {{ ?p hs:equipRef ?eq . ?eq ofdd:haystackId ?equip_ref . }}
          BIND(
            EXISTS {{ ?p hs:fddInput ?x }} ||
            EXISTS {{ ?p hs:bacnetRef ?y }} ||
            EXISTS {{ ?p hs:modbusRef ?z }}
            AS ?mapped)
        }}"
    );
    let mut groups: HashMap<String, Vec<Value>> = HashMap::new();
    for row in sparql_rows(&query) {
        let equip = row
            .get("equip_ref")
            .cloned()
            .unwrap_or_else(|| "unassigned".into());
        let mapped = row.get("mapped").map(|v| v == "true").unwrap_or(false);
        groups.entry(equip).or_default().push(json!({
            "point_id": row.get("point_id").cloned().unwrap_or_default(),
            "name": row.get("name").cloned().unwrap_or_default(),
            "mapped": mapped
        }));
    }
    let grouped: Vec<Value> = groups
        .into_iter()
        .map(|(equip_ref, points)| json!({"equip_ref": equip_ref, "points": points, "count": points.len()}))
        .collect();
    json!({"ok": true, "groups": grouped, "query_engine": "sparql"})
}

/// HVAC equipment counts and feeds chains for public dashboard context (SPARQL over RDF).
pub fn equipment_model_summary() -> Value {
    let type_rows = sparql_predefined("hvac_equipment_types");
    let mut by_type: HashMap<String, usize> = HashMap::new();
    for row in type_rows {
        if let (Some(etype), Some(count)) = (row.get("equipType"), row.get("count")) {
            by_type.insert(etype.clone(), count.parse::<usize>().unwrap_or(0));
        }
    }

    let equip_rows = sparql_predefined("hvac_equipment");
    let feeds_rows = sparql_predefined("hvac_feeds");
    let feeds_chains: Vec<String> = feeds_rows
        .into_iter()
        .filter_map(|row| {
            let from = row.get("fromLabel").or_else(|| row.get("from"))?;
            let to = row.get("toLabel").or_else(|| row.get("to"))?;
            Some(format!("{from} feeds {to}"))
        })
        .collect();

    json!({
        "ok": true,
        "equipment_by_type": by_type,
        "feeds_chains": feeds_chains,
        "equipment_count": equip_rows.len(),
        "query_engine": "sparql"
    })
}

/// Network graph for Model explorer and dashboard feeds visualization.
pub fn network_graph(site_id: Option<&str>) -> Value {
    let sid = super::scope::resolve_site_id(site_id);
    let site_filter = sid
        .as_deref()
        .map(|s| format!("FILTER (?site_id = \"{}\")", rdf::turtle_escape(s)))
        .unwrap_or_default();

    let equip_query = format!(
        "{SPARQL_PREFIXES}
        SELECT ?equipment_id ?name ?equipment_type ?site_id WHERE {{
          ?s a hs:Equip .
          ?s ofdd:haystackId ?equipment_id .
          OPTIONAL {{ ?s hs:dis ?name . }}
          OPTIONAL {{ ?s ofdd:equipType ?equipment_type . }}
          OPTIONAL {{ ?s hs:siteRef ?siteRes . ?siteRes ofdd:haystackId ?site_id . }}
          {site_filter}
        }}"
    );
    let equip_rows = sparql_rows(&equip_query);
    let mut labels: HashMap<String, String> = HashMap::new();
    let equipment: Vec<Value> = equip_rows
        .iter()
        .map(|row| {
            let equipment_id = row
                .get("equipment_id")
                .cloned()
                .unwrap_or_default();
            let name = row
                .get("name")
                .cloned()
                .unwrap_or_else(|| equipment_id.clone());
            labels.insert(equipment_id.clone(), name.clone());
            json!({
                "equipment_id": equipment_id,
                "name": name,
                "label": name,
                "equipment_type": row.get("equipment_type").cloned().unwrap_or_else(|| "generic".into())
            })
        })
        .collect();

    let equip_ids: HashSet<String> = labels.keys().cloned().collect();
    let feeds: Vec<Value> = sparql_predefined("hvac_feeds")
        .into_iter()
        .filter_map(|row| {
            let from = row.get("from")?.clone();
            let to = row.get("to")?.clone();
            if !equip_ids.contains(&to) {
                return None;
            }
            Some(json!({
                "from_equipment_id": from.clone(),
                "to_equipment_id": to.clone(),
                "from_label": row.get("fromLabel").cloned().unwrap_or(from),
                "to_label": row.get("toLabel").cloned().unwrap_or(to)
            }))
        })
        .collect();

    let points_query = format!(
        "{SPARQL_PREFIXES}
        SELECT ?equip_ref ?point_id ?name ?unit ?site_id WHERE {{
          ?p a hs:Point .
          ?p ofdd:haystackId ?point_id .
          OPTIONAL {{ ?p hs:dis ?name . }}
          OPTIONAL {{ ?p hs:unit ?unit . }}
          ?p hs:equipRef ?eq .
          ?eq ofdd:haystackId ?equip_ref .
          OPTIONAL {{ ?eq hs:siteRef ?siteRes . ?siteRes ofdd:haystackId ?site_id . }}
          {site_filter}
        }}"
    );
    let mut points_by_equipment: HashMap<String, Vec<Value>> = HashMap::new();
    for row in sparql_rows(&points_query) {
        let equip_ref = row.get("equip_ref").cloned().unwrap_or_default();
        if equip_ref.is_empty() || !equip_ids.contains(&equip_ref) {
            continue;
        }
        let point_id = row.get("point_id").cloned().unwrap_or_default();
        let name = row.get("name").cloned().unwrap_or_else(|| point_id.clone());
        points_by_equipment
            .entry(equip_ref.clone())
            .or_default()
            .push(json!({
                "point_id": point_id,
                "name": name,
                "label": name,
                "equipment_id": equip_ref,
                "unit": sparql_opt(&row, "unit")
            }));
    }

    let points_map: Value = points_by_equipment
        .into_iter()
        .map(|(k, v)| (k, json!(v)))
        .collect();

    json!({
        "ok": true,
        "site_id": sid,
        "query_engine": "sparql",
        "equipment": equipment,
        "feeds": feeds,
        "points_by_equipment": points_map
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::csv_import;
    use crate::test_support::with_temp_workspace;

    #[test]
    fn list_points_filters_by_csv_import_site() {
        with_temp_workspace(|_| {
            let model = csv_import::import_from_csv_commit(
                &["Date".to_string(), "Outdoor Air Temp".to_string()],
                "Plant-A.csv",
                "job-1",
                None,
            );
            assert_eq!(model.get("ok").and_then(|v| v.as_bool()), Some(true));
            let (site, equip, _, _) = csv_import::ids_from_filename("Plant-A.csv");
            assert_eq!(
                crate::model::scope::site_for_equipment(&equip).as_deref(),
                Some(site.as_str())
            );
            let pts = list_points(Some(&site));
            assert!(
                pts.get("count").and_then(|v| v.as_u64()).unwrap_or(0) >= 1,
                "expected points for {site}: {pts}"
            );
        });
    }

    #[test]
    fn groups_equips_and_counts_unmapped() {
        let coverage = model_coverage();
        assert!(coverage
            .get("equipment_count")
            .and_then(|v| v.as_u64())
            .is_some());
        assert!(coverage
            .get("point_count")
            .and_then(|v| v.as_u64())
            .is_some());
        let unmapped = unmapped_points();
        assert!(unmapped.get("count").is_some());
        let grouped = group_points_by_equip();
        assert!(grouped.get("groups").and_then(|v| v.as_array()).is_some());
    }
}
