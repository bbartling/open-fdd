//! Per-site schedule and verified-coverage status for Operations.
//!
//! A device is `verified` only when its stored cursor reaches the newest
//! instant the schedule has planned. Otherwise the first hole decides: a
//! failed, partial, or retrying window is a `gap`, a committed window whose
//! coverage is not assessed is `not_assessed`, and queued, running, or
//! unplanned time is `behind`. A device with no cursor is `not_assessed`.
//! The site state is the worst device state.

use chrono::{DateTime, Utc};
use serde::Serialize;

use crate::providers::committed_model::{IngestPlan, PlannedPoint};
use crate::providers::http_policy::provider_ids_equivalent;

use super::coverage::NOT_ASSESSED;
use super::cursor::{CoverageCursor, CursorHole, NOT_SCHEDULED};
use super::model::{JobState, JobView};

pub const VERIFIED: &str = "verified";
pub const BEHIND: &str = "behind";
pub const GAP: &str = "gap";
pub const NOT_CONFIGURED: &str = "not_configured";

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DeviceStatus {
    pub device_id: String,
    pub approved_points: usize,
    pub withheld_points: usize,
    pub verified_through: Option<DateTime<Utc>>,
    pub hole: Option<CursorHole>,
    pub state: &'static str,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OldestGap {
    pub device_id: String,
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    pub state: String,
    pub code: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ProviderStatus {
    pub provider_instance_id: String,
    pub model_revision: Option<String>,
    pub approved_points: usize,
    pub withheld_points: usize,
    pub discovered_points: usize,
    pub verified_through: Option<DateTime<Utc>>,
    pub devices: Vec<DeviceStatus>,
    pub oldest_gap: Option<OldestGap>,
    pub state: &'static str,
    /// Why coverage is not assessed, when `state` is `not_assessed`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub state_reason: Option<&'static str>,
}

/// The worse of two states: gap, then not assessed, then behind, then verified.
pub fn worse(a: &'static str, b: &'static str) -> &'static str {
    if rank(b) > rank(a) {
        b
    } else {
        a
    }
}

/// A point contributes to assessed coverage only when cadence or COV is bound.
pub fn point_cadence_bound(point: &PlannedPoint) -> bool {
    match point.history_mode.as_deref() {
        Some("interval") => point.cadence_secs.is_some_and(|secs| secs > 0),
        Some("cov") => true,
        _ => false,
    }
}

fn plan_has_assessable_points(plan: &IngestPlan, provider_instance_id: &str) -> bool {
    plan.groups
        .iter()
        .filter(|group| same_provider(&group.provider_instance_id, provider_instance_id))
        .flat_map(|group| group.points.iter())
        .any(point_cadence_bound)
}

fn not_assessed_reason(
    plan: &IngestPlan,
    provider_instance_id: &str,
    devices: &[DeviceStatus],
) -> &'static str {
    if !plan_has_assessable_points(plan, provider_instance_id) {
        return "cadence_not_bound";
    }
    if devices
        .iter()
        .any(|row| row.state == NOT_ASSESSED && row.verified_through.is_none())
    {
        return "no_verified_cursor";
    }
    "coverage_not_assessed"
}

fn rank(state: &str) -> u8 {
    match state {
        VERIFIED => 0,
        BEHIND => 1,
        NOT_ASSESSED => 2,
        GAP => 3,
        _ => 4,
    }
}

/// Plans name the model slug; queue rows and site config name the connection.
fn same_provider(row: &str, provider_instance_id: &str) -> bool {
    provider_ids_equivalent(provider_instance_id, row)
}

/// State of one device from its cursor and the planned horizon.
pub fn device_state(
    cursor: Option<&CoverageCursor>,
    planned_through: DateTime<Utc>,
) -> &'static str {
    let Some(cursor) = cursor else {
        return NOT_ASSESSED;
    };
    if cursor.verified_through >= planned_through {
        return VERIFIED;
    }
    let Some(hole) = cursor.hole.as_ref() else {
        return BEHIND;
    };
    if hole.state == NOT_SCHEDULED {
        return BEHIND;
    }
    match JobState::parse(&hole.state) {
        Some(JobState::Queued | JobState::Leased) => BEHIND,
        Some(JobState::Committed) if hole.code.as_deref() == Some(NOT_ASSESSED) => NOT_ASSESSED,
        _ => GAP,
    }
}

