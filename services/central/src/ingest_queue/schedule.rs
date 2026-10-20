//! Bounded completed-hour planning. This is not the N5 checkpoint walk.
//!
//! Each tick enqueues at most `catchup_hours` exact UTC hours per device.
//! Windows already present stay unique. Older retention recovery is a backfill.

use chrono::{DateTime, Duration, Timelike, Utc};

use super::model::{NewJob, MAX_CATCHUP_HOURS};

#[derive(Debug, Clone)]
pub struct ScheduleDevice {
    pub tenant_id: String,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: String,
    pub estimated_cost: u32,
}

pub fn due_windows(
    now: DateTime<Utc>,
    publication_delay: Duration,
    catchup_hours: u32,
    stagger_spread_secs: u64,
    devices: &[ScheduleDevice],
) -> Vec<NewJob> {
    let catchup = catchup_hours.clamp(1, MAX_CATCHUP_HOURS);
    let effective = now - publication_delay;
    let latest_end = floor_hour(effective);
    let mut jobs = Vec::new();
    for device in devices {
        let stagger = stagger_secs(&device.device_id, stagger_spread_secs);
        for age in 0..catchup {
            let logical_window_end = latest_end - Duration::hours(i64::from(age));
            let logical_window_start = logical_window_end - Duration::hours(1);
            let not_before = if age == 0 {
                logical_window_end + publication_delay + Duration::seconds(stagger as i64)
            } else {
                now
            };
            jobs.push(NewJob {
                tenant_id: device.tenant_id.clone(),
                canonical_site: device.canonical_site.clone(),
                provider_instance_id: device.provider_instance_id.clone(),
                device_id: device.device_id.clone(),
                model_revision: device.model_revision.clone(),
                logical_window_start,
                logical_window_end,
                shard: String::new(),
                not_before,
                estimated_cost: device.estimated_cost.max(1),
                requested_points_digest: None,
            });
        }
    }
    jobs
}

fn floor_hour(ts: DateTime<Utc>) -> DateTime<Utc> {
    let date = ts.date_naive();
    let hour = ts.time().hour();
    date.and_hms_opt(hour, 0, 0)
        .or_else(|| date.and_hms_opt(0, 0, 0))
        .map(|naive| naive.and_utc())
        .unwrap_or(ts)
}

fn stagger_secs(device_id: &str, spread: u64) -> u64 {
    if spread == 0 {
        return 0;
    }
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in device_id.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash % spread
}

#[cfg(test)]
mod tests {
    use super::*;

    fn device(id: &str) -> ScheduleDevice {
        ScheduleDevice {
            tenant_id: "t".into(),
            canonical_site: "site".into(),
            provider_instance_id: "nf:site".into(),
            device_id: id.into(),
            model_revision: "rev".into(),
            estimated_cost: 3,
        }
    }

    #[test]
    fn resume_enqueues_missed_completed_hours() {
        let now = DateTime::parse_from_rfc3339("2026-10-19T13:05:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let jobs = due_windows(now, Duration::minutes(5), 5, 0, &[device("ahu")]);
        let windows: Vec<_> = jobs
            .iter()
            .map(|job| {
                (
                    job.logical_window_start.to_rfc3339(),
                    job.logical_window_end.to_rfc3339(),
                )
            })
            .collect();
        assert_eq!(
            windows,
            vec![
                (
                    "2026-10-19T12:00:00+00:00".into(),
                    "2026-10-19T13:00:00+00:00".into()
                ),
                (
                    "2026-10-19T11:00:00+00:00".into(),
                    "2026-10-19T12:00:00+00:00".into()
                ),
                (
                    "2026-10-19T10:00:00+00:00".into(),
                    "2026-10-19T11:00:00+00:00".into()
                ),
                (
                    "2026-10-19T09:00:00+00:00".into(),
                    "2026-10-19T10:00:00+00:00".into()
                ),
                (
                    "2026-10-19T08:00:00+00:00".into(),
                    "2026-10-19T09:00:00+00:00".into()
                ),
            ]
        );
    }

    #[test]
    fn devices_stagger_the_newest_window_only() {
        let now = DateTime::parse_from_rfc3339("2026-10-19T13:05:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let jobs = due_windows(
            now,
            Duration::minutes(5),
            2,
            300,
            &[device("ahu-a"), device("ahu-b")],
        );
        let a = jobs.iter().find(|job| job.device_id == "ahu-a").unwrap();
        let b = jobs.iter().find(|job| job.device_id == "ahu-b").unwrap();
        assert_ne!(a.not_before, b.not_before);
        assert!(jobs
            .iter()
            .filter(|job| job.logical_window_start
                == DateTime::parse_from_rfc3339("2026-10-19T11:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc))
            .all(|job| job.not_before == now));
    }
}
