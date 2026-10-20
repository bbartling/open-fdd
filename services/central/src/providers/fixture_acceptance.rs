//! Offline N12 fixture acceptance.
//!
//! Pages are local GetData JSON. Nothing in this module opens a portal client.
//! Rows are the Timescale `SampleRow` projection (`point_to_sample`), upserted
//! by point id and source timestamp. A live read-only NF pilot is not this suite.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, Mutex as StdMutex};

use chrono::{DateTime, Duration, TimeZone, Utc};
use futures_util::future::BoxFuture;

use super::hourly::{classify_history_status, model_revision, FetchError, HourlyPolicy};
use super::hourly_exec::{run_hourly_tick, FetchRequest, HistorySource, SampleWriter, TickInput};
use super::http_policy::{floor_timestamp_micros, MAX_SAMPLES_PER_RESPONSE};
use super::map::{DevicePoints, HistorySeries, MappedPoint, RawProviderPoint};
use super::nf::{history_http_method, parse_get_data_json};
use super::store::{CheckpointKey, CommitPatch, HourlyStore, JobState, NewJob, ReceiptDraft};
use super::types::NormalizedSample;
use super::writer::project_historian_rows;
use crate::providers::error::ProviderErrorCode;
use crate::timescale_historian::{historian_error_drops_connection, TimescaleConnectGate};

const OA: &str = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const SAT: &str = "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const SITE: &str = "site-a";
const PROVIDER: &str = "nf:site-a";
const DEVICE: &str = "ahu-1";
const TENANT: &str = "default";
const EXACT_FIXTURE: &str = include_str!("../../fixtures/nf/hour_exact.json");

#[derive(Clone, Debug, PartialEq, Eq)]
struct RowSnap {
    site: String,
    equipment: String,
    point: String,
    role: String,
    micros: i64,
    val_bits: u64,
    unit: Option<String>,
    quality: Option<String>,
}

#[derive(Default)]
struct FixtureHistorian {
    rows: BTreeMap<(String, i64), RowSnap>,
}

impl FixtureHistorian {
    fn upsert(&mut self, samples: &[NormalizedSample]) {
        let projected = project_historian_rows(SITE, samples).expect("historian projection");
        for row in projected {
            let point = row.haystack_id.clone().unwrap_or_default();
            let micros = row.ts.timestamp_micros();
            let snap = RowSnap {
                site: row.site_id,
                equipment: row.equipment_id.unwrap_or_default(),
                point: point.clone(),
                role: row.role.unwrap_or_default(),
                micros,
                val_bits: row.val.unwrap_or(f64::NAN).to_bits(),
                unit: row.unit,
                quality: row.quality,
            };
            self.rows.insert((point, micros), snap);
        }
    }

    fn len(&self) -> usize {
        self.rows.len()
    }

    fn get(&self, point: &str, at: DateTime<Utc>) -> &RowSnap {
        self.rows
            .get(&(point.to_string(), at.timestamp_micros()))
            .unwrap_or_else(|| panic!("missing {point} at {at}"))
    }
}

enum WriteMode {
    Ok,
    Disconnect { remaining: usize },
    CrashAfterPersist { remaining: usize },
}

struct DbWriter {
    db: Arc<StdMutex<FixtureHistorian>>,
    mode: WriteMode,
}

impl SampleWriter for DbWriter {
    fn write<'a>(
        &'a mut self,
        samples: &'a [NormalizedSample],
    ) -> BoxFuture<'a, Result<usize, String>> {
        Box::pin(async move {
            match &mut self.mode {
                WriteMode::Disconnect { remaining } if *remaining > 0 => {
                    *remaining -= 1;
                    return Err("connection refused".into());
                }
                WriteMode::CrashAfterPersist { remaining } if *remaining > 0 => {
                    self.db.lock().expect("db").upsert(samples);
                    *remaining -= 1;
                    return Err("crash_before_receipt".into());
                }
                _ => {}
            }
            self.db.lock().expect("db").upsert(samples);
            Ok(samples.len())
        })
    }
}

struct Catalog {
    by_window: BTreeMap<DateTime<Utc>, Vec<HistorySeries>>,
    calls: StdMutex<Vec<FetchRequest>>,
}