/// Status of one provider's devices under the site's active plan. Only
/// cursors and gaps for the plan revision count. `gaps` must be ordered by
/// window start, as the gap list is.
pub fn provider_status(
    provider_instance_id: &str,
    plan: Option<&IngestPlan>,
    cursors: &[CoverageCursor],
    gaps: &[JobView],
    planned_through: DateTime<Utc>,
) -> ProviderStatus {
    let Some(plan) = plan else {
        return ProviderStatus {
            provider_instance_id: provider_instance_id.to_string(),
            model_revision: None,
            approved_points: 0,
            withheld_points: 0,
            discovered_points: 0,
            verified_through: None,
            devices: Vec::new(),
            oldest_gap: None,
            state: NOT_CONFIGURED,
            state_reason: None,
        };
    };
    let revision = plan.revision_id.as_str();
    let devices: Vec<DeviceStatus> = plan
        .groups
        .iter()
        .filter(|group| same_provider(&group.provider_instance_id, provider_instance_id))
        .map(|group| {
            let cursor = cursors.iter().find(|row| {
                same_provider(&row.key.provider_instance_id, provider_instance_id)
                    && row.key.device_id == group.equipment_id
                    && row.key.model_revision == revision
            });
            DeviceStatus {
                device_id: group.equipment_id.clone(),
                approved_points: group.points.len(),
                withheld_points: plan
                    .withheld
                    .iter()
                    .filter(|row| {
                        same_provider(&row.provider_instance_id, provider_instance_id)
                            && row.equipment_id == group.equipment_id
                    })
                    .count(),
                verified_through: cursor.map(|row| row.verified_through),
                hole: cursor.and_then(|row| row.hole.clone()),
                state: device_state(cursor, planned_through),
            }
        })
        .collect();
    let approved_points = devices.iter().map(|row| row.approved_points).sum();
    let withheld_points = plan
        .withheld
        .iter()
        .filter(|row| same_provider(&row.provider_instance_id, provider_instance_id))
        .count();
    let verified_through = if devices.iter().all(|row| row.verified_through.is_some()) {
        devices.iter().filter_map(|row| row.verified_through).min()
    } else {
        None
    };
    let state = devices
        .iter()
        .map(|row| row.state)
        .max_by_key(|state| rank(state))
        .unwrap_or(NOT_ASSESSED);
    let oldest_gap = gaps
        .iter()
        .find(|job| {
            same_provider(&job.provider_instance_id, provider_instance_id)
                && job.model_revision == revision
        })
        .map(|job| OldestGap {
            device_id: job.device_id.clone(),
            start: job.logical_window_start,
            end: job.logical_window_end,
            state: job.state.clone(),
            code: job.safe_error_code.clone(),
        });
    let state_reason = if state == NOT_ASSESSED {
        Some(not_assessed_reason(plan, provider_instance_id, &devices))
    } else {
        None
    };
    ProviderStatus {
        provider_instance_id: provider_instance_id.to_string(),
        model_revision: Some(plan.revision_id.clone()),
        approved_points,
        withheld_points,
        discovered_points: approved_points + withheld_points,
        verified_through,
        devices,
        oldest_gap,
        state,
        state_reason,
    }
}

/// Site-level reason when every provider is not assessed for the same root cause.
pub fn site_not_assessed_reason(statuses: &[ProviderStatus]) -> Option<&'static str> {
    if statuses.is_empty() || statuses.iter().any(|row| row.state != NOT_ASSESSED) {
        return None;
    }
    let first = statuses[0].state_reason?;
    if statuses.iter().all(|row| row.state_reason == Some(first)) {
        Some(first)
    } else {
        Some("coverage_not_assessed")
    }
}

#[cfg(test)]
mod tests {
    use chrono::Duration;

    use super::*;
    use crate::ingest_queue::cursor::CursorKey;
    use crate::ingest_queue::memory::MemoryStore;
    use crate::ingest_queue::model::{BudgetDefaults, EnqueueOutcome, NewJob};
    use crate::providers::committed_model::{IngestDeviceGroup, PlannedPoint, WithheldPoint};

