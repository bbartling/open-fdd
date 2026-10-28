//! Building-scoped VAV health matrix (vav_health_matrix_v1). No Python.

use std::collections::{HashMap, HashSet};

use anyhow::Result;
use serde_json::{json, Value};
use sqlx::Row;

use super::{envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, AnalyticsRequest, DF_ENGINE};

pub async fn handle_async(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    match vav_health_from_history(
        req.query.building_id.as_deref(),
        70.0,
        75.0,
        req.query.start,
        req.query.end,
    )
    .await
    {
        Ok(Some(env)) => env,
        Ok(None) => vav_state_envelope(&req.query, "error", "vav-health unavailable", DF_ENGINE),
        Err(e) => {
            let message = public_db_message(&e.to_string());
            vav_state_envelope(&req.query, "error", &message, DF_ENGINE)
        }
    }
}

pub const QV_VAV_HEALTH: &str = "vav-health-v1";
pub const SCHEMA_VAV_HEALTH: &str = "vav_health_matrix_v1";

fn public_db_message(err: &str) -> String {
    if err.contains("postgres://") || err.contains("postgresql://") {
        "vav-health query failed".to_string()
    } else {
        format!("vav-health query failed: {err}")
    }
}

fn vav_state_envelope(
    query: &AnalyticsQuery,
    availability: &str,
    message: &str,
    engine: &str,
) -> AnalyticsEnvelope {
    let mut env = envelope_with_engine(QV_VAV_HEALTH, query, vec![message.to_string()], engine);
    let mut coverage = json!({
        "schema_version": SCHEMA_VAV_HEALTH,
        "availability": availability,
        "message": message,
    });
    if let Some(building_id) = query.building_id.as_deref() {
        if let Some(obj) = coverage.as_object_mut() {
            obj.insert("building_id".into(), json!(building_id));
        }
    }
    env.coverage = Some(coverage);
    env
}

struct PointSpan {
    n: i64,
    span_s: f64,
    comfort_fail_s: f64,
    full_open_s: f64,
}

fn hours(seconds: f64) -> f64 {
    if seconds.is_finite() && seconds > 0.0 {
        seconds / 3600.0
    } else {
        0.0
    }
}