impl HistorySource for Catalog {
    fn fetch<'a>(
        &'a mut self,
        req: &'a FetchRequest,
    ) -> BoxFuture<'a, Result<Vec<HistorySeries>, FetchError>> {
        Box::pin(async move {
            self.calls.lock().expect("calls").push(req.clone());
            Ok(self
                .by_window
                .get(&req.window_start)
                .cloned()
                .unwrap_or_default())
        })
    }
}

struct ThrottleThen {
    page: Vec<HistorySeries>,
    hits: StdMutex<u32>,
}

impl HistorySource for ThrottleThen {
    fn fetch<'a>(
        &'a mut self,
        _req: &'a FetchRequest,
    ) -> BoxFuture<'a, Result<Vec<HistorySeries>, FetchError>> {
        Box::pin(async move {
            let mut hits = self.hits.lock().expect("hits");
            *hits += 1;
            if *hits == 1 {
                return Err(classify_history_status(429, Some(45)));
            }
            Ok(self.page.clone())
        })
    }
}

struct StealWriter {
    db: Arc<StdMutex<FixtureHistorian>>,
    store: HourlyStore,
    now: DateTime<Utc>,
    armed: bool,
}

impl SampleWriter for StealWriter {
    fn write<'a>(
        &'a mut self,
        samples: &'a [NormalizedSample],
    ) -> BoxFuture<'a, Result<usize, String>> {
        Box::pin(async move {
            self.db.lock().expect("db").upsert(samples);
            if self.armed {
                let stolen = self
                    .store
                    .claim(
                        SITE,
                        self.now + Duration::seconds(30),
                        4,
                        "worker-b",
                        Duration::seconds(30),
                    )
                    .await
                    .expect("steal claim");
                assert_eq!(stolen.len(), 1, "expired lease must move to worker-b");
                self.armed = false;
            }
            Ok(samples.len())
        })
    }
}

fn at(hour: u32, min: u32, sec: u32) -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 10, 18, hour, min, sec).unwrap()
}

fn quiet_policy() -> HourlyPolicy {
    HourlyPolicy {
        stagger_spread_secs: 0,
        retry_jitter_secs: 0,
        reconcile_hours: 0,
        max_claims_per_tick: 8,
        bootstrap: Duration::seconds(3600),
        overlap: Duration::seconds(0),
        publication_delay: Duration::seconds(300),
        lease: Duration::seconds(120),
        ..HourlyPolicy::default()
    }
}

fn point_map(points: &[(&str, &str)]) -> DevicePoints {
    DevicePoints {
        device_id: DEVICE.into(),
        points: points
            .iter()
            .map(|(id, role)| MappedPoint {
                provider_point_id: (*id).to_string(),
                role: (*role).to_string(),
                equip_type: Some("ahu".into()),
            })
            .collect(),
    }
}

fn revision(device: &DevicePoints) -> String {
    model_revision(
        &device.device_id,
        &device
            .points
            .iter()
            .map(|p| {
                (
                    p.provider_point_id.clone(),
                    p.role.clone(),
                    p.equip_type.clone(),
                )
            })
            .collect::<Vec<_>>(),
    )
}

fn key_for(device: &DevicePoints) -> CheckpointKey {
    CheckpointKey {
        tenant: TENANT.into(),
        canonical_site: SITE.into(),
        provider_instance: PROVIDER.into(),
        device_id: device.device_id.clone(),
        model_revision: revision(device),
    }
}

fn tick<'a>(
    now: DateTime<Utc>,
    devices: &'a [DevicePoints],
    policy: &'a HourlyPolicy,
    owner: &'a str,
) -> TickInput<'a> {
    TickInput {
        now,
        tenant: TENANT,
        canonical_site: SITE,
        provider_instance: PROVIDER,
        devices,
        policy,
        owner,
    }
}

