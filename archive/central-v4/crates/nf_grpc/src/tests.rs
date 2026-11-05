//! In-process PointManager: inventory, history, and status-code mapping.

use std::sync::Mutex;
use std::time::Duration;

use chrono::DateTime;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::transport::{Endpoint, Server};
use tonic::{Code, Request, Response, Status};

use super::proto::point_manager_server::{PointManager, PointManagerServer};
use super::proto::value::ValueType;
use super::proto::{
    DataVector, GetDataReply, GetDataRequest, GetPointsByIdRequest, GetPointsReply,
    GetPointsRequest, Point, Value,
};
use super::{
    BearerToken, HistoryWindow, InventoryQuery, Limits, NfGrpcError, NfReadClient, SampleScalar,
    CONTRACT_COMMIT,
};

const CANARY: &str = "CANARY-VENDOR-BODY";
const POINT_ID: &str = "11111111-1111-4111-8111-111111111111";
const TOKEN: &str = "unit-token";

#[derive(Clone)]
enum Script {
    Points,
    History,
    Status(Code),
    Huge,
    MissingTimestamp,
}

struct Seen {
    authorization: String,
    grpc_timeout: String,
    include_archived: bool,
    history_method: i32,
    history_count: i32,
    history_from: Option<prost_types::Timestamp>,
    history_uuids: Vec<String>,
}

impl Seen {
    fn empty() -> Self {
        Self {
            authorization: String::new(),
            grpc_timeout: String::new(),
            include_archived: false,
            history_method: -1,
            history_count: -1,
            history_from: None,
            history_uuids: Vec::new(),
        }
    }
}

struct Fake {
    script: Mutex<Script>,
    seen: Mutex<Seen>,
}

/// Server-owned handle. The test keeps the same `Fake` behind `Arc`.
struct FakeHandle(std::sync::Arc<Fake>);

impl Fake {
    fn new(script: Script) -> Self {
        Self {
            script: Mutex::new(script),
            seen: Mutex::new(Seen::empty()),
        }
    }

    fn script(&self) -> Script {
        self.script
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    fn record(&self, authorization: Option<&str>, timeout: Option<&str>) {
        let mut seen = self
            .seen
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(value) = authorization {
            seen.authorization = value.to_string();
        }
        if let Some(value) = timeout {
            seen.grpc_timeout = value.to_string();
        }
    }

    fn note_inventory(&self, include_archived: bool) {
        self.seen
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .include_archived = include_archived;
    }

    fn note_history(&self, request: &GetDataRequest) {
        let mut seen = self
            .seen
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        seen.history_method = request.method;
        seen.history_count = request.count;
        seen.history_from = request.from;
        seen.history_uuids = request.uuids.clone();
    }
}

fn meta<'a, T>(request: &'a Request<T>, name: &str) -> Option<&'a str> {
    request
        .metadata()
        .get(name)
        .and_then(|value| value.to_str().ok())
}

fn sample_point() -> Point {
    let mut point = Point {
        uuid: POINT_ID.to_string(),
        name: "zone-temp".to_string(),
        layer: "hpl:example:1".to_string(),
        description: "zone air".to_string(),
        display_units: "degF".to_string(),
        units: 64,
        point_type: 1,
        latest_value: Some(Value {
            ts: Some(stamp(1_700_000_000, 0)),
            value_type: Some(ValueType::Real(70.5)),
            ..Value::default()
        }),
        ..Point::default()
    };
    point
        .attrs
        .insert("role".to_string(), "zone-air-temp".to_string());
    point
}

fn stamp(seconds: i64, nanos: i32) -> prost_types::Timestamp {
    prost_types::Timestamp { seconds, nanos }
}

fn status_of(script: &Script) -> Option<Status> {
    match script {
        Script::Status(code) => Some(Status::new(*code, CANARY)),
        _ => None,
    }
}

#[tonic::async_trait]
impl PointManager for FakeHandle {
    async fn get_points(
        &self,
        request: Request<GetPointsRequest>,
    ) -> Result<Response<GetPointsReply>, Status> {
        self.0.record(
            meta(&request, "authorization"),
            meta(&request, "grpc-timeout"),
        );
        let inner = request.into_inner();
        self.0.note_inventory(inner.include_archived);
        if let Some(status) = status_of(&self.0.script()) {
            return Err(status);
        }
        let point = match self.0.script() {
            Script::Huge => {
                let mut point = sample_point();
                point
                    .attrs
                    .insert("blob".to_string(), "x".repeat(64 * 1024));
                point
            }
            Script::MissingTimestamp => Point {
                uuid: POINT_ID.to_string(),
                latest_value: Some(Value {
                    value_type: Some(ValueType::Real(1.0)),
                    ..Value::default()
                }),
                ..Point::default()
            },
            _ => sample_point(),
        };
        Ok(Response::new(GetPointsReply {
            total_count: 1,
            points: vec![point],
        }))
    }