/// Timescale VAV matrix. Membership is `canonical_kind == "vav"`.
/// Zone and damper series come from the current unique `authorized_series` binding.
async fn timescale_vav_matrix(
    building_id: &str,
    comfort_low: f64,
    comfort_high: f64,
    start: Option<chrono::DateTime<chrono::Utc>>,
    end: Option<chrono::DateTime<chrono::Utc>>,
) -> Result<Option<AnalyticsEnvelope>> {
    let query = AnalyticsQuery {
        building_id: Some(building_id.to_string()),
        ..Default::default()
    };
    let (win_start, win_end) = match super::historian::resolve_analytics_window(
        start,
        end,
        super::historian::VAV_HEALTH_DEFAULT_LOOKBACK_DAYS,
    ) {
        Ok(window) => window,
        Err(err) => {
            return Ok(Some(vav_state_envelope(
                &query,
                "error",
                &public_db_message(&err),
                "timescale-sql",
            )));
        }
    };
    let win_end = win_end.unwrap_or_else(chrono::Utc::now);
    let tsdb = match fdd_tsdb::Tsdb::connect_from_env().await {
        Ok(tsdb) => tsdb,
        Err(err) => {
            return Ok(Some(vav_state_envelope(
                &query,
                "error",
                &public_db_message(&err.to_string()),
                "timescale-sql",
            )));
        }
    };

    let equipment_rows = match sqlx::query(
        "SELECT equipment_id, equip_type FROM equipment WHERE building_id = $1 ORDER BY equipment_id",
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    {
        Ok(rows) => rows,
        Err(err) => {
            return Ok(Some(vav_state_envelope(
                &query,
                "error",
                &public_db_message(&err.to_string()),
                "timescale-sql",
            )));
        }
    };

    let mut vav: Vec<(String, String)> = Vec::new();
    for row in equipment_rows {
        let equipment_id: String = match row.try_get("equipment_id") {
            Ok(id) => id,
            Err(err) => {
                return Ok(Some(vav_state_envelope(
                    &query,
                    "error",
                    &public_db_message(&err.to_string()),
                    "timescale-sql",
                )));
            }
        };
        let equip_type: Option<String> = row.try_get("equip_type").unwrap_or(None);
        let stamped = equip_type.as_deref().unwrap_or("");
        if open_fdd_edge_prototype::equipment_types::canonical_kind(stamped) == Some("vav") {
            vav.push((equipment_id, stamped.to_string()));
        }
    }
    if vav.is_empty() {
        return Ok(Some(vav_state_envelope(
            &query,
            "no_equipment",
            "No VAV equipment in this data model.",
            "timescale-sql",
        )));
    }

    let role_rows = match sqlx::query(
        "SELECT equipment_id, role, openfdd_key
         FROM authorized_series
         WHERE site_id = $1 AND role IN ('zone_t', 'damper_pct')",
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    {
        Ok(rows) => rows,
        Err(err) => {
            return Ok(Some(vav_state_envelope(
                &query,
                "error",
                &public_db_message(&err.to_string()),
                "timescale-sql",
            )));
        }
    };
    let vav_ids: HashSet<String> = vav.iter().map(|(id, _)| id.clone()).collect();
    let mut roles: HashMap<String, HashSet<String>> = HashMap::new();
    let mut key_counts: HashMap<(String, String), usize> = HashMap::new();
    let mut bound_keys: HashMap<(String, String), String> = HashMap::new();
    for row in role_rows {
        let equipment_id: String = row.try_get("equipment_id").unwrap_or_default();
        let role: String = row.try_get("role").unwrap_or_default();
        let openfdd_key: String = row.try_get("openfdd_key").unwrap_or_default();
        if vav_ids.contains(&equipment_id) && !role.is_empty() && !openfdd_key.is_empty() {
            roles
                .entry(equipment_id.clone())
                .or_default()
                .insert(role.clone());
            let slot = (equipment_id, role);
            *key_counts.entry(slot.clone()).or_default() += 1;
            bound_keys.insert(slot, openfdd_key);
        }
    }
    // Two keys for one role are omitted. Averaging them would hide the conflict.
    bound_keys.retain(|slot, _| key_counts.get(slot).copied().unwrap_or(0) == 1);
    let keys: Vec<String> = bound_keys.values().cloned().collect();
    let sample_rows = match sqlx::query(
        r#"
        WITH ordered AS (
          SELECT openfdd_key, ts, val, unit,
                 LEAD(ts) OVER (PARTITION BY openfdd_key ORDER BY ts) AS next_ts
          FROM sample
          WHERE site_id = $1
            AND openfdd_key = ANY($2)
            AND ts >= $3
            AND ts < $4
        )
        SELECT openfdd_key,
               COUNT(*)::bigint AS n,
               COALESCE(SUM(
                 CASE WHEN next_ts IS NULL THEN 0
                 ELSE LEAST(EXTRACT(EPOCH FROM (next_ts - ts)), 3600.0)
                 END
               ), 0)::float8 AS span_s,
               COALESCE(SUM(
                 CASE
                   WHEN next_ts IS NULL OR btrim(coalesce(unit, '')) = '' THEN 0
                   WHEN next_ts IS NOT NULL AND (
                     CASE
                       WHEN lower(regexp_replace(coalesce(unit, ''), '[^a-zA-Z0-9]', '', 'g'))
                            IN ('c', 'degc', 'celsius')
                         THEN val < (($5 - 32.0) * 5.0 / 9.0)
                           OR val > (($6 - 32.0) * 5.0 / 9.0)
                       ELSE val < $5 OR val > $6
                     END
                   )
                   THEN LEAST(EXTRACT(EPOCH FROM (next_ts - ts)), 3600.0)
                   ELSE 0
                 END
               ), 0)::float8 AS comfort_fail_s,
               COALESCE(SUM(
                 CASE
                   WHEN next_ts IS NOT NULL AND (
                     CASE WHEN val > 1.0 THEN val / 100.0 ELSE val END
                   ) >= 0.975
                   THEN LEAST(EXTRACT(EPOCH FROM (next_ts - ts)), 3600.0)
                   ELSE 0
                 END
               ), 0)::float8 AS full_open_s
        FROM ordered
        GROUP BY openfdd_key
        "#,
    )
    .bind(building_id)
    .bind(&keys)
    .bind(win_start)
    .bind(win_end)
    .bind(comfort_low)
    .bind(comfort_high)
    .fetch_all(tsdb.pool())
    .await
    {
        Ok(rows) => rows,
        Err(err) => {
            return Ok(Some(vav_state_envelope(
                &query,
                "error",
                &public_db_message(&err.to_string()),
                "timescale-sql",
            )));
        }
    };

    let mut spans: HashMap<String, PointSpan> = HashMap::new();
    for row in sample_rows {
        let key: String = match row.try_get("openfdd_key") {
            Ok(key) => key,
            Err(err) => {
                return Ok(Some(vav_state_envelope(
                    &query,
                    "error",
                    &public_db_message(&err.to_string()),
                    "timescale-sql",
                )));
            }
        };
        if !keys.iter().any(|candidate| candidate == &key) {
            continue;
        }
        spans.insert(
            key,
            PointSpan {
                n: row.try_get("n").unwrap_or(0),
                span_s: row.try_get("span_s").unwrap_or(0.0),
                comfort_fail_s: row.try_get("comfort_fail_s").unwrap_or(0.0),
                full_open_s: row.try_get("full_open_s").unwrap_or(0.0),
            },
        );
    }

    let any_samples = spans.values().any(|span| span.n > 0);
    if !any_samples {
        let mapped_zone = vav
            .iter()
            .any(|(id, _)| roles.get(id).is_some_and(|set| set.contains("zone_t")));
        if mapped_zone {
            return Ok(Some(vav_state_envelope(
                &query,
                "no_history",
                "VAV zone temperature is mapped, but this window has no samples.",
                "timescale-sql",
            )));
        }
        return Ok(Some(vav_state_envelope(
            &query,
            "unsupported",
            "VAV equipment is present, but no zone temperature role is mapped and this window has no samples.",
            "timescale-sql",
        )));
    }

    let mut env = envelope_with_engine(QV_VAV_HEALTH, &query, Vec::new(), "timescale-sql");
    let mut n3 = 0u32;
    let mut n2 = 0u32;
    let mut n1 = 0u32;
    let mut n0 = 0u32;
    let mut nq = 0u32;
    for (equipment_id, stamped) in &vav {
        let zone_key = bound_keys
            .get(&(equipment_id.clone(), "zone_t".to_string()))
            .map(String::as_str)
            .unwrap_or("");
        let damper_key = bound_keys
            .get(&(equipment_id.clone(), "damper_pct".to_string()))
            .map(String::as_str)
            .unwrap_or("");
        let zone = spans.get(zone_key);
        let damper = spans.get(damper_key);
        let zone_n = zone.map(|span| span.n).unwrap_or(0);
        let damper_n = damper.map(|span| span.n).unwrap_or(0);
        if zone_n <= 0 && damper_n <= 0 {
            continue;
        }
        let fail_h = hours(zone.map(|span| span.comfort_fail_s).unwrap_or(0.0));
        let open_h = hours(damper.map(|span| span.full_open_s).unwrap_or(0.0));
        let span_h = hours(zone.map(|span| span.span_s).unwrap_or(0.0))
            .max(hours(damper.map(|span| span.span_s).unwrap_or(0.0)));
        let poor = if zone_n <= 0 {
            Value::Null
        } else {
            json!(fail_h > 0.01)
        };
        let rogue = if damper_n <= 0 || span_h < 20.0 {
            Value::Null
        } else {
            json!(span_h > 0.0 && (100.0 * open_h / span_h) >= 95.0)
        };
        let broken = Value::Null;
        let evaluable = [&poor, &rogue, &broken]
            .iter()
            .filter(|flag| !flag.is_null())
            .count();
        let hit = [&poor, &rogue, &broken]
            .iter()
            .filter(|flag| flag.as_bool() == Some(true))
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
            "building_id": building_id,
            "equipment_id": equipment_id,
            "equipment_type": open_fdd_edge_prototype::equipment_types::api_equipment_type_for(
                "",
                Some(stamped.as_str()),
            ),
            "broken_box": broken,
            "poor_zone_performance": poor,
            "rogue_damper": rogue,
            "dimensions_hit": hit,
            "dimensions_evaluable": evaluable,
            "score_label": label,
            "broken_fault_hours": 0.0,
            "comfort_fault_h": fail_h,
            "rogue_fault_h": open_h,
            "total_fault_h": fail_h + open_h,
            "schema_version": SCHEMA_VAV_HEALTH,
            "notes": "broken_box unknown until Run all rules joins FDD results",
        }));
    }
    env.coverage = Some(json!({
        "schema_version": SCHEMA_VAV_HEALTH,
        "building_id": building_id,
        "availability": "ready",
        "message": "VAV health is ready.",
        "groups": { "3/3": n3, "2/3": n2, "1/3": n1, "0/3": n0, "?/3": nq },
    }));
    env.warnings
        .push("broken_box unknown until Run all rules joins FDD results".into());
    Ok(Some(env))
}

pub async fn vav_health_from_history(
    building_id: Option<&str>,
    comfort_low: f64,
    comfort_high: f64,
    start: Option<chrono::DateTime<chrono::Utc>>,
    end: Option<chrono::DateTime<chrono::Utc>>,
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
        env.coverage = Some(json!({
            "schema_version": SCHEMA_VAV_HEALTH,
            "availability": "error",
            "message": "building_id is required — refusing mixed-site query",
        }));
        return Ok(Some(env));
    };
    timescale_vav_matrix(bid, comfort_low, comfort_high, start, end).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn refuses_missing_building_id() {
        let env = vav_health_from_history(None, 70.0, 75.0, None, None)
            .await
            .unwrap()
            .unwrap();
        assert!(env.warnings.iter().any(|w| w.contains("building_id")));
        assert!(env.rows.is_empty());
    }
}