fn group(points: Vec<RawProviderPoint>) -> Vec<HistorySeries> {
    let mut grouped: BTreeMap<String, Vec<RawProviderPoint>> = BTreeMap::new();
    for point in points {
        grouped
            .entry(point.provider_point_id.clone())
            .or_default()
            .push(point);
    }
    grouped
        .into_iter()
        .map(|(provider_point_id, samples)| HistorySeries {
            provider_point_id,
            samples,
        })
        .collect()
}

fn exact_page() -> Vec<HistorySeries> {
    group(parse_get_data_json(EXACT_FIXTURE).expect("exact fixture"))
}

fn catalog(window: DateTime<Utc>, page: Vec<HistorySeries>) -> Catalog {
    let mut by_window = BTreeMap::new();
    by_window.insert(window, page);
    Catalog {
        by_window,
        calls: StdMutex::new(Vec::new()),
    }
}

struct Expect {
    point: &'static str,
    rfc: &'static str,
    val: f64,
    quality: Option<&'static str>,
    role: &'static str,
}

fn expected_exact() -> Vec<Expect> {
    vec![
        Expect {
            point: OA,
            rfc: "2026-10-18T09:00:00.123456789Z",
            val: 70.5,
            quality: Some("good"),
            role: "oa_t",
        },
        Expect {
            point: OA,
            rfc: "2026-10-18T09:15:00Z",
            val: 71.0,
            quality: Some("uncertain"),
            role: "oa_t",
        },
        Expect {
            point: OA,
            rfc: "2026-10-18T09:30:00Z",
            val: 71.5,
            quality: None,
            role: "oa_t",
        },
        Expect {
            point: OA,
            rfc: "2026-10-18T09:45:00Z",
            val: 72.0,
            quality: Some("stale"),
            role: "oa_t",
        },
        Expect {
            point: SAT,
            rfc: "2026-10-18T09:05:00Z",
            val: 55.25,
            quality: Some("bad"),
            role: "sat",
        },
        Expect {
            point: SAT,
            rfc: "2026-10-18T09:06:00Z",
            val: 55.5,
            quality: Some("good"),
            role: "sat",
        },
    ]
}

fn assert_exact_set(db: &FixtureHistorian) {
    let expected = expected_exact();
    assert_eq!(db.len(), expected.len());
    for exp in &expected {
        let ts = floor_timestamp_micros(
            DateTime::parse_from_rfc3339(exp.rfc)
                .unwrap()
                .with_timezone(&Utc),
        );
        let snap = db.get(exp.point, ts);
        assert_eq!(snap.val_bits, exp.val.to_bits(), "{}", exp.rfc);
        assert_eq!(snap.unit.as_deref(), Some("°F"));
        assert_eq!(snap.quality.as_deref(), exp.quality);
        assert_eq!(snap.role, exp.role);
        assert_ne!(snap.role, "mat");
        assert_eq!(snap.equipment, DEVICE);
        assert_eq!(snap.site, SITE);
        assert_eq!(snap.micros, ts.timestamp_micros());
    }
    let banned = [11.0_f64, 99.0, 12345.0];
    assert!(db
        .rows
        .values()
        .all(|row| banned.iter().all(|v| row.val_bits != v.to_bits())));
}

fn job_draft(start: DateTime<Utc>, device: &str) -> NewJob {
    NewJob {
        tenant: TENANT.into(),
        canonical_site: SITE.into(),
        provider_instance: PROVIDER.into(),
        device_id: device.into(),
        model_revision: "rev-fence".into(),
        window_start: start,
        window_end: start + Duration::seconds(3600),
        shard: 0,
        shard_count: 1,
        purpose: "hourly".into(),
        generation: 0,
        not_before: start,
        point_ids: vec![OA.into()],
    }
}

fn receipt(job_id: &str, now: DateTime<Utc>, receipt_id: &str) -> CommitPatch {
    CommitPatch {
        now,
        receipt: ReceiptDraft {
            receipt_id: receipt_id.into(),
            job_id: job_id.into(),
            outcome: "samples".into(),
            fetched_count: 1,
            accepted_count: 1,
            rejected_count: 0,
            overlap_count: 0,
            writer_acknowledged: 1,
            safe_code: "samples".into(),
        },
    }
}

