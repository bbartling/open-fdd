//! W2d / #1423 driver acceptance: T1423-1 paging, T1423-2 throttle retry.

use std::collections::{HashMap, HashSet};

use chrono::{DateTime, TimeZone, Utc};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

use super::driver_limits::HistoryDriverLimits;
use super::hourly::{classify_history_status, FetchError};
use super::http_policy::{
    HttpLimits, MAX_HISTORY_WINDOW, MAX_SAMPLES_PER_RESPONSE, MAX_UUIDS_PER_REQUEST,
};
use super::map::RawProviderPoint;
use super::nf::{
    build_history_read_url, merge_history_samples, next_history_page_start_for_point,
    NfPortalDriver, PagedHistoryPoints,
};
use super::Runtime;

const UUID_A: &str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
const UUID_B: &str = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff";

async fn read_http_request(sock: &mut tokio::net::TcpStream) -> String {
    let mut buf = vec![0_u8; 8192];
    let n = sock.read(&mut buf).await.unwrap_or(0);
    String::from_utf8_lossy(&buf[..n]).into_owned()
}

fn paging_test_limits(sample_cap: usize, max_pages: usize) -> HistoryDriverLimits {
    HistoryDriverLimits {
        max_history_span: MAX_HISTORY_WINDOW,
        max_points_per_request: MAX_UUIDS_PER_REQUEST,
        max_points_total: 4,
        max_samples_per_response: sample_cap,
        max_history_pages: max_pages,
        supports_paging: true,
    }
}

fn sample_series_for(
    point_id: &str,
    count: usize,
    start: chrono::DateTime<Utc>,
) -> Vec<RawProviderPoint> {
    (0..count)
        .map(|index| RawProviderPoint {
            provider_point_id: point_id.to_string(),
            display_name: None,
            ts: start + chrono::Duration::minutes(i64::try_from(index).unwrap_or(i64::MAX)),
            val: f64::from(u32::try_from(index).unwrap_or(u32::MAX)),
            unit: Some("degF".into()),
            source_quality: None,
            attrs: serde_json::Map::new(),
        })
        .collect()
}

fn history_json_for(point_id: &str, samples: &[RawProviderPoint]) -> String {
    let values: Vec<serde_json::Value> = samples
        .iter()
        .map(|row| {
            serde_json::json!({
                "double": row.val,
                "ts": row.ts.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
                "quality": "good"
            })
        })
        .collect();
    serde_json::json!({
        "data": [{
            "uuid": point_id,
            "values": values
        }]
    })
    .to_string()
}

fn parse_history_from_seconds(req: &str) -> Option<i64> {
    let line = req.lines().next()?;
    let query = line.split('?').nth(1)?;
    for part in query.split('&') {
        if let Some(raw) = part.strip_prefix("from.seconds=") {
            return raw.parse().ok();
        }
    }
    None
}

fn parse_history_to_seconds(req: &str) -> Option<i64> {
    let line = req.lines().next()?;
    let query = line.split('?').nth(1)?;
    for part in query.split('&') {
        if let Some(raw) = part.strip_prefix("to.seconds=") {
            return raw.parse().ok();
        }
    }
    None
}

fn history_uuids(req: &str) -> Vec<String> {
    let line = req.lines().next().unwrap_or("");
    let query = line.split('?').nth(1).unwrap_or("");
    query
        .split('&')
        .filter_map(|part| part.strip_prefix("uuids=").map(str::to_string))
        .collect()
}

fn respond_json(status: &str, body: &str) -> String {
    format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
}