    const NF: &str = "nf:site-a";
    const REV: &str = "rev-1";

    fn at(raw: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(raw)
            .unwrap()
            .with_timezone(&Utc)
    }

    fn point(id: &str) -> PlannedPoint {
        PlannedPoint {
            semantic_point_id: format!("s-{id}"),
            source_point_id: id.into(),
            canonical_role: "supply_air_temp".into(),
            kind: None,
            source_unit: None,
            canonical_unit: None,
            quantity: None,
            history_mode: None,
            cadence_secs: None,
            heartbeat_secs: None,
        }
    }

    fn plan() -> IngestPlan {
        let group = |device: &str, points: &[&str]| IngestDeviceGroup {
            provider_instance_id: NF.into(),
            equipment_id: device.into(),
            equip_type: "ahu".into(),
            points: points.iter().map(|id| point(id)).collect(),
        };
        IngestPlan {
            schema: "test".into(),
            revision_id: REV.into(),
            tenant_id: "t".into(),
            site_id: "site-a".into(),
            groups: vec![
                group("ahu-1", &["p1", "p2"]),
                group("ahu-2", &["p3"]),
                IngestDeviceGroup {
                    provider_instance_id: "nf:other".into(),
                    ..group("ahu-9", &["p9"])
                },
            ],
            withheld: vec![WithheldPoint {
                provider_instance_id: NF.into(),
                equipment_id: "ahu-1".into(),
                semantic_point_id: "s-p4".into(),
                source_point_id: "p4".into(),
                reason: "unmapped".into(),
            }],
        }
    }

    fn cursor(
        device: &str,
        revision: &str,
        through: &str,
        hole: Option<(&str, Option<&str>)>,
    ) -> CoverageCursor {
        let verified_through = at(through);
        CoverageCursor {
            key: CursorKey {
                tenant_id: "t".into(),
                canonical_site: "site-a".into(),
                provider_instance_id: NF.into(),
                device_id: device.into(),
                model_revision: revision.into(),
            },
            verified_through,
            hole: hole.map(|(state, code)| CursorHole {
                at: verified_through,
                state: state.into(),
                code: code.map(str::to_string),
            }),
            updated_at: verified_through,
        }
    }

    fn gap(device: &str, revision: &str, start: &str, state: &str) -> JobView {
        let store = MemoryStore::new(BudgetDefaults::default());
        let start = at(start);
        let job = NewJob {
            tenant_id: "t".into(),
            canonical_site: "site-a".into(),
            provider_instance_id: NF.into(),
            device_id: device.into(),
            model_revision: revision.into(),
            logical_window_start: start,
            logical_window_end: start + Duration::hours(1),
            shard: String::new(),
            not_before: start,
            estimated_cost: 1,
            requested_points_digest: None,
        };
        let mut view = match store.enqueue(job, start).unwrap() {
            EnqueueOutcome::Created(view) | EnqueueOutcome::Existing(view) => view,
        };
        view.state = state.into();
        view.safe_error_code = Some("retention_exceeded".into());
        view
    }

    #[test]
    fn device_state_follows_the_cursor_and_its_hole() {
        let planned = at("2026-10-20T12:00:00Z");
        assert_eq!(device_state(None, planned), NOT_ASSESSED);
        let done = cursor(
            "ahu-1",
            REV,
            "2026-10-20T12:00:00Z",
            Some((NOT_SCHEDULED, None)),
        );
        assert_eq!(device_state(Some(&done), planned), VERIFIED);
        let unplanned = cursor(
            "ahu-1",
            REV,
            "2026-10-20T11:00:00Z",
            Some((NOT_SCHEDULED, None)),
        );
        assert_eq!(device_state(Some(&unplanned), planned), BEHIND);
        let queued = cursor("ahu-1", REV, "2026-10-20T11:00:00Z", Some(("queued", None)));
        assert_eq!(device_state(Some(&queued), planned), BEHIND);
        let failed = cursor(
            "ahu-1",
            REV,
            "2026-10-20T11:00:00Z",
            Some(("permanent_failure", Some("retention_exceeded"))),
        );
        assert_eq!(device_state(Some(&failed), planned), GAP);
        let partial = cursor(
            "ahu-1",
            REV,
            "2026-10-20T11:00:00Z",
            Some(("partial", None)),
        );
        assert_eq!(device_state(Some(&partial), planned), GAP);
        let unknown = cursor(
            "ahu-1",
            REV,
            "2026-10-20T11:00:00Z",
            Some(("committed", Some(NOT_ASSESSED))),
        );
        assert_eq!(device_state(Some(&unknown), planned), NOT_ASSESSED);
        let incomplete = cursor(
            "ahu-1",
            REV,
            "2026-10-20T11:00:00Z",
            Some(("committed", Some("incomplete"))),
        );
        assert_eq!(device_state(Some(&incomplete), planned), GAP);
    }