#[tokio::test]
async fn exact_source_set_preserves_units_time_quality_and_restart() {
    assert_eq!(history_http_method(), "GET");
    assert!(!EXACT_FIXTURE.to_ascii_lowercase().contains("http"));
    let store = HourlyStore::memory();
    let devices = vec![point_map(&[(OA, "oa_t"), (SAT, "sat")])];
    let policy = quiet_policy();
    let now = at(10, 5, 0);
    let db = Arc::new(StdMutex::new(FixtureHistorian::default()));
    let mut fetch = catalog(at(9, 0, 0), exact_page());
    let mut writer = DbWriter {
        db: db.clone(),
        mode: WriteMode::Ok,
    };
    let report = run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(report.committed, 1);
    assert_eq!(report.failed, 0);
    assert_eq!(report.fetches, 1);
    assert_exact_set(&db.lock().unwrap());
    let jobs = store.list_jobs(SITE).await.unwrap();
    let hourly: Vec<_> = jobs.iter().filter(|job| job.purpose == "hourly").collect();
    assert_eq!(hourly.len(), 1);
    assert_eq!(hourly[0].state, JobState::Committed);
    assert_eq!(
        hourly[0].writer_acknowledged as usize,
        db.lock().unwrap().len()
    );
    let calls = fetch.calls.lock().unwrap().len();
    let again = run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(again.fetches, 0);
    assert_eq!(fetch.calls.lock().unwrap().len(), calls);
    assert_exact_set(&db.lock().unwrap());
    assert_eq!(
        store.checkpoint(&key_for(&devices[0])).await.unwrap(),
        Some(at(10, 0, 0))
    );
}

#[tokio::test]
async fn partial_history_keeps_present_rows_and_does_not_commit() {
    let store = HourlyStore::memory();
    let devices = vec![point_map(&[(OA, "oa_t"), (SAT, "sat")])];
    let policy = quiet_policy();
    let now = at(10, 5, 0);
    let page: Vec<_> = exact_page()
        .into_iter()
        .filter(|series| series.provider_point_id == OA)
        .collect();
    let db = Arc::new(StdMutex::new(FixtureHistorian::default()));
    let mut fetch = catalog(at(9, 0, 0), page);
    let mut writer = DbWriter {
        db: db.clone(),
        mode: WriteMode::Ok,
    };
    let report = run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert!(report.partial >= 1);
    assert_eq!(report.committed, 0);
    assert!(report.blocks_green());
    {
        let db = db.lock().unwrap();
        assert_eq!(db.len(), 4);
        assert!(db.rows.keys().all(|(point, _)| point == OA));
        assert!(db.rows.values().all(|row| row.role == "oa_t"));
    }
    let jobs = store.list_jobs(SITE).await.unwrap();
    assert!(jobs.iter().all(|job| job.state != JobState::Committed));
    assert!(jobs.iter().any(|job| job.state == JobState::Partial));
    assert_eq!(
        store.checkpoint(&key_for(&devices[0])).await.unwrap(),
        Some(at(9, 0, 0))
    );
}