#[tokio::test]
async fn t1423_1_nf_fixture_pages_at_sample_cap_without_loss_or_duplicates() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let window_start = Utc.with_ymd_and_hms(2026, 10, 20, 8, 0, 0).unwrap();
    let window_end = window_start + chrono::Duration::hours(2);
    let all = sample_series_for(UUID_A, 11, window_start);
    let cap = 5_usize;
    let limits = paging_test_limits(cap, 512);
    let expected_len = all.len();
    let all_server = all.clone();
    let history_calls = std::sync::Arc::new(tokio::sync::Mutex::new(0_usize));
    let calls_task = std::sync::Arc::clone(&history_calls);
    tokio::spawn(async move {
        loop {
            let Ok((mut sock, _)) = listener.accept().await else {
                break;
            };
            let req = read_http_request(&mut sock).await;
            if req.starts_with("GET /api/v1/point/data") {
                let mut calls = calls_task.lock().await;
                *calls += 1;
                let from =
                    DateTime::from_timestamp(parse_history_from_seconds(&req).unwrap_or(0), 0)
                        .unwrap_or(window_start);
                let to = DateTime::from_timestamp(parse_history_to_seconds(&req).unwrap_or(0), 0)
                    .unwrap_or(window_end);
                let point_id = history_uuids(&req)
                    .into_iter()
                    .next()
                    .unwrap_or_else(|| UUID_A.to_string());
                let mut page: Vec<_> = all_server
                    .iter()
                    .filter(|row| {
                        row.provider_point_id == point_id && row.ts >= from && row.ts <= to
                    })
                    .cloned()
                    .collect();
                if page.len() > cap {
                    page.truncate(cap);
                }
                let payload = respond_json("200 OK", &history_json_for(&point_id, &page));
                let _ = sock.write_all(payload.as_bytes()).await;
            } else {
                let payload = respond_json("404 Not Found", r#"{"error":"unexpected"}"#);
                let _ = sock.write_all(payload.as_bytes()).await;
            }
        }
    });
    let mut driver = NfPortalDriver::new(
        "nf:t1423",
        format!("http://127.0.0.1:{port}"),
        None,
        None,
        true,
        HttpLimits::default(),
    )
    .unwrap();
    let fetched = driver
        .fetch_history_chunk_paged(&[UUID_A.to_string()], window_start, window_end, &limits)
        .await
        .unwrap();
    assert!(fetched.complete);
    assert_eq!(fetched.points.len(), expected_len);
    let keys: HashSet<_> = fetched
        .points
        .iter()
        .map(|row| (row.provider_point_id.as_str(), row.ts))
        .collect();
    assert_eq!(keys.len(), expected_len);
    for expected in &all {
        assert!(keys.contains(&(expected.provider_point_id.as_str(), expected.ts)));
    }
    let call_count = *history_calls.lock().await;
    assert_eq!(
        call_count, 3,
        "expected three paged GETs for 11 samples at cap 5"
    );
    let url = build_history_read_url(
        &format!("http://127.0.0.1:{port}"),
        &[UUID_A.to_string()],
        window_start,
        window_end,
    );
    assert!(url.contains("from.seconds="));
}

#[tokio::test]
async fn t1423_1_two_points_cap_truncates_without_cross_point_loss() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let window_start = Utc.with_ymd_and_hms(2026, 10, 20, 11, 0, 0).unwrap();
    let window_end = window_start + chrono::Duration::hours(2);
    let cap = 5_usize;
    let limits = paging_test_limits(cap, 512);
    let catalog: HashMap<String, Vec<RawProviderPoint>> = [
        (
            UUID_A.to_string(),
            sample_series_for(UUID_A, 3, window_start),
        ),
        (
            UUID_B.to_string(),
            sample_series_for(UUID_B, 8, window_start),
        ),
    ]
    .into_iter()
    .collect();
    let catalog_task = catalog.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut sock, _)) = listener.accept().await else {
                break;
            };
            let req = read_http_request(&mut sock).await;
            if !req.starts_with("GET /api/v1/point/data") {
                continue;
            }
            let from = DateTime::from_timestamp(parse_history_from_seconds(&req).unwrap_or(0), 0)
                .unwrap_or(window_start);
            let to = DateTime::from_timestamp(parse_history_to_seconds(&req).unwrap_or(0), 0)
                .unwrap_or(window_end);
            let point_id = history_uuids(&req)
                .into_iter()
                .next()
                .unwrap_or_else(|| UUID_A.to_string());
            let mut page: Vec<_> = catalog_task
                .get(&point_id)
                .into_iter()
                .flat_map(|rows| rows.iter())
                .filter(|row| row.ts >= from && row.ts <= to)
                .cloned()
                .collect();
            if page.len() > cap {
                page.truncate(cap);
            }
            let payload = respond_json("200 OK", &history_json_for(&point_id, &page));
            let _ = sock.write_all(payload.as_bytes()).await;
        }
    });
    let mut driver = NfPortalDriver::new(
        "nf:t1423-two-point",
        format!("http://127.0.0.1:{port}"),
        None,
        None,
        true,
        HttpLimits::default(),
    )
    .unwrap();
    let fetched = driver
        .fetch_history_chunk_paged(
            &[UUID_A.to_string(), UUID_B.to_string()],
            window_start,
            window_end,
            &limits,
        )
        .await
        .unwrap();
    assert!(fetched.complete);
    assert_eq!(fetched.points.len(), 11);
    let keys: HashSet<_> = fetched
        .points
        .iter()
        .map(|row| (row.provider_point_id.as_str(), row.ts))
        .collect();
    assert_eq!(keys.len(), 11);
    assert_eq!(
        fetched
            .points
            .iter()
            .filter(|row| row.provider_point_id == UUID_A)
            .count(),
        3
    );
    assert_eq!(
        fetched
            .points
            .iter()
            .filter(|row| row.provider_point_id == UUID_B)
            .count(),
        8
    );
}

