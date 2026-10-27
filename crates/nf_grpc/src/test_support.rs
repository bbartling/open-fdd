//! In-process `PointManager` fake for downstream parity tests.
//!
//! Compiled only with the `test-support` feature, which only dev-dependencies
//! enable. It serves `GetData` from fixed series over plaintext loopback; the
//! production `NfReadClient::connect` path stays TLS-only.

use std::net::SocketAddr;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

use chrono::{DateTime, Utc};
use tokio_stream::wrappers::TcpListenerStream;
use tonic::transport::{Endpoint, Server};
use tonic::{Code, Request, Response, Status};

use crate::client::{BearerToken, HistorySeries, Limits, NfReadClient, SampleScalar};
use crate::error::NfGrpcError;
use crate::proto::point_manager_server::{PointManager, PointManagerServer};
use crate::proto::value::ValueType;
use crate::proto::{
    DataVector, GetDataReply, GetDataRequest, GetPointsByIdRequest, GetPointsReply,
    GetPointsRequest, Value,
};

/// What the fake answers to `GetData`.
#[derive(Debug, Clone)]
pub enum FakeReply {
    /// Return these series. Each request only gets the requested uuids.
    Series(Vec<HistorySeries>),
    /// Fail every call with this gRPC status code (numeric, e.g. 16).
    Status(i32),
    /// Sleep before answering, to exercise client deadlines.
    Stall(Duration),
}

/// Request facts the fake saw. Bearer values are compared, never printed.
#[derive(Debug, Clone, Default)]
pub struct FakeSeen {
    pub authorizations: Vec<String>,
    pub history_batches: Vec<Vec<String>>,
    pub history_methods: Vec<i32>,
    pub history_from_seconds: Vec<i64>,
    pub history_to_seconds: Vec<i64>,
}

struct State {
    reply: Mutex<FakeReply>,
    /// Status codes returned before `reply`, one per call.
    queued: Mutex<Vec<i32>>,
    seen: Mutex<FakeSeen>,
}

/// Handle to a running fake. The server task ends with the test runtime.
#[derive(Clone)]
pub struct FakePointManager {
    state: Arc<State>,
    addr: SocketAddr,
}

impl FakePointManager {
    /// Bind `127.0.0.1:0` and serve `PointManager`.
    pub async fn spawn(reply: FakeReply) -> Result<Self, NfGrpcError> {
        let state = Arc::new(State {
            reply: Mutex::new(reply),
            queued: Mutex::new(Vec::new()),
            seen: Mutex::new(FakeSeen::default()),
        });
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|_| NfGrpcError::Transport)?;
        let addr = listener.local_addr().map_err(|_| NfGrpcError::Transport)?;
        let service = PointManagerServer::new(Handle(Arc::clone(&state)));
        let incoming = TcpListenerStream::new(listener);
        tokio::spawn(async move {
            let _served = Server::builder()
                .add_service(service)
                .serve_with_incoming(incoming)
                .await;
        });
        Ok(Self { state, addr })
    }

    pub fn addr(&self) -> SocketAddr {
        self.addr
    }

    pub fn set_reply(&self, reply: FakeReply) {
        *self
            .state
            .reply
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = reply;
    }

    /// Fail the next calls with these codes, in order, then use `reply`.
    pub fn queue_statuses(&self, codes: &[i32]) {
        let mut queued = self
            .state
            .queued
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        queued.extend(codes.iter().rev().copied());
    }

    pub fn seen(&self) -> FakeSeen {
        self.state
            .seen
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    /// Plaintext loopback client for this fake. Not reachable from the
    /// production connect path, which requires `https`.
    pub async fn client(
        &self,
        bearer: BearerToken,
        limits: Limits,
    ) -> Result<NfReadClient, NfGrpcError> {
        let endpoint = Endpoint::from_shared(format!("http://{}", self.addr))
            .map_err(|_| NfGrpcError::Config)?
            .connect_timeout(limits.connect)
            .timeout(limits.deadline);
        let mut last = NfGrpcError::Transport;
        for _ in 0..20 {
            match endpoint.connect().await {
                Ok(channel) => return Ok(NfReadClient::from_channel(channel, bearer, limits)),
                Err(_) => {
                    last = NfGrpcError::Transport;
                    tokio::time::sleep(Duration::from_millis(20)).await;
                }
            }
        }
        Err(last)
    }
}

struct Handle(Arc<State>);

impl Handle {
    fn note(&self, authorization: Option<&str>) {
        if let Some(value) = authorization {
            self.0
                .seen
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .authorizations
                .push(value.to_string());
        }
    }

    fn next_status(&self) -> Option<Status> {
        let code = self
            .0
            .queued
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .pop()?;
        Some(Status::new(Code::from(code), "fake status"))
    }

