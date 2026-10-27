//! Daily catch-up against a fake NF portal that drops one 5-minute slot.
//!
//! The scheduler plans the previous Chicago day, the real NF driver reads
//! history over HTTP, coverage reconciles every slot, and the verified cursor
//! stops at the hour with the missing slot. That hour waits for the next daily
//! run. Once the portal serves the slot, it commits and the cursor reaches the
//! end of the day. A slot that never arrives becomes `retention_exceeded`.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use chrono::{DateTime, Duration, Utc};
use chrono_tz::Tz;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

use super::super::coverage::{reconcile, Expectation, PointExpectation, ReconcileInput};
use super::super::cursor::CursorKey;
use super::super::memory::MemoryStore;
use super::super::model::{
    operator_retry_allowed, BudgetDefaults, ClaimRequest, FinishRequest, ListFilter,
};
use super::super::schedule::{apply_daily_policy, daily_windows, IngestSchedule, ScheduleDevice};
use super::{applied_samples, decide_window, observations_for, DecideWindow, EMPTY_RECEIPT};
use crate::providers::http_policy::{HttpLimits, MAX_HISTORY_WINDOW, MAX_UUIDS_PER_REQUEST};
use crate::providers::nf::NfPortalDriver;

const SAT: &str = "f93888d3-e498-3a30-a881-eb5cbd4c40a8";
const RAT: &str = "0b5f7a2e-1c3d-4e5f-8a9b-0c1d2e3f4a5b";
const CADENCE: i64 = 300;

fn at(raw: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(raw)
        .unwrap()
        .with_timezone(&Utc)
}

fn chicago() -> Tz {
    chrono_tz::America::Chicago
}

fn missing_slot() -> DateTime<Utc> {
    at("2026-10-19T14:25:00Z")
}

fn query_pairs(request: &str) -> Vec<(String, String)> {
    let target = request.split_whitespace().nth(1).unwrap_or("");
    let query = target.split_once('?').map_or("", |(_, query)| query);
    query
        .split('&')
        .filter_map(|pair| pair.split_once('='))
        .map(|(key, value)| (key.to_string(), value.replace("%2D", "-")))
        .collect()
}

fn history_body(request: &str, repaired: bool) -> String {
    let pairs = query_pairs(request);
    let seconds = |key: &str| -> i64 {
        pairs
            .iter()
            .find(|(name, _)| name == key)
            .and_then(|(_, value)| value.parse().ok())
            .unwrap()
    };
    let (from, to) = (seconds("from.seconds"), seconds("to.seconds"));
    assert!(to - from <= MAX_HISTORY_WINDOW.num_seconds());
    let uuids: Vec<&str> = pairs
        .iter()
        .filter(|(name, _)| name == "uuids")
        .flat_map(|(_, value)| value.split(','))
        .collect();
    assert!(!uuids.is_empty() && uuids.len() <= MAX_UUIDS_PER_REQUEST);
    let mut data = Vec::new();
    for uuid in uuids {
        let mut values = Vec::new();
        let mut slot = from - from.rem_euclid(CADENCE);
        if slot < from {
            slot += CADENCE;
        }
        while slot < to {
            let ts = DateTime::from_timestamp(slot, 0).unwrap();
            if repaired || uuid != SAT || ts != missing_slot() {
                values.push(serde_json::json!({
                    "ts": ts.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
                    "double": 70.5,
                    "quality": "good"
                }));
            }
            slot += CADENCE;
        }
        data.push(serde_json::json!({"uuid": uuid, "values": values}));
    }
    serde_json::json!({ "data": data }).to_string()
}

async fn fake_portal(repaired: Arc<AtomicBool>) -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    tokio::spawn(async move {
        while let Ok((mut sock, _)) = listener.accept().await {
            let repaired = Arc::clone(&repaired);
            tokio::spawn(async move {
                let mut buf = vec![0u8; 16384];
                let mut got = Vec::new();
                while !got.windows(4).any(|w| w == b"\r\n\r\n") {
                    match sock.read(&mut buf).await {
                        Ok(0) | Err(_) => return,
                        Ok(n) => got.extend_from_slice(&buf[..n]),
                    }
                }
                let request = String::from_utf8_lossy(&got).to_string();
                let body = if request.contains("/api/v1/auth/token") {
                    r#"{"accessToken":"tok-abc","expiresIn":3600}"#.to_string()
                } else if request.contains("/api/v1/point/data") {
                    history_body(&request, repaired.load(Ordering::SeqCst))
                } else {
                    "{}".to_string()
                };
                let reply = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
                let _ = sock.write_all(reply.as_bytes()).await;
            });
        }
    });
    port
}

