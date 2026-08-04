//! Mechanical cooling eligibility — strict evidence hierarchy.
//!
//! Pump or valve alone is **not** compressor proof. Compressor/chiller status
//! (or equivalent) is required for eligible mechanical-cooling analytics.

use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::{BTreeMap, BTreeSet};

use super::{
    envelope, finalize_historian, historian, resolve_query_version, AnalyticsEnvelope,
    AnalyticsRequest, QV_MECHANICAL_COOLING,
};

/// Evidence kinds recognized by the hierarchy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceKind {
    PumpStatus,
    ValveCmd,
    ValveFeedback,
    CompressorStatus,
    ChillerStatus,
    /// Unknown / other — treated as insufficient alone.
    #[serde(other)]
    Other,
}

impl EvidenceKind {
    pub fn is_sufficient_primary(self) -> bool {
        matches!(self, Self::CompressorStatus | Self::ChillerStatus)
    }

    pub fn is_insufficient_alone(self) -> bool {
        matches!(
            self,
            Self::PumpStatus | Self::ValveCmd | Self::ValveFeedback
        )
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct EvidenceRow {
    pub equipment_id: String,
    pub evidence_kind: EvidenceKind,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub present: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MechCoolingEligibility {
    pub equipment_id: String,
    pub eligible: bool,
    pub confidence: String,
    pub evidence_kinds: Vec<String>,
    pub reason: String,
}

/// Evaluate eligibility per equipment from evidence rows.
///
/// Rules:
/// - At least one `compressor_status` or `chiller_status` → eligible, confidence high
///   (medium if only one primary sample and also pump/valve present as support).
/// - Pump-only or valve-only (any combination of pump/valve without compressor/chiller)
///   → not eligible, confidence none, reason insufficient_evidence.
pub fn evaluate_evidence(rows: &[EvidenceRow]) -> Vec<MechCoolingEligibility> {
    let mut by_eq: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut kinds_by_eq: BTreeMap<String, Vec<EvidenceKind>> = BTreeMap::new();

    for r in rows {
        let present = r.present.unwrap_or(true);
        if !present {
            continue;
        }
        let label = serde_json::to_value(r.evidence_kind)
            .ok()
            .and_then(|v| v.as_str().map(str::to_string))
            .unwrap_or_else(|| "other".into());
        by_eq
            .entry(r.equipment_id.clone())
            .or_default()
            .insert(label);
        kinds_by_eq
            .entry(r.equipment_id.clone())
            .or_default()
            .push(r.evidence_kind);
    }

    let mut out = Vec::with_capacity(by_eq.len());
    for (equipment_id, labels) in by_eq {
        let kinds = kinds_by_eq.get(&equipment_id).cloned().unwrap_or_default();
        let has_primary = kinds.iter().any(|k| k.is_sufficient_primary());
        let only_insufficient = !kinds.is_empty()
            && kinds
                .iter()
                .all(|k| k.is_insufficient_alone() || matches!(k, EvidenceKind::Other))
            && !has_primary
            && kinds.iter().any(|k| k.is_insufficient_alone());

        let evidence_kinds: Vec<String> = labels.into_iter().collect();

        let (eligible, confidence, reason) = if has_primary {
            let has_support = kinds.iter().any(|k| k.is_insufficient_alone());
            let confidence = if has_support { "high" } else { "medium" };
            (
                true,
                confidence.to_string(),
                "primary_compressor_or_chiller_status".into(),
            )
        } else if only_insufficient || kinds.iter().all(|k| k.is_insufficient_alone()) {
            (
                false,
                "none".into(),
                "insufficient_evidence_pump_or_valve_only".into(),
            )
        } else {
            (
                false,
                "none".into(),
                "insufficient_evidence_no_primary_status".into(),
            )
        };

        out.push(MechCoolingEligibility {
            equipment_id,
            eligible,
            confidence,
            evidence_kinds,
            reason,
        });
    }
    out
}

pub fn handle(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    let (qv, mut warnings) = resolve_query_version(req, QV_MECHANICAL_COOLING);
    let mut env = envelope(&qv, &req.query, warnings.clone());

    let rows = parse_evidence(req);
    match rows {
        Some(evidence) if !evidence.is_empty() => {
            let mut filtered = evidence;
            if let Some(ids) = &req.query.equipment_ids {
                if !ids.is_empty() {
                    filtered.retain(|r| ids.contains(&r.equipment_id));
                }
            }
            let results = evaluate_evidence(&filtered);
            env.rows = results
                .iter()
                .map(|r| serde_json::to_value(r).unwrap_or(json!({})))
                .collect();
            env.equipment = env.rows.clone();
            env.coverage = Some(json!({
                "equipment_count": env.equipment.len(),
                "evidence_row_count": filtered.len(),
            }));
            warnings.push(
                "mechanical_cooling: evidence-hierarchy gate only (OAT bins / DF port next)".into(),
            );
            env.warnings = warnings;
        }
        _ => {
            warnings.push(
                "no inline evidence rows provided; historian/job mechanical-cooling load is next"
                    .into(),
            );
            env.warnings = warnings;
        }
    }
    env
}

/// Async handler: prefer historian OAT bins, else descriptive counts, else
/// inline evidence-hierarchy gate.
pub async fn handle_async(req: &AnalyticsRequest) -> AnalyticsEnvelope {
    if req.series.is_none() {
        let max_gap = req.max_gap_seconds.unwrap_or(900.0);
        match historian::mech_oat_bins_from_history(req.query.equipment_ids.as_deref(), max_gap)
            .await
        {
            Ok(Some(env)) => return finalize_historian(req, env, QV_MECHANICAL_COOLING),
            Ok(None) => {}
            Err(e) => {
                tracing::warn!(error = %e, "historian mechanical_cooling OAT bins failed");
            }
        }
        match historian::descriptive_counts_from_history(
            QV_MECHANICAL_COOLING,
            req.query.equipment_ids.as_deref(),
            "mechanical_cooling: compressor/chiller evidence gate requires inline series",
        )
        .await
        {
            Ok(Some(env)) => return finalize_historian(req, env, QV_MECHANICAL_COOLING),
            Ok(None) => {}
            Err(e) => {
                tracing::warn!(error = %e, "historian mechanical_cooling path failed; using inline/empty fallback");
            }
        }
    }
    handle(req)
}

fn parse_evidence(req: &AnalyticsRequest) -> Option<Vec<EvidenceRow>> {
    let series = req.series.as_ref()?;
    let arr = if let Some(a) = series.as_array() {
        a.clone()
    } else if let Some(a) = series.get("evidence").and_then(|v| v.as_array()) {
        a.clone()
    } else if let Some(a) = series.get("points").and_then(|v| v.as_array()) {
        a.clone()
    } else {
        return None;
    };
    let mut out = Vec::new();
    for v in arr {
        if let Ok(p) = serde_json::from_value::<EvidenceRow>(v) {
            out.push(p);
        }
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pump_only_rejected() {
        let rows = vec![EvidenceRow {
            equipment_id: "CH-1".into(),
            evidence_kind: EvidenceKind::PumpStatus,
            role: Some("chw_pump".into()),
            present: Some(true),
        }];
        let out = evaluate_evidence(&rows);
        assert_eq!(out.len(), 1);
        assert!(!out[0].eligible);
        assert_eq!(out[0].confidence, "none");
        assert!(out[0].reason.contains("pump_or_valve"));
    }

    #[test]
    fn valve_only_rejected() {
        let rows = vec![
            EvidenceRow {
                equipment_id: "AHU-1".into(),
                evidence_kind: EvidenceKind::ValveCmd,
                role: None,
                present: Some(true),
            },
            EvidenceRow {
                equipment_id: "AHU-1".into(),
                evidence_kind: EvidenceKind::ValveFeedback,
                role: None,
                present: Some(true),
            },
        ];
        let out = evaluate_evidence(&rows);
        assert!(!out[0].eligible);
        assert!(out[0].reason.contains("insufficient"));
    }

    #[test]
    fn compressor_status_accepted() {
        let rows = vec![EvidenceRow {
            equipment_id: "CH-2".into(),
            evidence_kind: EvidenceKind::CompressorStatus,
            role: Some("comp_1".into()),
            present: Some(true),
        }];
        let out = evaluate_evidence(&rows);
        assert!(out[0].eligible);
        assert!(out[0].confidence == "medium" || out[0].confidence == "high");
        assert_eq!(out[0].reason, "primary_compressor_or_chiller_status");
    }

    #[test]
    fn chiller_status_with_pump_support_high_confidence() {
        let rows = vec![
            EvidenceRow {
                equipment_id: "CH-3".into(),
                evidence_kind: EvidenceKind::ChillerStatus,
                role: None,
                present: Some(true),
            },
            EvidenceRow {
                equipment_id: "CH-3".into(),
                evidence_kind: EvidenceKind::PumpStatus,
                role: None,
                present: Some(true),
            },
        ];
        let out = evaluate_evidence(&rows);
        assert!(out[0].eligible);
        assert_eq!(out[0].confidence, "high");
    }

    #[test]
    fn handle_pump_only_via_series() {
        let req = AnalyticsRequest {
            series: Some(json!({
                "evidence": [
                    {"equipment_id": "CH-1", "evidence_kind": "pump_status", "present": true}
                ]
            })),
            ..Default::default()
        };
        let env = handle(&req);
        assert_eq!(env.query_version, QV_MECHANICAL_COOLING);
        assert_eq!(env.rows.len(), 1);
        assert_eq!(env.rows[0]["eligible"], false);
    }
}