    fn reply(&self) -> FakeReply {
        self.0
            .reply
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }
}

fn authorization<T>(request: &Request<T>) -> Option<&str> {
    request
        .metadata()
        .get("authorization")
        .and_then(|value| value.to_str().ok())
}

fn to_value(at: DateTime<Utc>, scalar: &SampleScalar) -> Value {
    let nanos = i32::try_from(at.timestamp_subsec_nanos()).unwrap_or(0);
    let value_type = match scalar {
        SampleScalar::Null => ValueType::Null(true),
        SampleScalar::Boolean(bit) => ValueType::Boolean(*bit),
        SampleScalar::Unsigned(number) => ValueType::Unsigned(*number),
        SampleScalar::Signed(number) => ValueType::Signed(*number),
        SampleScalar::Real(number) => ValueType::Real(*number),
        SampleScalar::Double(number) => ValueType::Double(*number),
        SampleScalar::OctetString(bytes) => ValueType::OctetString(bytes.clone()),
        SampleScalar::Text(text) => ValueType::CharacterString(text.clone()),
    };
    Value {
        ts: Some(prost_types::Timestamp {
            seconds: at.timestamp(),
            nanos,
        }),
        value_type: Some(value_type),
        ..Value::default()
    }
}

#[tonic::async_trait]
impl PointManager for Handle {
    async fn get_points(
        &self,
        request: Request<GetPointsRequest>,
    ) -> Result<Response<GetPointsReply>, Status> {
        self.note(authorization(&request));
        Err(Status::unimplemented("history-only fake"))
    }

    async fn get_points_by_id(
        &self,
        request: Request<GetPointsByIdRequest>,
    ) -> Result<Response<GetPointsReply>, Status> {
        self.note(authorization(&request));
        Err(Status::unimplemented("history-only fake"))
    }

    async fn get_data(
        &self,
        request: Request<GetDataRequest>,
    ) -> Result<Response<GetDataReply>, Status> {
        self.note(authorization(&request));
        let inner = request.into_inner();
        {
            let mut seen = self.0.seen.lock().unwrap_or_else(PoisonError::into_inner);
            seen.history_batches.push(inner.uuids.clone());
            seen.history_methods.push(inner.method);
            seen.history_from_seconds
                .push(inner.from.map(|ts| ts.seconds).unwrap_or(-1));
            seen.history_to_seconds
                .push(inner.to.map(|ts| ts.seconds).unwrap_or(-1));
        }
        if let Some(status) = self.next_status() {
            return Err(status);
        }
        let series = match self.reply() {
            FakeReply::Status(code) => {
                return Err(Status::new(Code::from(code), "fake status"));
            }
            FakeReply::Stall(wait) => {
                tokio::time::sleep(wait).await;
                Vec::new()
            }
            FakeReply::Series(series) => series,
        };
        let data = series
            .iter()
            .filter(|one| inner.uuids.iter().any(|id| id == &one.uuid))
            .map(|one| DataVector {
                uuid: one.uuid.clone(),
                values: one
                    .samples
                    .iter()
                    .map(|sample| to_value(sample.at, &sample.value))
                    .collect(),
            })
            .collect();
        Ok(Response::new(GetDataReply { data }))
    }

    type ObservePointsUpdatesStream =
        tokio_stream::Once<Result<crate::proto::ObservePointsUpdatesReply, Status>>;
    type ObserveDataUpdatesStream =
        tokio_stream::Once<Result<crate::proto::ObserveDataUpdatesReply, Status>>;
    type ObserveErrorUpdatesStream =
        tokio_stream::Once<Result<crate::proto::ObserveErrorUpdatesReply, Status>>;