#[tokio::test]
async fn t1423_1_max_pages_reports_incomplete_without_error() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let window_start = Utc.with_ymd_and_hms(2026, 10, 20, 12, 0, 0).unwrap();
    let window_end = window_start + chrono::Duration::hours(2);
    let all = sample_series_for(UUID_A, 11, window_start);
    let cap = 5_usize;
    let limits = paging_test_limits(cap, 2);
    let all_server = all.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut sock, _)) = listener.accept().await else {
                break;
            };
            let req = read_http_request(&mut sock).await;
            if !req.starts_with("GET /api/v1/point/data") {
                continue;
            }
            let from = DateTime::from_timestamp(parse_history_from_seconds(&req).unwrap_or(0), 0)
                .unwrap_or(window_start);
            let to = DateTime::from_timestamp(parse_history_to_seconds(&req).unwrap_or(0), 0)
                .unwrap_or(window_end);
            let mut page: Vec<_> = all_server
                .iter()
                .filter(|row| row.ts >= from && row.ts <= to)
                .cloned()
                .collect();
            if page.len() > cap {
                page.truncate(cap);
            }
            let payload = respond_json("200 OK", &history_json_for(UUID_A, &page));
            let _ = sock.write_all(payload.as_bytes()).await;
        }
    });
    let mut driver = NfPortalDriver::new(
        "nf:t1423-incomplete",
        format!("http://127.0.0.1:{port}"),
        None,
        None,
        true,
        HttpLimits::default(),
    )
    .unwrap();
    let PagedHistoryPoints { points, complete } = driver
        .fetch_history_chunk_paged(&[UUID_A.to_string()], window_start, window_end, &limits)
        .await
        .unwrap();
    assert!(!complete);
    assert_eq!(points.len(), 10);
}

#[test]
fn t1423_incomplete_driver_page_blocks_window_commit() {
    use crate::ingest_queue::coverage::{
        reconcile, Expectation, PointExpectation, PointObservation, ReconcileInput, INCOMPLETE,
    };

    let start = Utc.with_ymd_and_hms(2026, 10, 20, 13, 0, 0).unwrap();
    let end = start + chrono::Duration::minutes(15);
    let report = reconcile(&ReconcileInput {
        start,
        end,
        expectations: &[PointExpectation {
            point_id: UUID_A.into(),
            expectation: Expectation::Interval { cadence_secs: 300 },
        }],
        observations: &[PointObservation {
            point_id: UUID_A.into(),
            returned: true,
            timestamps: vec![start],
        }],
        prior: &[],
        response_complete: false,
    })
    .expect("reconcile");
    assert_eq!(report.summary, INCOMPLETE);
    assert!(!report.allows_commit());
}

