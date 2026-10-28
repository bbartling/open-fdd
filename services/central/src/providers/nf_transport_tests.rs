//! REST and gRPC fixtures built in-process from one sample set. Both
//! transports must hand the writer identical normalized series.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use chrono::{DateTime, SecondsFormat, TimeZone, Utc};
use openfdd_nf_grpc::test_support::{FakePointManager, FakeReply};
use openfdd_nf_grpc::{BearerToken, HistorySeries as GrpcSeries, Limits, Sample, SampleScalar};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

use super::*;
use crate::providers::http_policy::HttpLimits;

const TOKEN: &str = "tok-grpc-fixture";
const SECRET: &str = "CANARY-CLIENT-SECRET";
const POINT_A: &str = "aaaaaaaa-0000-4000-8000-00000000000a";
const POINT_B: &str = "bbbbbbbb-0000-4000-8000-00000000000b";

fn at(minute: u32, nanos: u32) -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 1, 5, 10, minute, 0)
        .single()
        .unwrap()
        + chrono::Duration::nanoseconds(i64::from(nanos))
}

fn window() -> (DateTime<Utc>, DateTime<Utc>) {
    (at(0, 0), at(0, 0) + chrono::Duration::hours(1))
}

/// One sample set. Non-numeric kinds, a pre-1990 stamp, and an invalid uuid
/// must be dropped the same way by both transports.
fn fixture() -> Vec<GrpcSeries> {
    let old = Utc.with_ymd_and_hms(1980, 1, 1, 0, 0, 0).single().unwrap();
    vec![
        GrpcSeries {
            uuid: POINT_A.into(),
            samples: vec![
                Sample {
                    at: at(5, 0),
                    value: SampleScalar::Real(71.3),
                },
                Sample {
                    at: at(10, 123_456_789),
                    value: SampleScalar::Double(55.125),
                },
                Sample {
                    at: at(15, 0),
                    value: SampleScalar::Boolean(true),
                },
                Sample {
                    at: at(20, 0),
                    value: SampleScalar::Real(0.1),
                },
                Sample {
                    at: old,
                    value: SampleScalar::Double(1.0),
                },
            ],
        },
        GrpcSeries {
            uuid: POINT_B.into(),
            samples: vec![
                Sample {
                    at: at(5, 0),
                    value: SampleScalar::Signed(5),
                },
                Sample {
                    at: at(30, 500),
                    value: SampleScalar::Double(-12.5),
                },
                Sample {
                    at: at(45, 0),
                    value: SampleScalar::Text("on".into()),
                },
            ],
        },
        GrpcSeries {
            uuid: "bad id!".into(),
            samples: vec![Sample {
                at: at(5, 0),
                value: SampleScalar::Double(9.0),
            }],
        },
    ]
}

/// The portal JSON for the same GetData reply (proto3 JSON field names).
fn rest_body(series: &[GrpcSeries], requested: &[String]) -> String {
    let data: Vec<serde_json::Value> = series
        .iter()
        .filter(|one| requested.iter().any(|id| id == &one.uuid))
        .map(|one| {
            let values: Vec<serde_json::Value> = one
                .samples
                .iter()
                .map(|sample| {
                    let ts = sample.at.to_rfc3339_opts(SecondsFormat::AutoSi, true);
                    match &sample.value {
                        SampleScalar::Real(number) => {
                            let decimal: serde_json::Value =
                                serde_json::from_str(&number.to_string()).unwrap();
                            serde_json::json!({"ts": ts, "real": decimal})
                        }
                        SampleScalar::Double(number) => {
                            serde_json::json!({"ts": ts, "double": number})
                        }
                        SampleScalar::Boolean(bit) => serde_json::json!({"ts": ts, "boolean": bit}),
                        SampleScalar::Signed(number) => {
                            serde_json::json!({"ts": ts, "signed": number})
                        }
                        SampleScalar::Unsigned(number) => {
                            serde_json::json!({"ts": ts, "unsigned": number})
                        }
                        SampleScalar::Text(text) => {
                            serde_json::json!({"ts": ts, "characterString": text})
                        }
                        SampleScalar::Null | SampleScalar::OctetString(_) => {
                            serde_json::json!({"ts": ts, "null": "NULL_VALUE"})
                        }
                    }
                })
                .collect();
            serde_json::json!({"uuid": one.uuid, "values": values})
        })
        .collect();
    serde_json::json!({ "data": data }).to_string()
}