    async fn get_points_by_id(
        &self,
        request: Request<GetPointsByIdRequest>,
    ) -> Result<Response<GetPointsReply>, Status> {
        self.0.record(
            meta(&request, "authorization"),
            meta(&request, "grpc-timeout"),
        );
        if let Some(status) = status_of(&self.0.script()) {
            return Err(status);
        }
        let uuids = request.into_inner().uuids;
        let mut points = Vec::new();
        if uuids.iter().any(|id| id == POINT_ID) {
            points.push(sample_point());
        }
        let total_count = i64::try_from(points.len()).unwrap_or(0);
        Ok(Response::new(GetPointsReply {
            points,
            total_count,
        }))
    }

    async fn get_data(
        &self,
        request: Request<GetDataRequest>,
    ) -> Result<Response<GetDataReply>, Status> {
        self.0.record(
            meta(&request, "authorization"),
            meta(&request, "grpc-timeout"),
        );
        let inner = request.into_inner();
        self.0.note_history(&inner);
        if let Some(status) = status_of(&self.0.script()) {
            return Err(status);
        }
        Ok(Response::new(GetDataReply {
            data: vec![DataVector {
                uuid: POINT_ID.to_string(),
                values: vec![Value {
                    ts: Some(stamp(1_700_000_100, 250_000_000)),
                    value_type: Some(ValueType::Real(71.25)),
                    ..Value::default()
                }],
            }],
        }))
    }

    type ObservePointsUpdatesStream =
        tokio_stream::Once<Result<super::proto::ObservePointsUpdatesReply, Status>>;
    type ObserveDataUpdatesStream =
        tokio_stream::Once<Result<super::proto::ObserveDataUpdatesReply, Status>>;
    type ObserveErrorUpdatesStream =
        tokio_stream::Once<Result<super::proto::ObserveErrorUpdatesReply, Status>>;