fn device() -> ScheduleDevice {
    ScheduleDevice {
        tenant_id: "tenant-daily".into(),
        canonical_site: "site-daily".into(),
        provider_instance_id: "nf:daily".into(),
        device_id: "AHU_1".into(),
        model_revision: "rev-daily".into(),
        estimated_cost: 1,
        point_ids: vec![SAT.into(), RAT.into()],
    }
}

fn key() -> CursorKey {
    let device = device();
    CursorKey {
        tenant_id: device.tenant_id,
        canonical_site: device.canonical_site,
        provider_instance_id: device.provider_instance_id,
        device_id: device.device_id,
        model_revision: device.model_revision,
    }
}

fn expectations() -> Vec<PointExpectation> {
    [SAT, RAT]
        .into_iter()
        .map(|point_id| PointExpectation {
            point_id: point_id.into(),
            expectation: Expectation::Interval {
                cadence_secs: CADENCE,
            },
        })
        .collect()
}

fn store() -> MemoryStore {
    MemoryStore::new(BudgetDefaults {
        max_in_flight: 64,
        max_per_minute: 100_000,
    })
}

const DELAY_MINUTES: i64 = 5;

/// One scheduler run at `now`: claim everything due and finish it.
async fn run_daily(store: &MemoryStore, driver: &mut NfPortalDriver, now: DateTime<Utc>) -> usize {
    let policy = IngestSchedule::Daily { tz: chicago() };
    let expectations = expectations();
    let mut processed = 0;
    loop {
        let claimed = store.claim(&ClaimRequest {
            owner: "daily-test".into(),
            limit: 64,
            now,
            lease_for: Duration::seconds(180),
        });
        if claimed.is_empty() {
            return processed;
        }
        for job in claimed {
            let uuids = vec![SAT.to_string(), RAT.to_string()];
            let page = driver
                .read_history_page(&uuids, job.logical_window_start, job.logical_window_end)
                .await
                .unwrap();
            let observations = observations_for(&expectations, &page);
            let report = reconcile(&ReconcileInput {
                start: job.logical_window_start,
                end: job.logical_window_end,
                expectations: &expectations,
                observations: &observations,
                prior: &job.point_coverage,
                response_complete: true,
            })
            .unwrap();
            let applied = applied_samples(&page, job.logical_window_start, job.logical_window_end);
            let outcome = decide_window(&DecideWindow {
                job_revision: &job.model_revision,
                active_revision: Some(&job.model_revision),
                job_digest: None,
                active_digest: None,
                coverage: &report,
                attempt: job.attempt,
                now,
                written: &EMPTY_RECEIPT,
                applied: &applied,
            });
            let outcome = apply_daily_policy(
                outcome,
                policy,
                job.logical_window_start,
                now,
                Duration::minutes(DELAY_MINUTES),
                Duration::days(7),
            );
            let mut finish =
                FinishRequest::new("daily-test", job.job_id, job.fencing_token, now, outcome);
            finish.applied_samples = applied;
            store.finish(&finish).unwrap();
            store.advance_cursor(&key(), now).unwrap();
            processed += 1;
        }
    }
}

fn states(store: &MemoryStore) -> HashMap<DateTime<Utc>, (String, Option<String>, DateTime<Utc>)> {
    store
        .list_jobs(&ListFilter {
            sites: None,
            tenant_id: Some("tenant-daily".into()),
            state: None,
            limit: 500,
        })
        .into_iter()
        .map(|job| {
            (
                job.logical_window_start,
                (job.state, job.safe_error_code, job.not_before),
            )
        })
        .collect()
}

async fn plan_day(store: &MemoryStore, now: DateTime<Utc>) -> usize {
    let jobs = daily_windows(
        now,
        chicago(),
        Duration::minutes(DELAY_MINUTES),
        1,
        0,
        3600,
        &[device()],
    )
    .unwrap();
    assert!(jobs
        .iter()
        .all(|job| job.logical_window_end - job.logical_window_start <= MAX_HISTORY_WINDOW));
    let count = jobs.len();
    for job in jobs {
        store.enqueue(job, now).unwrap();
    }
    count
}