#[tokio::test]
async fn crash_before_receipt_replays_without_duplicate_rows() {
    let store = HourlyStore::memory();
    let devices = vec![point_map(&[(OA, "oa_t"), (SAT, "sat")])];
    let policy = quiet_policy();
    let now = at(10, 5, 0);
    let db = Arc::new(StdMutex::new(FixtureHistorian::default()));
    let mut fetch = catalog(at(9, 0, 0), exact_page());
    let mut writer = DbWriter {
        db: db.clone(),
        mode: WriteMode::CrashAfterPersist { remaining: 1 },
    };
    let crashed = run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(crashed.committed, 0);
    assert_eq!(crashed.last_safe_code.as_deref(), Some("persistence"));
    assert!(!crashed
        .last_safe_code
        .as_deref()
        .unwrap()
        .contains("crash_before_receipt"));
    assert_exact_set(&db.lock().unwrap());
    let jobs = store.list_jobs(SITE).await.unwrap();
    assert!(jobs.iter().any(|job| job.state == JobState::RetryWait));
    assert_eq!(jobs[0].safe_error_code.as_deref(), Some("persistence"));
    let early = run_hourly_tick(
        &store,
        &tick(now + Duration::seconds(29), &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(early.fetches, 0);
    assert_exact_set(&db.lock().unwrap());
    let healed = run_hourly_tick(
        &store,
        &tick(now + Duration::seconds(30), &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(healed.committed, 1);
    assert_exact_set(&db.lock().unwrap());
    assert_eq!(
        store.checkpoint(&key_for(&devices[0])).await.unwrap(),
        Some(at(10, 0, 0))
    );
}

#[tokio::test]
async fn db_disconnect_retries_then_writes_the_exact_set() {
    let lost = anyhow::anyhow!("connection refused");
    assert!(historian_error_drops_connection(&lost));
    let constraint = anyhow::anyhow!("duplicate key value violates unique constraint");
    assert!(!historian_error_drops_connection(&constraint));
    let mut gate = TimescaleConnectGate::new();
    gate.insert("historian");
    gate.disconnect();
    assert!(!gate.is_connected());
    gate.insert("reconnected");
    assert!(gate.is_connected());

    let store = HourlyStore::memory();
    let devices = vec![point_map(&[(OA, "oa_t"), (SAT, "sat")])];
    let policy = quiet_policy();
    let now = at(10, 5, 0);
    let db = Arc::new(StdMutex::new(FixtureHistorian::default()));
    let mut fetch = catalog(at(9, 0, 0), exact_page());
    let mut writer = DbWriter {
        db: db.clone(),
        mode: WriteMode::Disconnect { remaining: 1 },
    };
    let dropped = run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(dropped.committed, 0);
    assert_eq!(dropped.last_safe_code.as_deref(), Some("persistence"));
    assert_eq!(db.lock().unwrap().len(), 0);
    let healed = run_hourly_tick(
        &store,
        &tick(now + Duration::seconds(30), &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(healed.committed, 1);
    assert_exact_set(&db.lock().unwrap());
}

#[tokio::test]
async fn throttled_429_backs_off_then_commits() {
    let store = HourlyStore::memory();
    let devices = vec![point_map(&[(OA, "oa_t"), (SAT, "sat")])];
    let policy = quiet_policy();
    let now = at(10, 5, 0);
    let db = Arc::new(StdMutex::new(FixtureHistorian::default()));
    let mut fetch = ThrottleThen {
        page: exact_page(),
        hits: StdMutex::new(0),
    };
    let mut writer = DbWriter {
        db: db.clone(),
        mode: WriteMode::Ok,
    };
    let blocked = run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(blocked.committed, 0);
    assert_eq!(blocked.last_safe_code.as_deref(), Some("throttled"));
    assert_eq!(*fetch.hits.lock().unwrap(), 1);
    assert_eq!(db.lock().unwrap().len(), 0);
    let jobs = store.list_jobs(SITE).await.unwrap();
    let wait = jobs
        .iter()
        .find(|job| job.state == JobState::RetryWait)
        .unwrap();
    assert!(wait.not_before.unwrap() >= now + Duration::seconds(45));
    let early = run_hourly_tick(
        &store,
        &tick(now + Duration::seconds(44), &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(early.fetches, 0);
    assert_eq!(*fetch.hits.lock().unwrap(), 1);
    let healed = run_hourly_tick(
        &store,
        &tick(now + Duration::seconds(45), &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(healed.committed, 1);
    assert_eq!(*fetch.hits.lock().unwrap(), 2);
    assert_exact_set(&db.lock().unwrap());
}

#[tokio::test]
async fn long_outage_catch_up_lands_every_sample_once() {
    let store = HourlyStore::memory();
    let devices = vec![point_map(&[(OA, "oa_t")])];
    let mut policy = quiet_policy();
    policy.max_claims_per_tick = 2;
    policy.retention = Duration::seconds(48 * 3600);
    let now = at(13, 5, 0);
    let key = key_for(&devices[0]);
    store.put_checkpoint(&key, at(1, 0, 0)).await.unwrap();
    let mut by_window = BTreeMap::new();
    for hour in 1..13 {
        let mut values = String::new();
        for (index, minute) in [0_u32, 20, 40].into_iter().enumerate() {
            if index > 0 {
                values.push(',');
            }
            let val = hour * 60 + minute;
            values.push_str(&format!(
                r#"{{"ts":"2026-10-18T{hour:02}:{minute:02}:00Z","double":{val}.0,"quality":"good"}}"#
            ));
        }
        let json = format!(
            r#"{{"data":[{{"uuid":"{OA}","name":"Mixed Air Temperature","units":"°F","values":[{values}]}}]}}"#
        );
        let points = parse_get_data_json(&json).unwrap();
        assert_eq!(points.len(), 3);
        by_window.insert(at(hour, 0, 0), group(points));
    }
    let db = Arc::new(StdMutex::new(FixtureHistorian::default()));
    let mut fetch = Catalog {
        by_window,
        calls: StdMutex::new(Vec::new()),
    };
    let mut writer = DbWriter {
        db: db.clone(),
        mode: WriteMode::Ok,
    };
    for _ in 0..16 {
        if store.checkpoint(&key).await.unwrap() == Some(at(13, 0, 0)) {
            break;
        }
        run_hourly_tick(
            &store,
            &tick(now, &devices, &policy, "worker-a"),
            &mut fetch,
            &mut writer,
        )
        .await
        .unwrap();
    }
    assert_eq!(store.checkpoint(&key).await.unwrap(), Some(at(13, 0, 0)));
    {
        let db_guard = db.lock().unwrap();
        assert_eq!(db_guard.len(), 36);
        for hour in 1..13 {
            for minute in [0_u32, 20, 40] {
                let snap = db_guard.get(OA, at(hour, minute, 0));
                let val = f64::from(hour * 60 + minute);
                assert_eq!(snap.val_bits, val.to_bits());
                assert_eq!(snap.unit.as_deref(), Some("°F"));
                assert_eq!(snap.quality.as_deref(), Some("good"));
                assert_eq!(snap.role, "oa_t");
                assert_ne!(snap.role, "mat");
            }
        }
    }
    let jobs = store.list_jobs(SITE).await.unwrap().len();
    assert_eq!(jobs, 12);
    run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(db.lock().unwrap().len(), 36);
    assert_eq!(store.list_jobs(SITE).await.unwrap().len(), jobs);
}

#[tokio::test]
async fn late_backload_adds_the_new_sample_only() {
    let store = HourlyStore::memory();
    let devices = vec![point_map(&[(OA, "oa_t")])];
    let mut policy = quiet_policy();
    policy.reconcile_hours = 0;
    let now = at(10, 5, 0);
    let early = parse_get_data_json(&format!(
        r#"{{"data":[{{"uuid":"{OA}","units":"°F","values":[
            {{"ts":"2026-10-18T09:10:00Z","double":1.0,"quality":"good"}},
            {{"ts":"2026-10-18T09:20:00Z","double":2.0,"quality":"good"}}
        ]}}]}}"#
    ))
    .unwrap();
    let db = Arc::new(StdMutex::new(FixtureHistorian::default()));
    let mut fetch = catalog(at(9, 0, 0), group(early));
    let mut writer = DbWriter {
        db: db.clone(),
        mode: WriteMode::Ok,
    };
    let first = run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(first.committed, 1);
    assert_eq!(db.lock().unwrap().len(), 2);
    let late = parse_get_data_json(&format!(
        r#"{{"data":[{{"uuid":"{OA}","units":"°F","values":[
            {{"ts":"2026-10-18T09:10:00Z","double":1.0,"quality":"good"}},
            {{"ts":"2026-10-18T09:20:00Z","double":2.0,"quality":"good"}},
            {{"ts":"2026-10-18T09:40:00Z","double":3.0,"quality":"uncertain"}}
        ]}}]}}"#
    ))
    .unwrap();
    fetch.by_window.insert(at(9, 0, 0), group(late));
    policy.reconcile_hours = 1;
    let second = run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert!(second.committed >= 1);
    let db = db.lock().unwrap();
    assert_eq!(db.len(), 3);
    assert_eq!(db.get(OA, at(9, 10, 0)).val_bits, 1.0_f64.to_bits());
    assert_eq!(db.get(OA, at(9, 20, 0)).val_bits, 2.0_f64.to_bits());
    let added = db.get(OA, at(9, 40, 0));
    assert_eq!(added.val_bits, 3.0_f64.to_bits());
    assert_eq!(added.quality.as_deref(), Some("uncertain"));
    assert_eq!(added.unit.as_deref(), Some("°F"));
}

