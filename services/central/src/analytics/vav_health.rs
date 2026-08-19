//! Building-scoped VAV health matrix (vav_health_matrix_v1). No Python.

use std::collections::HashMap;

use anyhow::Result;
use datafusion::prelude::SessionContext;
use fdd_sql::run_sql;
use serde_json::{json, Value};

use super::historian::try_register_history_scoped;
use super::{envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, AnalyticsRequest, DF_ENGINE};

pub async fn handle_async(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    match vav_health_from_history(req.query.building_id.as_deref(), 70.0, 75.0).await {
        Ok(Some(env)) => env,
        Ok(None) => {
            let mut env = envelope_with_engine(
                QV_VAV_HEALTH,
                &req.query,
                vec!["vav-health unavailable".into()],
                DF_ENGINE,
            );
            env.coverage = Some(json!({"schema_version": SCHEMA_VAV_HEALTH}));
            env
        }
        Err(e) => {
            let mut env = envelope_with_engine(
                QV_VAV_HEALTH,
                &req.query,
                vec![format!("vav-health failed: {e}")],
                DF_ENGINE,
            );
            env.coverage = Some(json!({"schema_version": SCHEMA_VAV_HEALTH}));
            env
        }
    }
}

pub const QV_VAV_HEALTH: &str = "vav-health-v1";
pub const SCHEMA_VAV_HEALTH: &str = "vav_health_matrix_v1";

/// Same default IDs as `open_fdd.analytics.vav_health.DEFAULT_BROKEN_RULES`.
const BROKEN_RULE_IDS: &[&str] = &[
    "VAV-3",
    "VAV-4",
    "VAV-5",
    "VAV-7",
    "VAV-REHEAT",
    "VAV-AHU-LEAVE",
];

/// Per-equipment broken-box from the last registry run. Empty map + `false`
/// when no result JSON exists (unknown, not PASS).
fn broken_box_from_fdd(building_id: &str) -> (bool, HashMap<String, (bool, String, f64)>) {
    let body = open_fdd_edge_prototype::fdd::registry_api::results_response(Some(building_id));
    let rows = body
        .get("results")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if rows.is_empty() {
        return (false, HashMap::new());
    }
    let mut map: HashMap<String, (bool, Vec<String>, f64)> = HashMap::new();
    for row in rows {
        let rid = row.get("rule_id").and_then(Value::as_str).unwrap_or("");
        if !BROKEN_RULE_IDS.contains(&rid) {
            continue;
        }
        let st = row.get("status").and_then(Value::as_str).unwrap_or("");
        if st.eq_ignore_ascii_case("NOT_APPLICABLE_EQUIPMENT_TYPE") {
            continue;
        }
        let eq = row
            .get("equipment_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if eq.is_empty() {
            continue;
        }
        let hours = row
            .get("fault_hours")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
        let fault = st.eq_ignore_ascii_case("FAULT") || hours > 0.0;
        let e = map.entry(eq).or_insert_with(|| (false, Vec::new(), 0.0));
        e.2 += hours;
        if fault {
            e.0 = true;
            e.1.push(rid.to_string());
        }
    }
    let out = map
        .into_iter()
        .map(|(k, (fault, mut ids, hours))| {
            ids.sort();
            ids.dedup();
            (k, (fault, ids.join(";"), hours))
        })
        .collect();
    (true, out)
}

pub async fn vav_health_from_history(
    building_id: Option<&str>,
    comfort_low: f64,
    comfort_high: f64,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        let q = AnalyticsQuery {
            building_id: None,
            ..Default::default()
        };
        let mut env = envelope_with_engine(
            QV_VAV_HEALTH,
            &q,
            vec!["building_id is required — refusing mixed-site query".into()],
            DF_ENGINE,
        );
        env.coverage = Some(json!({"schema_version": SCHEMA_VAV_HEALTH}));
        return Ok(Some(env));
    };
    let ctx = SessionContext::new();
    if !try_register_history_scoped(&ctx, Some(bid)).await? {
        let q = AnalyticsQuery {
            building_id: Some(bid.to_string()),
            ..Default::default()
        };
        let mut env = envelope_with_engine(
            QV_VAV_HEALTH,
            &q,
            vec![
                "no historian parquet for this building — run ingest then Update analytics".into(),
            ],
            DF_ENGINE,
        );
        env.coverage = Some(json!({"schema_version": SCHEMA_VAV_HEALTH, "building_id": bid}));
        return Ok(Some(env));
    }
    let sql = r#"
SELECT
  equipment_id,
  AVG(CASE WHEN zone_t IS NOT NULL THEN 1.0 ELSE 0.0 END) AS zone_cov,
  AVG(CASE WHEN damper_pct IS NOT NULL THEN 1.0 ELSE 0.0 END) AS dmp_cov,
  SUM(CASE
    WHEN zone_t IS NOT NULL AND (zone_t < {lo} OR zone_t > {hi}) THEN 1.0 ELSE 0.0
  END) * 300.0 / 3600.0 AS comfort_fail_h,
  SUM(CASE
    WHEN damper_pct IS NOT NULL AND (
      CASE WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END
    ) >= 0.975 THEN 1.0 ELSE 0.0
  END) * 300.0 / 3600.0 AS full_open_h,
  COUNT(*) * 300.0 / 3600.0 AS span_h