    async fn observe_points_updates(
        &self,
        _request: Request<super::proto::ObservePointsUpdatesRequest>,
    ) -> Result<Response<Self::ObservePointsUpdatesStream>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }

    async fn observe_data_updates(
        &self,
        _request: Request<super::proto::ObserveDataUpdatesRequest>,
    ) -> Result<Response<Self::ObserveDataUpdatesStream>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }

    async fn observe_error_updates(
        &self,
        _request: Request<super::proto::ObserveErrorUpdatesRequest>,
    ) -> Result<Response<Self::ObserveErrorUpdatesStream>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }

    async fn get_layers(
        &self,
        _: Request<super::proto::GetLayersRequest>,
    ) -> Result<Response<super::proto::GetLayersReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_layer(
        &self,
        _: Request<super::proto::CreateLayerRequest>,
    ) -> Result<Response<super::proto::CreateLayerReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn update_layer(
        &self,
        _: Request<super::proto::UpdateLayerRequest>,
    ) -> Result<Response<super::proto::UpdateLayerReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_layer(
        &self,
        _: Request<super::proto::DeleteLayerRequest>,
    ) -> Result<Response<super::proto::DeleteLayerReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_distinct_attrs(
        &self,
        _: Request<super::proto::GetDistinctAttrsRequest>,
    ) -> Result<Response<super::proto::GetDistinctAttrsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_distinct_attr_keys(
        &self,
        _: Request<super::proto::GetDistinctAttrsRequest>,
    ) -> Result<Response<super::proto::GetDistinctAttrsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn add_points_data(
        &self,
        _: Request<super::proto::AddPointsDataRequest>,
    ) -> Result<Response<super::proto::AddPointsDataReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn add_data(
        &self,
        _: Request<super::proto::AddDataRequest>,
    ) -> Result<Response<super::proto::AddDataReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_data_summary(
        &self,
        _: Request<super::proto::GetDataSummaryRequest>,
    ) -> Result<Response<super::proto::GetDataSummaryReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn update_points(
        &self,
        _: Request<super::proto::UpdatePointsRequest>,
    ) -> Result<Response<super::proto::UpdatePointsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn rename_point(
        &self,
        _: Request<super::proto::RenamePointRequest>,
    ) -> Result<Response<super::proto::RenamePointReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn copy_attributes(
        &self,
        _: Request<super::proto::CopyAttributesRequest>,
    ) -> Result<Response<super::proto::CopyAttributesReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_points(
        &self,
        _: Request<super::proto::DeletePointsRequest>,
    ) -> Result<Response<super::proto::DeletePointsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn add_tags(
        &self,
        _: Request<super::proto::AddTagsRequest>,
    ) -> Result<Response<super::proto::AddTagsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_tags(
        &self,
        _: Request<super::proto::DeleteTagsRequest>,
    ) -> Result<Response<super::proto::DeleteTagsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_config_keys(
        &self,
        _: Request<super::proto::GetConfigKeysRequest>,
    ) -> Result<Response<super::proto::GetConfigKeysReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn set_config_key(
        &self,
        _: Request<super::proto::SetConfigKeyRequest>,
    ) -> Result<Response<super::proto::SetConfigKeyReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_config_keys(
        &self,
        _: Request<super::proto::DeleteConfigKeysRequest>,
    ) -> Result<Response<super::proto::DeleteConfigKeysReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_export(
        &self,
        _: Request<super::proto::CreateExportRequest>,
    ) -> Result<Response<super::proto::CreateExportReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_data_export(
        &self,
        _: Request<super::proto::CreateDataExportRequest>,
    ) -> Result<Response<super::proto::CreateDataExportReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_versions(
        &self,
        _: Request<super::proto::GetVersionsRequest>,
    ) -> Result<Response<super::proto::GetVersionsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn aggregate_points(
        &self,
        _: Request<super::proto::AggregatePointsRequest>,
    ) -> Result<Response<super::proto::AggregatePointsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_point_errors(
        &self,
        _: Request<super::proto::GetPointErrorsRequest>,
    ) -> Result<Response<super::proto::GetPointErrorsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_conversion(
        &self,
        _: Request<super::proto::CreateConversionRequest>,
    ) -> Result<Response<super::proto::CreateConversionReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_conversions(
        &self,
        _: Request<super::proto::GetConversionsRequest>,
    ) -> Result<Response<super::proto::GetConversionsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn update_conversion(
        &self,
        _: Request<super::proto::UpdateConversionRequest>,
    ) -> Result<Response<super::proto::UpdateConversionReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_conversion(
        &self,
        _: Request<super::proto::DeleteConversionRequest>,
    ) -> Result<Response<super::proto::DeleteConversionReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_quality_rule(
        &self,
        _: Request<super::proto::CreateQualityRuleRequest>,
    ) -> Result<Response<super::proto::CreateQualityRuleReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_quality_rules(
        &self,
        _: Request<super::proto::GetQualityRulesRequest>,
    ) -> Result<Response<super::proto::GetQualityRulesReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn update_quality_rule(
        &self,
        _: Request<super::proto::UpdateQualityRuleRequest>,
    ) -> Result<Response<super::proto::UpdateQualityRuleReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_quality_rule(
        &self,
        _: Request<super::proto::DeleteQualityRuleRequest>,
    ) -> Result<Response<super::proto::DeleteQualityRuleReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn backtest_quality_rule(
        &self,
        _: Request<super::proto::BacktestQualityRuleRequest>,
    ) -> Result<Response<super::proto::BacktestQualityRuleReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
}

async fn connect_fake(fake: Fake) -> (NfReadClient, std::sync::Arc<Fake>) {
    let shared = std::sync::Arc::new(fake);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let incoming = TcpListenerStream::new(listener);
    let service = PointManagerServer::new(FakeHandle(std::sync::Arc::clone(&shared)));
    tokio::spawn(async move {
        Server::builder()
            .add_service(service)
            .serve_with_incoming(incoming)
            .await
            .unwrap();
    });
    let endpoint = Endpoint::from_shared(format!("http://{addr}")).unwrap();
    let mut last = None;
    for _ in 0..20 {
        match endpoint.connect().await {
            Ok(channel) => {
                let bearer = BearerToken::new(TOKEN).unwrap();
                let client = NfReadClient::from_channel(channel, bearer, Limits::default());
                return (client, shared);
            }
            Err(err) => {
                last = Some(err);
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        }
    }
    panic!("fake server did not accept: {last:?}");
}

fn set_script(fake: &Fake, script: Script) {
    *fake
        .script
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner) = script;
}