#[derive(Default)]
struct PortalLog {
    token_posts: usize,
    history_gets: usize,
    other: Vec<String>,
}

/// Portal fake: token issuance and `GET /api/v1/point/data`.
async fn spawn_portal(series: Vec<GrpcSeries>) -> (String, Arc<Mutex<PortalLog>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let log = Arc::new(Mutex::new(PortalLog::default()));
    let seen = Arc::clone(&log);
    tokio::spawn(async move {
        loop {
            let Ok((mut sock, _)) = listener.accept().await else {
                break;
            };
            let head = read_head(&mut sock).await;
            let line = head.lines().next().unwrap_or("").to_string();
            let body = if line.starts_with("POST /api/v1/auth/token ") {
                seen.lock().unwrap().token_posts += 1;
                format!(r#"{{"access_token":"{TOKEN}","expires_in":3600}}"#)
            } else if line.starts_with("GET /api/v1/point/data?") {
                seen.lock().unwrap().history_gets += 1;
                let requested: Vec<String> = line
                    .split(['?', '&', ' '])
                    .filter_map(|part| part.strip_prefix("uuids="))
                    .map(str::to_string)
                    .collect();
                rest_body(&series, &requested)
            } else {
                seen.lock().unwrap().other.push(line);
                "{}".to_string()
            };
            let reply = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = sock.write_all(reply.as_bytes()).await;
        }
    });
    (format!("http://127.0.0.1:{port}"), log)
}

async fn read_head(sock: &mut tokio::net::TcpStream) -> String {
    let mut buf = Vec::new();
    let mut tmp = [0u8; 4096];
    loop {
        let n = tokio::time::timeout(Duration::from_secs(2), sock.read(&mut tmp))
            .await
            .unwrap()
            .unwrap();
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&tmp[..n]);
        if let Some(pos) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
            let head = String::from_utf8_lossy(&buf[..pos]).to_string();
            let len = head
                .lines()
                .find_map(|line| {
                    let (name, value) = line.split_once(':')?;
                    name.eq_ignore_ascii_case("content-length")
                        .then(|| value.trim().parse::<usize>().ok())
                        .flatten()
                })
                .unwrap_or(0);
            while buf.len() < pos + 4 + len {
                let n = sock.read(&mut tmp).await.unwrap();
                if n == 0 {
                    break;
                }
                buf.extend_from_slice(&tmp[..n]);
            }
            return head;
        }
    }
    String::from_utf8_lossy(&buf).to_string()
}

fn driver(provider_id: &str, endpoint: &str) -> NfPortalDriver {
    NfPortalDriver::new(
        provider_id,
        endpoint,
        Some("fixture-client".into()),
        Some(SECRET.into()),
        false,
        HttpLimits::default(),
    )
    .unwrap()
}

async fn grpc_transport(
    provider_id: &str,
    endpoint: &str,
    fake: &FakePointManager,
    limits: Limits,
) -> NfTransport {
    let placeholder = BearerToken::new("placeholder-before-issue").unwrap();
    let client = fake.client(placeholder, limits).await.unwrap();
    NfTransport::with_grpc_client(driver(provider_id, endpoint), client)
}

fn ids() -> Vec<String> {
    vec![POINT_A.into(), POINT_B.into()]
}