#[test]
fn t1423_1_merge_and_cursor_helpers_match_driver_paging() {
    let start = Utc.with_ymd_and_hms(2026, 10, 20, 9, 0, 0).unwrap();
    let end = start + chrono::Duration::hours(1);
    let all = sample_series_for(UUID_A, 7, start);
    let cap = 3_usize;
    let mut out = Vec::new();
    let mut seen = HashSet::new();
    let mut cursor = start;
    let mut guard = 0;
    while guard < 16 {
        guard += 1;
        let page_end = cursor + chrono::Duration::minutes(30);
        let slice_end = page_end.min(end);
        let page: Vec<_> = all
            .iter()
            .filter(|row| row.ts >= cursor && row.ts <= slice_end)
            .take(cap)
            .cloned()
            .collect();
        let capped = page.len() >= cap;
        merge_history_samples(&mut out, page, &mut seen);
        if !capped {
            break;
        }
        cursor = next_history_page_start_for_point(&out, UUID_A, cursor, end).expect("cursor");
    }
    assert_eq!(out.len(), all.len());
}

#[tokio::test]
async fn t1423_2_portal_429_retry_after_never_permanent_failure() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let from = Utc.with_ymd_and_hms(2026, 10, 20, 10, 0, 0).unwrap();
    let to = from + chrono::Duration::hours(1);
    let throttled_once = std::sync::Arc::new(tokio::sync::Mutex::new(true));
    let flag = std::sync::Arc::clone(&throttled_once);
    tokio::spawn(async move {
        loop {
            let Ok((mut sock, _)) = listener.accept().await else {
                break;
            };
            let req = read_http_request(&mut sock).await;
            if !req.starts_with("GET /api/v1/point/data") {
                let _ = sock
                    .write_all(
                        respond_json("404 Not Found", r#"{"error":"unexpected"}"#).as_bytes(),
                    )
                    .await;
                continue;
            }
            let mut once = flag.lock().await;
            if *once {
                *once = false;
                let payload = "HTTP/1.1 429 Too Many Requests\r\nRetry-After: 4\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}";
                let _ = sock.write_all(payload.as_bytes()).await;
            } else {
                let body = history_json_for(UUID_A, &[]);
                let _ = sock
                    .write_all(respond_json("200 OK", &body).as_bytes())
                    .await;
            }
        }
    });
    let mut driver = NfPortalDriver::new(
        "nf:t1423-throttle",
        format!("http://127.0.0.1:{port}"),
        None,
        None,
        true,
        HttpLimits::default(),
    )
    .unwrap();
    let err = driver
        .read_history_page(&[UUID_A.to_string()], from, to)
        .await
        .unwrap_err();
    assert_eq!(
        err,
        FetchError::Throttled {
            retry_after_secs: Some(4)
        }
    );
    assert_eq!(err.ingest_queue_label(), "throttled:4");
    assert_eq!(
        classify_history_status(429, Some(4)),
        FetchError::Throttled {
            retry_after_secs: Some(4)
        }
    );

    let runtime = Runtime::health_only_for_test("building-t1423");
    runtime.record_portal_throttle("building-t1423").await;
    runtime.record_portal_throttle("building-t1423").await;
    let guard = runtime.health.lock().await;
    let site = guard
        .sites
        .iter()
        .find(|row| row.building_id == "building-t1423")
        .expect("site row");
    assert_eq!(site.portal_throttle_count, 2);
    assert!(site.portal_throttled_since.is_some());
}

#[test]
fn t1423_driver_limits_advertise_nf_portal_capability() {
    let limits = HistoryDriverLimits::nf_portal();
    assert_eq!(limits.max_history_span, MAX_HISTORY_WINDOW);
    assert_eq!(limits.max_points_per_request, MAX_UUIDS_PER_REQUEST);
    assert_eq!(limits.max_samples_per_response, MAX_SAMPLES_PER_RESPONSE);
    assert_eq!(limits.max_history_pages, 512);
    assert!(limits.supports_paging);
}