#[tokio::test]
async fn inventory_and_history_round_trip() {
    let (mut client, fake) = connect_fake(Fake::new(Script::Points)).await;
    let query = InventoryQuery::new("hpl:example:1", 25, 0)
        .unwrap()
        .include_archived(true);
    let page = client.list_points(&query).await.unwrap();
    assert_eq!(page.total_count, 1);
    let point = &page.points[0];
    assert_eq!(point.uuid, POINT_ID);
    assert_eq!(
        point.attrs.get("role").map(String::as_str),
        Some("zone-air-temp")
    );
    assert_eq!(point.units, 64);
    match point.latest.as_ref().map(|sample| &sample.value) {
        Some(SampleScalar::Real(value)) => assert!((value - 70.5).abs() < f32::EPSILON),
        other => panic!("unexpected latest {other:?}"),
    }
    let by_id = client.points_by_id("", &[POINT_ID]).await.unwrap();
    assert_eq!(by_id.points.len(), 1);
    assert_eq!(by_id.points[0].name, "zone-temp");

    set_script(&fake, Script::History);
    let from = DateTime::from_timestamp(1_700_000_000, 0).unwrap();
    let to = DateTime::from_timestamp(1_700_003_600, 0).unwrap();
    let window = HistoryWindow::new(Some(from), Some(to), 100, false).unwrap();
    let history = client.point_history(&[POINT_ID], &window).await.unwrap();
    assert_eq!(history.series.len(), 1);
    assert_eq!(history.series[0].uuid, POINT_ID);
    match &history.series[0].samples[0].value {
        SampleScalar::Real(value) => assert!((value - 71.25).abs() < f32::EPSILON),
        other => panic!("unexpected history {other:?}"),
    }
    assert_eq!(
        history.series[0].samples[0].at,
        DateTime::from_timestamp(1_700_000_100, 250_000_000).unwrap()
    );

    let seen = fake
        .seen
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert_eq!(seen.authorization, format!("Bearer {TOKEN}"));
    assert!(!seen.grpc_timeout.is_empty());
    assert!(seen.include_archived);
    assert_eq!(seen.history_method, 0);
    assert_eq!(seen.history_count, 100);
    assert_eq!(seen.history_uuids, vec![POINT_ID.to_string()]);
    assert_eq!(
        seen.history_from.as_ref().map(|ts| ts.seconds),
        Some(1_700_000_000)
    );
}

#[tokio::test]
async fn status_codes_map_without_vendor_text() {
    let cases = [
        (Code::Unauthenticated, NfGrpcError::AuthFailed),
        (Code::PermissionDenied, NfGrpcError::Forbidden),
        (Code::InvalidArgument, NfGrpcError::InvalidArgument),
        (Code::DeadlineExceeded, NfGrpcError::DeadlineExceeded),
        (Code::NotFound, NfGrpcError::NotFound),
        (Code::ResourceExhausted, NfGrpcError::Throttled),
        (Code::Unavailable, NfGrpcError::Unavailable),
        (Code::Unimplemented, NfGrpcError::Unimplemented),
        (Code::Internal, NfGrpcError::Internal),
        (Code::Cancelled, NfGrpcError::Cancelled),
        (Code::OutOfRange, NfGrpcError::InvalidArgument),
        (Code::AlreadyExists, NfGrpcError::Contract),
        (Code::FailedPrecondition, NfGrpcError::Contract),
        (Code::DataLoss, NfGrpcError::Contract),
        (Code::Aborted, NfGrpcError::Transport),
        (Code::Unknown, NfGrpcError::Transport),
    ];
    let (mut client, fake) = connect_fake(Fake::new(Script::Status(Code::Unknown))).await;
    let query = InventoryQuery::new("", 10, 0).unwrap();
    for (code, expected) in cases {
        set_script(&fake, Script::Status(code));
        let err = client.list_points(&query).await.unwrap_err();
        assert_eq!(err, expected, "{code:?}");
        assert_eq!(err.to_string(), expected.as_str());
        assert!(!err.to_string().contains(CANARY));
        assert_eq!(err.retryable(), expected.retryable());
    }
}

#[test]
fn elapsed_deadline_is_not_reported_as_cancelled() {
    let elapsed = tonic::Status::cancelled(tonic::TimeoutExpired(()).to_string());
    assert_eq!(
        crate::error::map_status(&elapsed),
        NfGrpcError::DeadlineExceeded
    );
    let cancelled = tonic::Status::cancelled("client went away");
    assert_eq!(crate::error::map_status(&cancelled), NfGrpcError::Cancelled);
}