fn driver(port: u16) -> NfPortalDriver {
    NfPortalDriver::new(
        "nf:daily",
        format!("http://127.0.0.1:{port}"),
        Some("lab-id".into()),
        Some("lab-secret".into()),
        false,
        HttpLimits::default(),
    )
    .unwrap()
}

#[tokio::test]
async fn missing_slot_holds_the_cursor_until_the_portal_repairs_it() {
    let repaired = Arc::new(AtomicBool::new(false));
    let port = fake_portal(Arc::clone(&repaired)).await;
    let mut nf = driver(port);
    let store = store();
    let first_run = at("2026-10-20T05:06:00Z");
    assert_eq!(plan_day(&store, first_run).await, 24);
    assert_eq!(run_daily(&store, &mut nf, first_run).await, 24);

    let hole_hour = at("2026-10-19T14:00:00Z");
    let next_run = at("2026-10-21T05:05:00Z");
    let jobs = states(&store);
    let (state, code, not_before) = jobs.get(&hole_hour).unwrap().clone();
    assert_eq!(state, "retry_wait");
    assert_eq!(code.as_deref(), Some("genuine_gap"));
    assert_eq!(not_before, next_run);
    assert_eq!(
        jobs.values()
            .filter(|(state, _, _)| state == "committed")
            .count(),
        23
    );
    let cursor = store.advance_cursor(&key(), first_run).unwrap();
    assert_eq!(cursor.verified_through, hole_hour);
    let hole = cursor.hole.unwrap();
    assert_eq!(hole.state, "retry_wait");
    assert_eq!(hole.code.as_deref(), Some("genuine_gap"));

    // Negative control: before the next daily run nothing is claimable.
    assert_eq!(
        run_daily(&store, &mut nf, next_run - Duration::minutes(1)).await,
        0
    );
    assert_eq!(states(&store).get(&hole_hour).unwrap().0, "retry_wait");

    repaired.store(true, Ordering::SeqCst);
    assert_eq!(run_daily(&store, &mut nf, next_run).await, 1);
    assert_eq!(states(&store).get(&hole_hour).unwrap().0, "committed");
    let cursor = store.advance_cursor(&key(), next_run).unwrap();
    assert_eq!(cursor.verified_through, at("2026-10-20T05:00:00Z"));
    assert!(cursor.hole.is_none());
}

#[tokio::test]
async fn unrepaired_slot_becomes_a_retention_gap() {
    let port = fake_portal(Arc::new(AtomicBool::new(false))).await;
    let mut nf = driver(port);
    let store = store();
    let first_run = at("2026-10-20T05:06:00Z");
    plan_day(&store, first_run).await;
    run_daily(&store, &mut nf, first_run).await;
    let hole_hour = at("2026-10-19T14:00:00Z");

    // Still inside retention: the window waits for the following run.
    let second_run = at("2026-10-21T05:05:00Z");
    assert_eq!(run_daily(&store, &mut nf, second_run).await, 1);
    let (state, _, not_before) = states(&store).get(&hole_hour).unwrap().clone();
    assert_eq!(state, "retry_wait");
    assert_eq!(not_before, at("2026-10-22T05:05:00Z"));

    // The run after which the source no longer retains the window.
    let late_run = at("2026-10-26T05:05:00Z");
    assert_eq!(run_daily(&store, &mut nf, late_run).await, 1);
    let (state, code, _) = states(&store).get(&hole_hour).unwrap().clone();
    assert_eq!(state, "permanent_failure");
    assert_eq!(code.as_deref(), Some("retention_exceeded"));
    assert!(!operator_retry_allowed(&state, code.as_deref()));
    assert_eq!(
        run_daily(&store, &mut nf, late_run + Duration::days(2)).await,
        0
    );

    let cursor = store.advance_cursor(&key(), late_run).unwrap();
    assert_eq!(cursor.verified_through, hole_hour);
    let hole = cursor.hole.unwrap();
    assert_eq!(hole.state, "permanent_failure");
    assert_eq!(hole.code.as_deref(), Some("retention_exceeded"));
    let gaps = store.list_gaps(&ListFilter {
        sites: None,
        tenant_id: Some("tenant-daily".into()),
        state: None,
        limit: 50,
    });
    assert_eq!(gaps.len(), 1);
}