#[tokio::test]
async fn stolen_lease_cannot_commit_a_second_copy() {
    let store = HourlyStore::memory();
    let devices = vec![point_map(&[(OA, "oa_t"), (SAT, "sat")])];
    let mut policy = quiet_policy();
    policy.lease = Duration::seconds(30);
    let now = at(10, 5, 0);
    let db = Arc::new(StdMutex::new(FixtureHistorian::default()));
    let mut fetch = catalog(at(9, 0, 0), exact_page());
    let mut writer = StealWriter {
        db: db.clone(),
        store: store.clone(),
        now,
        armed: true,
    };
    let stolen = run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(stolen.committed, 0);
    assert_eq!(stolen.last_safe_code.as_deref(), Some("stale_fence"));
    assert_exact_set(&db.lock().unwrap());
    let healed = run_hourly_tick(
        &store,
        &tick(now + Duration::seconds(60), &devices, &policy, "worker-b"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(healed.committed, 1);
    assert_exact_set(&db.lock().unwrap());
    let jobs = store.list_jobs(SITE).await.unwrap();
    assert_eq!(
        jobs.iter()
            .filter(|job| job.state == JobState::Committed)
            .count(),
        1
    );
}

#[tokio::test]
async fn two_to_four_workers_commit_each_job_once() {
    for workers in 2..=4 {
        let store = HourlyStore::memory();
        let base = at(0, 0, 0);
        let jobs_n = 8;
        for index in 0..jobs_n {
            let start = base + Duration::seconds(3600 * i64::try_from(index).unwrap());
            assert!(store
                .insert_job_if_absent(&job_draft(start, DEVICE))
                .await
                .unwrap());
        }
        let won_ids = Arc::new(StdMutex::new(BTreeSet::new()));
        let mut joins = Vec::new();
        for worker in 0..workers {
            let store = store.clone();
            let won_ids = won_ids.clone();
            joins.push(tokio::spawn(async move {
                let owner = format!("worker-{worker}");
                let mut won = 0usize;
                for _ in 0..40 {
                    let now = base + Duration::seconds(48 * 3600);
                    let claimed = store
                        .claim(SITE, now, 1, &owner, Duration::seconds(60))
                        .await
                        .unwrap();
                    let Some(job) = claimed.into_iter().next() else {
                        tokio::task::yield_now().await;
                        continue;
                    };
                    let stale = store
                        .commit(
                            &job.job_id,
                            job.fencing_token.saturating_sub(1),
                            &owner,
                            &receipt(&job.job_id, now, &format!("stale-{}", job.job_id)),
                        )
                        .await
                        .unwrap();
                    assert!(!stale);
                    let ok = store
                        .commit(
                            &job.job_id,
                            job.fencing_token,
                            &owner,
                            &receipt(&job.job_id, now, &format!("ok-{}", job.job_id)),
                        )
                        .await
                        .unwrap();
                    if ok {
                        won_ids.lock().unwrap().insert(job.job_id);
                        won += 1;
                    }
                }
                won
            }));
        }
        let mut total = 0usize;
        for join in joins {
            total += join.await.unwrap();
        }
        assert_eq!(total, jobs_n, "workers={workers}");
        assert_eq!(won_ids.lock().unwrap().len(), jobs_n);
        let jobs = store.list_jobs(SITE).await.unwrap();
        assert_eq!(jobs.len(), jobs_n);
        assert!(jobs.iter().all(|job| job.state == JobState::Committed));
        assert!(jobs.iter().all(|job| job.receipt_id.is_some()));
    }
}

#[tokio::test]
async fn each_extra_worker_rejects_an_expired_fence() {
    for workers in 2..=4 {
        let store = HourlyStore::memory();
        let now = at(12, 0, 0);
        store
            .insert_job_if_absent(&job_draft(at(9, 0, 0), DEVICE))
            .await
            .unwrap();
        let claimed = store
            .claim(SITE, now, 1, "worker-0", Duration::seconds(10))
            .await
            .unwrap();
        assert_eq!(claimed.len(), 1);
        let token = claimed[0].fencing_token;
        let expired = now + Duration::seconds(10);
        let reclaimed = store
            .claim(SITE, expired, 1, "worker-1", Duration::seconds(30))
            .await
            .unwrap();
        assert_eq!(reclaimed.len(), 1);
        assert_ne!(reclaimed[0].fencing_token, token);
        for worker in 0..workers {
            let owner = format!("worker-{worker}");
            let ok = store
                .commit(
                    &claimed[0].job_id,
                    token,
                    &owner,
                    &receipt(&claimed[0].job_id, expired, "expired"),
                )
                .await
                .unwrap();
            assert!(!ok, "{owner} kept a stale fence");
        }
        assert!(store
            .commit(
                &reclaimed[0].job_id,
                reclaimed[0].fencing_token,
                "worker-1",
                &receipt(&reclaimed[0].job_id, expired, "winner"),
            )
            .await
            .unwrap());
        for worker in 2..workers {
            let more = store
                .claim(
                    SITE,
                    expired,
                    1,
                    &format!("worker-{worker}"),
                    Duration::seconds(30),
                )
                .await
                .unwrap();
            assert!(more.is_empty());
        }
        let jobs = store.list_jobs(SITE).await.unwrap();
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0].state, JobState::Committed);
        assert_eq!(jobs[0].receipt_id.as_deref(), Some("winner"));
    }
}