    #[test]
    fn provider_status_counts_points_and_takes_the_worst_device() {
        let planned = at("2026-10-20T12:00:00Z");
        let plan = plan();
        let cursors = vec![
            cursor("ahu-1", REV, "2026-10-20T12:00:00Z", None),
            cursor(
                "ahu-2",
                REV,
                "2026-10-20T10:00:00Z",
                Some(("retry_wait", None)),
            ),
            cursor("ahu-2", "rev-0", "2026-10-20T12:00:00Z", None),
        ];
        let gaps = vec![
            gap(
                "ahu-2",
                "rev-0",
                "2026-10-19T01:00:00Z",
                "permanent_failure",
            ),
            gap("ahu-2", REV, "2026-10-20T10:00:00Z", "retry_wait"),
        ];
        let status = provider_status(NF, Some(&plan), &cursors, &gaps, planned);
        assert_eq!(status.model_revision.as_deref(), Some(REV));
        assert_eq!(status.approved_points, 3);
        assert_eq!(status.withheld_points, 1);
        assert_eq!(status.discovered_points, 4);
        assert_eq!(status.devices.len(), 2);
        assert_eq!(status.devices[0].state, VERIFIED);
        assert_eq!(status.devices[0].withheld_points, 1);
        assert_eq!(status.devices[1].state, GAP);
        assert_eq!(status.state, GAP);
        assert_eq!(status.verified_through, Some(at("2026-10-20T10:00:00Z")));
        let oldest = status.oldest_gap.expect("gap for the active revision");
        assert_eq!(oldest.device_id, "ahu-2");
        assert_eq!(oldest.start, at("2026-10-20T10:00:00Z"));
        assert_eq!(oldest.state, "retry_wait");
    }

    #[test]
    fn cadence_binding_drives_not_assessed_reason() {
        let planned = at("2026-10-20T12:00:00Z");
        let mut plan = plan();
        plan.groups[0].points[0].history_mode = Some("interval".into());
        plan.groups[0].points[0].cadence_secs = Some(300);
        let status = provider_status(NF, Some(&plan), &[], &[], planned);
        assert_eq!(status.state, NOT_ASSESSED);
        assert_eq!(status.state_reason, Some("no_verified_cursor"));

        for group in &mut plan.groups {
            for point in &mut group.points {
                point.history_mode = None;
                point.cadence_secs = None;
            }
        }
        let unbound = provider_status(NF, Some(&plan), &[], &[], planned);
        assert_eq!(unbound.state_reason, Some("cadence_not_bound"));
    }

    #[test]
    fn missing_cursor_or_plan_is_never_verified() {
        let planned = at("2026-10-20T12:00:00Z");
        let plan = plan();
        let cursors = vec![cursor("ahu-1", REV, "2026-10-20T12:00:00Z", None)];
        let status = provider_status(NF, Some(&plan), &cursors, &[], planned);
        assert_eq!(status.devices[1].state, NOT_ASSESSED);
        assert_eq!(status.state, NOT_ASSESSED);
        assert_eq!(status.verified_through, None);
        assert_eq!(status.oldest_gap, None);

        let unplanned = provider_status(NF, None, &cursors, &[], planned);
        assert_eq!(unplanned.state, NOT_CONFIGURED);
        assert!(unplanned.devices.is_empty());

        let other = provider_status("nf:none", Some(&plan), &cursors, &[], planned);
        assert!(other.devices.is_empty());
        assert_eq!(other.state, NOT_ASSESSED);
        assert_ne!(other.state, VERIFIED);
    }
}