FROM history
WHERE equipment_id LIKE 'VAV%'
GROUP BY equipment_id
ORDER BY equipment_id
"#
    .replace("{lo}", &comfort_low.to_string())
    .replace("{hi}", &comfort_high.to_string());
    let result = match run_sql(&ctx, &sql).await {
        Ok(r) => r,
        Err(e) => {
            let q = AnalyticsQuery {
                building_id: Some(bid.to_string()),
                ..Default::default()
            };
            let mut env = envelope_with_engine(
                QV_VAV_HEALTH,
                &q,
                vec![format!("vav-health query failed: {e}")],
                DF_ENGINE,
            );
            env.coverage = Some(json!({"schema_version": SCHEMA_VAV_HEALTH}));
            return Ok(Some(env));
        }
    };
    let q = AnalyticsQuery {
        building_id: Some(bid.to_string()),
        ..Default::default()
    };
    let mut env = envelope_with_engine(QV_VAV_HEALTH, &q, vec![], DF_ENGINE);
    let mut n3 = 0u32;
    let mut n2 = 0u32;
    let mut n1 = 0u32;
    let mut n0 = 0u32;
    let mut nq = 0u32;
    let (has_fdd, broken_map) = broken_box_from_fdd(bid);
    for row in result.rows {
        let eq = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let dmp_cov = row.get("dmp_cov").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let zone_cov = row.get("zone_cov").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let fail_h = row
            .get("comfort_fail_h")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        let open_h = row
            .get("full_open_h")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        let span = row.get("span_h").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let poor = if zone_cov < 0.01 {
            Value::Null
        } else {
            json!(fail_h > 0.01)
        };
        let rogue = if dmp_cov < 0.01 || span < 20.0 {
            Value::Null
        } else {
            json!(span > 0.0 && (100.0 * open_h / span) >= 95.0)
        };
        let (broken, broken_ids, broken_h) = if !has_fdd {
            (Value::Null, String::new(), 0.0)
        } else if let Some((fault, ids, hours)) = broken_map.get(eq) {
            (json!(*fault), ids.clone(), *hours)
        } else {
            (json!(false), String::new(), 0.0)
        };
        let evaluable = [&poor, &rogue, &broken]
            .iter()
            .filter(|v| !v.is_null())
            .count();
        let hit = [&poor, &rogue, &broken]
            .iter()
            .filter(|v| v.as_bool() == Some(true))
            .count();
        let label = if evaluable < 3 {
            nq += 1;
            "?/3"
        } else if hit == 3 {
            n3 += 1;
            "3/3"
        } else if hit == 2 {
            n2 += 1;
            "2/3"
        } else if hit == 1 {
            n1 += 1;
            "1/3"
        } else {
            n0 += 1;
            "0/3"
        };
        env.rows.push(json!({
            "building_id": bid,
            "equipment_id": eq,
            "parent_ahu": "",
            "equipment_type": "VAV",
            "broken_box": broken,
            "poor_zone_performance": poor,
            "rogue_damper": rogue,
            "dimensions_hit": hit,
            "dimensions_evaluable": evaluable,
            "score_label": label,
            "broken_rule_ids": broken_ids,
            "broken_fault_hours": broken_h,
            "comfort_fault_h": fail_h,
            "rogue_fault_h": open_h,
            "total_fault_h": broken_h + fail_h + open_h,
            "occupied_comfort_fail_pct": if span > 0.0 { json!(100.0 * fail_h / span) } else { Value::Null },
            "occupied_hours": span,
            "damper_full_open_pct": if span > 0.0 { json!(100.0 * open_h / span) } else { Value::Null },
            "damper_full_open_hours": open_h,
            "operating_hours": span,
            "data_coverage_pct": 100.0 * zone_cov,
            "confidence": if evaluable < 3 { "insufficient" } else { "medium" },
            "engine": DF_ENGINE,
            "schema_version": SCHEMA_VAV_HEALTH,
            "notes": if has_fdd {
                "broken_box from VAV-3/4/5/7/REHEAT/AHU-LEAVE FDD results"
            } else {
                "broken_box unknown until Run all rules joins FDD results"
            },
        }));
    }
    env.coverage = Some(json!({
        "schema_version": SCHEMA_VAV_HEALTH,
        "building_id": bid,
        "groups": {
            "3/3": n3, "2/3": n2, "1/3": n1, "0/3": n0, "?/3": nq
        }
    }));
    if env.rows.is_empty() {
        env.warnings
            .push("no VAV% equipment_id rows in historian".into());
    }
    if !has_fdd {
        env.warnings
            .push("Run all rules to populate broken_box from VAV-3/4/5/7/REHEAT/AHU-LEAVE".into());
    }
    Ok(Some(env))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn refuses_missing_building_id() {
        let env = vav_health_from_history(None, 70.0, 75.0)
            .await
            .unwrap()
            .unwrap();
        assert!(env.warnings.iter().any(|w| w.contains("building_id")));
        assert!(env.rows.is_empty());
    }
}