#[tokio::test]
async fn rest_and_grpc_fixtures_produce_identical_samples() {
    let (endpoint, portal) = spawn_portal(fixture()).await;
    let fake = FakePointManager::spawn(FakeReply::Series(fixture()))
        .await
        .unwrap();
    let (from, to) = window();

    let mut rest = NfTransport::with_driver(
        driver("nf:parity-rest", &endpoint),
        SiteTransport::Rest,
        &endpoint,
    );
    assert_eq!(rest.transport(), SiteTransport::Rest);
    let via_rest = rest.read_history_page(&ids(), from, to).await.unwrap();

    let mut grpc = grpc_transport("nf:parity-grpc", &endpoint, &fake, Limits::default()).await;
    assert_eq!(grpc.transport(), SiteTransport::Grpc);
    let gets_before = portal.lock().unwrap().history_gets;
    let via_grpc = grpc.read_history_page(&ids(), from, to).await.unwrap();

    assert_eq!(via_rest, via_grpc);
    // Positive control: the fixture is not trivially empty.
    assert!(via_grpc.complete);
    assert_eq!(via_grpc.series.len(), 2);
    let a = &via_grpc.series[0];
    assert_eq!(a.provider_point_id, POINT_A);
    let vals: Vec<f64> = a.samples.iter().map(|s| s.val).collect();
    assert_eq!(vals, vec![71.3, 55.125, 0.1]);
    assert_eq!(a.samples[1].ts.timestamp_subsec_nanos(), 123_456_000);
    let b = &via_grpc.series[1];
    assert_eq!(b.samples.len(), 1);
    assert_eq!(b.samples[0].val, -12.5);
    assert_eq!(b.samples[0].ts.timestamp_subsec_nanos(), 0);

    // gRPC mode never touched the REST history read.
    let log = portal.lock().unwrap();
    assert_eq!(log.history_gets, gets_before);
    assert!(
        log.other.is_empty(),
        "unexpected portal calls: {:?}",
        log.other
    );
    drop(log);
    let seen = fake.seen();
    assert_eq!(seen.history_methods, vec![0]);
    assert_eq!(seen.history_from_seconds, vec![from.timestamp()]);
    assert_eq!(seen.history_to_seconds, vec![to.timestamp()]);
    assert!(seen
        .authorizations
        .iter()
        .all(|value| value == &format!("Bearer {TOKEN}")));
}

#[tokio::test]
async fn sample_drift_is_detected() {
    // Negative control for the parity assertion above.
    let (endpoint, _portal) = spawn_portal(fixture()).await;
    let mut drifted = fixture();
    drifted[0].samples[0].value = SampleScalar::Real(71.4);
    let fake = FakePointManager::spawn(FakeReply::Series(drifted))
        .await
        .unwrap();
    let (from, to) = window();
    let mut rest = NfTransport::with_driver(
        driver("nf:drift-rest", &endpoint),
        SiteTransport::Rest,
        &endpoint,
    );
    let mut grpc = grpc_transport("nf:drift-grpc", &endpoint, &fake, Limits::default()).await;
    let via_rest = rest.read_history_page(&ids(), from, to).await.unwrap();
    let via_grpc = grpc.read_history_page(&ids(), from, to).await.unwrap();
    assert_ne!(via_rest, via_grpc);
}

#[tokio::test]
async fn grpc_status_codes_map_to_precise_categories_without_fallback() {
    let (endpoint, portal) = spawn_portal(fixture()).await;
    let fake = FakePointManager::spawn(FakeReply::Series(fixture()))
        .await
        .unwrap();
    let (from, to) = window();
    let cases = [
        (16, "grpc_auth_failed", FetchError::Auth),
        (7, "grpc_forbidden", FetchError::Auth),
        (
            8,
            "grpc_throttled",
            FetchError::Throttled {
                retry_after_secs: None,
            },
        ),
        (4, "grpc_deadline_exceeded", FetchError::Transport),
        (14, "grpc_unavailable", FetchError::Transport),
        (12, "grpc_unimplemented", FetchError::NotImplemented),
        (13, "grpc_internal", FetchError::Transport),
        (3, "grpc_invalid_argument", FetchError::Contract),
        (5, "grpc_not_found", FetchError::Contract),
    ];
    for (index, (code, token, category)) in cases.into_iter().enumerate() {
        fake.set_reply(FakeReply::Status(code));
        let mut grpc = grpc_transport(
            &format!("nf:status-{index}"),
            &endpoint,
            &fake,
            Limits::default(),
        )
        .await;
        let err = grpc.read_history_page(&ids(), from, to).await.unwrap_err();
        assert_eq!(err.code(), token, "status {code}");
        assert_eq!(err.fetch_error(), category, "status {code}");
        assert!(!err.code().contains("fake status"));
    }
    assert_eq!(portal.lock().unwrap().history_gets, 0, "no REST fallback");
}

#[tokio::test]
async fn unauthenticated_reissues_the_token_once() {
    let (endpoint, portal) = spawn_portal(fixture()).await;
    let fake = FakePointManager::spawn(FakeReply::Series(fixture()))
        .await
        .unwrap();
    fake.queue_statuses(&[16]);
    let (from, to) = window();
    let mut grpc = grpc_transport("nf:reissue", &endpoint, &fake, Limits::default()).await;
    let page = grpc.read_history_page(&ids(), from, to).await.unwrap();
    assert_eq!(page.series.len(), 2);
    assert_eq!(fake.seen().history_batches.len(), 2);
    let log = portal.lock().unwrap();
    assert_eq!(log.token_posts, 2);
    assert_eq!(log.history_gets, 0);
}