    async fn observe_points_updates(
        &self,
        _request: Request<crate::proto::ObservePointsUpdatesRequest>,
    ) -> Result<Response<Self::ObservePointsUpdatesStream>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }

    async fn observe_data_updates(
        &self,
        _request: Request<crate::proto::ObserveDataUpdatesRequest>,
    ) -> Result<Response<Self::ObserveDataUpdatesStream>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }

    async fn observe_error_updates(
        &self,
        _request: Request<crate::proto::ObserveErrorUpdatesRequest>,
    ) -> Result<Response<Self::ObserveErrorUpdatesStream>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }

    async fn get_layers(
        &self,
        _: Request<crate::proto::GetLayersRequest>,
    ) -> Result<Response<crate::proto::GetLayersReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_layer(
        &self,
        _: Request<crate::proto::CreateLayerRequest>,
    ) -> Result<Response<crate::proto::CreateLayerReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn update_layer(
        &self,
        _: Request<crate::proto::UpdateLayerRequest>,
    ) -> Result<Response<crate::proto::UpdateLayerReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_layer(
        &self,
        _: Request<crate::proto::DeleteLayerRequest>,
    ) -> Result<Response<crate::proto::DeleteLayerReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_distinct_attrs(
        &self,
        _: Request<crate::proto::GetDistinctAttrsRequest>,
    ) -> Result<Response<crate::proto::GetDistinctAttrsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_distinct_attr_keys(
        &self,
        _: Request<crate::proto::GetDistinctAttrsRequest>,
    ) -> Result<Response<crate::proto::GetDistinctAttrsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn add_points_data(
        &self,
        _: Request<crate::proto::AddPointsDataRequest>,
    ) -> Result<Response<crate::proto::AddPointsDataReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn add_data(
        &self,
        _: Request<crate::proto::AddDataRequest>,
    ) -> Result<Response<crate::proto::AddDataReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_data_summary(
        &self,
        _: Request<crate::proto::GetDataSummaryRequest>,
    ) -> Result<Response<crate::proto::GetDataSummaryReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn update_points(
        &self,
        _: Request<crate::proto::UpdatePointsRequest>,
    ) -> Result<Response<crate::proto::UpdatePointsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn rename_point(
        &self,
        _: Request<crate::proto::RenamePointRequest>,
    ) -> Result<Response<crate::proto::RenamePointReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn copy_attributes(
        &self,
        _: Request<crate::proto::CopyAttributesRequest>,
    ) -> Result<Response<crate::proto::CopyAttributesReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_points(
        &self,
        _: Request<crate::proto::DeletePointsRequest>,
    ) -> Result<Response<crate::proto::DeletePointsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn add_tags(
        &self,
        _: Request<crate::proto::AddTagsRequest>,
    ) -> Result<Response<crate::proto::AddTagsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_tags(
        &self,
        _: Request<crate::proto::DeleteTagsRequest>,
    ) -> Result<Response<crate::proto::DeleteTagsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_config_keys(
        &self,
        _: Request<crate::proto::GetConfigKeysRequest>,
    ) -> Result<Response<crate::proto::GetConfigKeysReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn set_config_key(
        &self,
        _: Request<crate::proto::SetConfigKeyRequest>,
    ) -> Result<Response<crate::proto::SetConfigKeyReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_config_keys(
        &self,
        _: Request<crate::proto::DeleteConfigKeysRequest>,
    ) -> Result<Response<crate::proto::DeleteConfigKeysReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_export(
        &self,
        _: Request<crate::proto::CreateExportRequest>,
    ) -> Result<Response<crate::proto::CreateExportReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_data_export(
        &self,
        _: Request<crate::proto::CreateDataExportRequest>,
    ) -> Result<Response<crate::proto::CreateDataExportReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_versions(
        &self,
        _: Request<crate::proto::GetVersionsRequest>,
    ) -> Result<Response<crate::proto::GetVersionsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn aggregate_points(
        &self,
        _: Request<crate::proto::AggregatePointsRequest>,
    ) -> Result<Response<crate::proto::AggregatePointsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_point_errors(
        &self,
        _: Request<crate::proto::GetPointErrorsRequest>,
    ) -> Result<Response<crate::proto::GetPointErrorsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_conversion(
        &self,
        _: Request<crate::proto::CreateConversionRequest>,
    ) -> Result<Response<crate::proto::CreateConversionReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_conversions(
        &self,
        _: Request<crate::proto::GetConversionsRequest>,
    ) -> Result<Response<crate::proto::GetConversionsReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn update_conversion(
        &self,
        _: Request<crate::proto::UpdateConversionRequest>,
    ) -> Result<Response<crate::proto::UpdateConversionReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_conversion(
        &self,
        _: Request<crate::proto::DeleteConversionRequest>,
    ) -> Result<Response<crate::proto::DeleteConversionReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn create_quality_rule(
        &self,
        _: Request<crate::proto::CreateQualityRuleRequest>,
    ) -> Result<Response<crate::proto::CreateQualityRuleReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn get_quality_rules(
        &self,
        _: Request<crate::proto::GetQualityRulesRequest>,
    ) -> Result<Response<crate::proto::GetQualityRulesReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn update_quality_rule(
        &self,
        _: Request<crate::proto::UpdateQualityRuleRequest>,
    ) -> Result<Response<crate::proto::UpdateQualityRuleReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn delete_quality_rule(
        &self,
        _: Request<crate::proto::DeleteQualityRuleRequest>,
    ) -> Result<Response<crate::proto::DeleteQualityRuleReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
    async fn backtest_quality_rule(
        &self,
        _: Request<crate::proto::BacktestQualityRuleRequest>,
    ) -> Result<Response<crate::proto::BacktestQualityRuleReply>, Status> {
        Err(Status::unimplemented("read-only test server"))
    }
}