#[tokio::test]
async fn oversized_response_is_its_own_category() {
    let fake = Fake::new(Script::Huge);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let incoming = TcpListenerStream::new(listener);
    let service = PointManagerServer::new(FakeHandle(std::sync::Arc::new(fake)));
    tokio::spawn(async move {
        Server::builder()
            .add_service(service)
            .serve_with_incoming(incoming)
            .await
            .unwrap();
    });
    let channel = Endpoint::from_shared(format!("http://{addr}"))
        .unwrap()
        .connect()
        .await
        .unwrap();
    let limits = Limits::new(Duration::from_secs(2), Duration::from_secs(2), 1024).unwrap();
    let mut client = NfReadClient::from_channel(channel, BearerToken::new(TOKEN).unwrap(), limits);
    let err = client
        .list_points(&InventoryQuery::new("", 1, 0).unwrap())
        .await
        .unwrap_err();
    assert_eq!(err, NfGrpcError::ResponseTooLarge);
    assert!(!err.to_string().contains("bytes"));
}

#[tokio::test]
async fn missing_sample_timestamp_is_contract() {
    let (mut client, _) = connect_fake(Fake::new(Script::MissingTimestamp)).await;
    let err = client
        .list_points(&InventoryQuery::new("", 1, 0).unwrap())
        .await
        .unwrap_err();
    assert_eq!(err, NfGrpcError::Contract);
}

#[test]
fn local_guards_do_not_dial() {
    assert!(matches!(
        BearerToken::new("  "),
        Err(NfGrpcError::AuthNotConfigured)
    ));
    let token = BearerToken::new("super-secret-token").unwrap();
    let rendered = format!("{token:?}");
    assert_eq!(rendered, "BearerToken([redacted])");
    assert!(!rendered.contains("super-secret-token"));
    assert!(matches!(
        Limits::new(Duration::from_secs(1), Duration::ZERO, 1024),
        Err(NfGrpcError::Config)
    ));
    assert!(InventoryQuery::new("bad\nlayer", 10, 0).is_err());
    assert!(InventoryQuery::new("", 0, 0).is_err());
    assert!(InventoryQuery::new("", 10, -1).is_err());
    assert!(HistoryWindow::new(None, None, 10_001, false).is_err());
    let later = DateTime::from_timestamp(20, 0).unwrap();
    let earlier = DateTime::from_timestamp(10, 0).unwrap();
    assert!(HistoryWindow::new(Some(later), Some(earlier), 1, false).is_err());
}

#[tokio::test]
async fn plaintext_and_userinfo_endpoints_fail_before_dial() {
    let bearer = BearerToken::new(TOKEN).unwrap();
    let err = NfReadClient::connect("http://127.0.0.1:9", bearer, Limits::default())
        .await
        .unwrap_err();
    assert_eq!(err, NfGrpcError::TlsRequired);

    let bearer = BearerToken::new(TOKEN).unwrap();
    let err = NfReadClient::connect(
        "https://user:secret@example.test",
        bearer,
        Limits::default(),
    )
    .await
    .unwrap_err();
    assert_eq!(err, NfGrpcError::Config);
    assert!(!err.to_string().contains("secret"));
}

#[test]
fn vendored_proto_matches_the_contract_note() {
    use sha2::{Digest, Sha256};
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("proto");
    let contract = std::fs::read_to_string(root.join("CONTRACT.md")).unwrap();
    assert!(contract.contains(CONTRACT_COMMIT));
    assert!(contract.contains("authorization"));
    assert!(contract.contains("GetPoints"));
    assert!(contract.contains("GetPointsById"));
    assert!(contract.contains("GetData"));
    assert!(contract.contains("readonly"));
    let mut checked = 0;
    for line in contract.lines() {
        let Some(rest) = line.strip_prefix("file-sha256: ") else {
            continue;
        };
        let mut parts = rest.split_whitespace();
        let expected = parts.next().unwrap();
        let rel = parts.next().unwrap();
        let bytes = std::fs::read(root.join(rel)).unwrap();
        let actual = hex_encode(Sha256::digest(&bytes).as_slice());
        assert_eq!(actual, expected, "{rel}");
        checked += 1;
    }
    assert_eq!(checked, 6);
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(char::from(HEX[usize::from(byte >> 4)]));
        out.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    out
}