#[tokio::test]
async fn grpc_deadline_is_enforced() {
    let (endpoint, portal) = spawn_portal(fixture()).await;
    let fake = FakePointManager::spawn(FakeReply::Stall(Duration::from_secs(3)))
        .await
        .unwrap();
    let limits = Limits::new(
        Duration::from_secs(1),
        Duration::from_millis(200),
        Limits::DEFAULT_MAX_RESPONSE_BYTES,
    )
    .unwrap();
    let (from, to) = window();
    let mut grpc = grpc_transport("nf:deadline", &endpoint, &fake, limits).await;
    let started = std::time::Instant::now();
    let err = grpc.read_history_page(&ids(), from, to).await.unwrap_err();
    assert!(started.elapsed() < Duration::from_secs(2));
    assert_eq!(err.code(), "grpc_deadline_exceeded");
    assert_eq!(portal.lock().unwrap().history_gets, 0);
}

#[tokio::test]
async fn grpc_reads_chunk_at_fifty_uuids_and_bounds_requests() {
    let (endpoint, _portal) = spawn_portal(fixture()).await;
    let fake = FakePointManager::spawn(FakeReply::Series(fixture()))
        .await
        .unwrap();
    let (from, to) = window();
    let mut grpc = grpc_transport("nf:chunks", &endpoint, &fake, Limits::default()).await;
    let many: Vec<String> = (0..60).map(|i| format!("pt-{i:04}")).collect();
    grpc.read_history_page(&many, from, to).await.unwrap();
    let sizes: Vec<usize> = fake.seen().history_batches.iter().map(Vec::len).collect();
    assert_eq!(sizes, vec![50, 10]);

    let calls = fake.seen().history_batches.len();
    let too_long = grpc
        .read_history_page(&ids(), from, from + chrono::Duration::hours(7))
        .await
        .unwrap_err();
    assert_eq!(too_long, HistoryFailure::Rest(FetchError::Contract));
    let bad_id = grpc
        .read_history_page(&["bad id".to_string()], from, to)
        .await
        .unwrap_err();
    assert_eq!(bad_id, HistoryFailure::Rest(FetchError::Contract));
    assert_eq!(
        fake.seen().history_batches.len(),
        calls,
        "rejected before the wire"
    );
    assert!(grpc
        .read_history_page(&[], from, to)
        .await
        .unwrap()
        .series
        .is_empty());
}

#[tokio::test]
async fn production_grpc_connect_requires_tls_endpoint() {
    let (endpoint, portal) = spawn_portal(fixture()).await;
    // Plain http endpoint: the real connect path refuses before any RPC.
    let mut grpc =
        NfTransport::with_driver(driver("nf:tls", &endpoint), SiteTransport::Grpc, &endpoint);
    let (from, to) = window();
    let err = grpc.read_history_page(&ids(), from, to).await.unwrap_err();
    assert_eq!(err.code(), "grpc_tls_required");
    assert_eq!(portal.lock().unwrap().history_gets, 0);
}

#[test]
fn real_values_use_the_json_decimal_and_reject_non_finite() {
    assert_eq!(real_as_json_decimal(71.3).unwrap(), 71.3);
    assert_eq!(real_as_json_decimal(0.1).unwrap(), 0.1);
    assert_eq!(real_as_json_decimal(f32::NAN), Err(NfGrpcError::Contract));
    let page = HistoryPage {
        series: vec![GrpcSeries {
            uuid: POINT_A.into(),
            samples: vec![Sample {
                at: at(1, 0),
                value: SampleScalar::Double(f64::INFINITY),
            }],
        }],
    };
    assert_eq!(raw_points_from_grpc(page), Err(NfGrpcError::Contract));
}

#[test]
fn debug_output_redacts_credentials() {
    let transport = NfTransport::with_driver(
        driver("nf:debug", "https://portal.example"),
        SiteTransport::Grpc,
        "https://portal.example",
    );
    let text = format!("{transport:?}");
    assert!(text.contains("Grpc"));
    assert!(!text.contains(SECRET));
    assert!(!text.contains(TOKEN));
}