#[tokio::test]
async fn oversized_page_is_rejected_and_replay_stays_bounded() {
    let mut body = format!(r#"{{"data":[{{"uuid":"{OA}","units":"°F","values":["#);
    let extra = MAX_SAMPLES_PER_RESPONSE + 1;
    for index in 0..extra {
        if index > 0 {
            body.push(',');
        }
        body.push_str(r#"{"ts":"2026-10-18T09:00:00Z","double":1.0,"quality":"good"}"#);
    }
    body.push_str("]}]}");
    let err = parse_get_data_json(&body).unwrap_err();
    assert_eq!(err.code, ProviderErrorCode::BodyTooLarge);
    assert!(!err.to_string().contains("CANARY"));

    let store = HourlyStore::memory();
    let devices = vec![point_map(&[(OA, "oa_t")])];
    let mut policy = quiet_policy();
    policy.bootstrap = Duration::seconds(4 * 3600);
    let now = at(13, 5, 0);
    let mut by_window = BTreeMap::new();
    for hour in 9..13 {
        let json = format!(
            r#"{{"data":[{{"uuid":"{OA}","units":"°F","values":[
                {{"ts":"2026-10-18T{hour:02}:00:00Z","double":1.0,"quality":"good"}},
                {{"ts":"2026-10-18T{hour:02}:20:00Z","double":2.0,"quality":"good"}},
                {{"ts":"2026-10-18T{hour:02}:40:00Z","double":3.0,"quality":"bad"}}
            ]}}]}}"#
        );
        by_window.insert(at(hour, 0, 0), group(parse_get_data_json(&json).unwrap()));
    }
    let db = Arc::new(StdMutex::new(FixtureHistorian::default()));
    let mut fetch = Catalog {
        by_window,
        calls: StdMutex::new(Vec::new()),
    };
    let mut writer = DbWriter {
        db: db.clone(),
        mode: WriteMode::Ok,
    };
    run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    let rows = db.lock().unwrap().len();
    let jobs = store.list_jobs(SITE).await.unwrap().len();
    assert_eq!(rows, 12);
    assert_eq!(jobs, 4);
    run_hourly_tick(
        &store,
        &tick(now, &devices, &policy, "worker-a"),
        &mut fetch,
        &mut writer,
    )
    .await
    .unwrap();
    assert_eq!(db.lock().unwrap().len(), rows);
    assert_eq!(store.list_jobs(SITE).await.unwrap().len(), jobs);
}
