//! TLS read client for `PointManager.GetPoints`, `GetPointsById`, and `GetData`.

use std::collections::BTreeMap;
use std::time::Duration;

use chrono::{DateTime, Utc};
use tonic::metadata::MetadataValue;
use tonic::transport::{Channel, ClientTlsConfig, Endpoint};
use tonic::Request;

use crate::error::{map_status, NfGrpcError};
use crate::proto::point_manager_client::PointManagerClient;
use crate::proto::resample_options::ResampleMethod;
use crate::proto::value::ValueType;
use crate::proto::{
    DataVector, GetDataReply, GetDataRequest, GetPointsByIdRequest, GetPointsReply,
    GetPointsRequest, GetPointsResponseFormat, Point, Value,
};

/// Access token already issued by NF `AuthService.IssueToken`.
///
/// The client sends it as gRPC metadata `authorization: Bearer <token>`.
/// `Debug` does not include the token.
pub struct BearerToken {
    token: String,
}

impl BearerToken {
    pub fn new(token: &str) -> Result<Self, NfGrpcError> {
        let token = token.trim();
        if token.is_empty() {
            return Err(NfGrpcError::AuthNotConfigured);
        }
        if token.len() > 8192 || !token.bytes().all(|byte| (0x21..=0x7e).contains(&byte)) {
            return Err(NfGrpcError::Config);
        }
        Ok(Self {
            token: token.to_string(),
        })
    }
}

impl std::fmt::Debug for BearerToken {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("BearerToken([redacted])")
    }
}

/// Deadlines and message caps. Zero or an unbounded response size is rejected.
#[derive(Debug, Clone, Copy)]
pub struct Limits {
    pub connect: Duration,
    pub deadline: Duration,
    pub max_response_bytes: usize,
    pub max_request_bytes: usize,
}

impl Limits {
    pub const DEFAULT_CONNECT: Duration = Duration::from_secs(10);
    pub const DEFAULT_DEADLINE: Duration = Duration::from_secs(45);
    pub const DEFAULT_MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;
    pub const DEFAULT_MAX_REQUEST_BYTES: usize = 1024 * 1024;
    pub const MAX_RESPONSE_CAP: usize = 32 * 1024 * 1024;

    pub fn new(
        connect: Duration,
        deadline: Duration,
        max_response_bytes: usize,
    ) -> Result<Self, NfGrpcError> {
        if connect.is_zero()
            || deadline.is_zero()
            || max_response_bytes == 0
            || max_response_bytes > Self::MAX_RESPONSE_CAP
        {
            return Err(NfGrpcError::Config);
        }
        Ok(Self {
            connect,
            deadline,
            max_response_bytes,
            max_request_bytes: Self::DEFAULT_MAX_REQUEST_BYTES.min(max_response_bytes),
        })
    }
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            connect: Self::DEFAULT_CONNECT,
            deadline: Self::DEFAULT_DEADLINE,
            max_response_bytes: Self::DEFAULT_MAX_RESPONSE_BYTES,
            max_request_bytes: Self::DEFAULT_MAX_REQUEST_BYTES,
        }
    }
}

pub const MAX_PAGE_SIZE: i64 = 500;
pub const MAX_UUIDS: usize = 50;
pub const MAX_ID_LEN: usize = 128;
pub const MAX_HISTORY_COUNT: i32 = 10_000;

/// One page of `GetPoints` or `GetPointsById`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InventoryQuery {
    layer: String,
    page_size: i64,
    page_offset: i64,
    include_archived: bool,
}

impl InventoryQuery {
    pub fn new(layer: &str, page_size: i64, page_offset: i64) -> Result<Self, NfGrpcError> {
        Ok(Self {
            layer: checked_layer(layer)?,
            page_size: checked_page_size(page_size)?,
            page_offset: checked_page_offset(page_offset)?,
            include_archived: false,
        })
    }

    pub fn include_archived(mut self, include: bool) -> Self {
        self.include_archived = include;
        self
    }
}

/// Raw `GetData` window. Resample method stays `NONE` (no server rollup).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HistoryWindow {
    pub from: Option<DateTime<Utc>>,
    pub to: Option<DateTime<Utc>>,
    pub count: i32,
    pub reverse: bool,
}

impl HistoryWindow {
    pub fn new(
        from: Option<DateTime<Utc>>,
        to: Option<DateTime<Utc>>,
        count: i32,
        reverse: bool,
    ) -> Result<Self, NfGrpcError> {
        if let (Some(start), Some(end)) = (from, to) {
            if end < start {
                return Err(NfGrpcError::InvalidArgument);
            }
        }
        if !(0..=MAX_HISTORY_COUNT).contains(&count) {
            return Err(NfGrpcError::InvalidArgument);
        }
        Ok(Self {
            from,
            to,
            count,
            reverse,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum SampleScalar {
    Null,
    Boolean(bool),
    Unsigned(u32),
    Signed(i32),
    Real(f32),
    Double(f64),
    OctetString(Vec<u8>),
    Text(String),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Sample {
    pub at: DateTime<Utc>,
    pub value: SampleScalar,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PointRecord {
    pub uuid: String,
    pub name: String,
    pub layer: String,
    pub description: String,
    pub display_units: String,
    pub units: i32,
    pub point_type: i32,
    pub archived: bool,
    pub attrs: BTreeMap<String, String>,
    pub latest: Option<Sample>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct InventoryPage {
    pub points: Vec<PointRecord>,
    pub total_count: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HistorySeries {
    pub uuid: String,
    pub samples: Vec<Sample>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HistoryPage {
    pub series: Vec<HistorySeries>,
}

/// Read-only NF point client. Write RPCs are not callable through this type.
#[derive(Debug)]
pub struct NfReadClient {
    rpc: PointManagerClient<Channel>,
    bearer: BearerToken,
    limits: Limits,
}

impl NfReadClient {
    /// Connect with certificate verification on. `endpoint` must be `https`
    /// and must not carry userinfo.
    pub async fn connect(
        endpoint: &str,
        bearer: BearerToken,
        limits: Limits,
    ) -> Result<Self, NfGrpcError> {
        let endpoint = endpoint.trim();
        let uri: http::Uri = endpoint.parse().map_err(|_| NfGrpcError::Config)?;
        if uri.scheme_str() != Some("https") {
            return Err(NfGrpcError::TlsRequired);
        }
        let host = uri
            .host()
            .filter(|host| !host.is_empty())
            .ok_or(NfGrpcError::Config)?;
        if uri
            .authority()
            .is_some_and(|authority| authority.as_str().contains('@'))
        {
            return Err(NfGrpcError::Config);
        }
        let tls = ClientTlsConfig::new()
            .domain_name(host)
            .with_native_roots()
            .with_webpki_roots();
        let channel = Endpoint::from_shared(endpoint.to_string())
            .map_err(|_| NfGrpcError::Config)?
            .connect_timeout(limits.connect)
            .timeout(limits.deadline)
            .tls_config(tls)
            .map_err(|_| NfGrpcError::Config)?
            .connect()
            .await
            .map_err(|_| NfGrpcError::Transport)?;
        Ok(Self::from_channel(channel, bearer, limits))
    }

    pub(crate) fn from_channel(channel: Channel, bearer: BearerToken, limits: Limits) -> Self {
        let rpc = PointManagerClient::new(channel)
            .max_decoding_message_size(limits.max_response_bytes)
            .max_encoding_message_size(limits.max_request_bytes);
        Self {
            rpc,
            bearer,
            limits,
        }
    }

    /// `PointManager.GetPoints`.
    pub async fn list_points(
        &mut self,
        query: &InventoryQuery,
    ) -> Result<InventoryPage, NfGrpcError> {
        let request = GetPointsRequest {
            layer: query.layer.clone(),
            response_format: GetPointsResponseFormat::LayersCollapsed as i32,
            page_offset: query.page_offset,
            page_size: query.page_size,
            include_archived: query.include_archived,
            ..GetPointsRequest::default()
        };
        let response = self
            .rpc
            .get_points(self.authorized(request)?)
            .await
            .map_err(|status| map_status(&status))?;
        map_points(response.into_inner())
    }

    /// `PointManager.GetPointsById`.
    pub async fn points_by_id(
        &mut self,
        layer: &str,
        uuids: &[&str],
    ) -> Result<InventoryPage, NfGrpcError> {
        let request = GetPointsByIdRequest {
            layer: checked_layer(layer)?,
            uuids: checked_ids(uuids)?,
            response_format: GetPointsResponseFormat::LayersCollapsed as i32,
            ..GetPointsByIdRequest::default()
        };
        let response = self
            .rpc
            .get_points_by_id(self.authorized(request)?)
            .await
            .map_err(|status| map_status(&status))?;
        map_points(response.into_inner())
    }

    /// `PointManager.GetData` with resample method `NONE`.
    pub async fn point_history(
        &mut self,
        uuids: &[&str],
        window: &HistoryWindow,
    ) -> Result<HistoryPage, NfGrpcError> {
        let request = GetDataRequest {
            uuids: checked_ids(uuids)?,
            from: window.from.map(to_timestamp).transpose()?,
            to: window.to.map(to_timestamp).transpose()?,
            method: ResampleMethod::None as i32,
            count: window.count,
            reverse: window.reverse,
            ..GetDataRequest::default()
        };
        let response = self
            .rpc
            .get_data(self.authorized(request)?)
            .await
            .map_err(|status| map_status(&status))?;
        map_history(response.into_inner())
    }

    fn authorized<M>(&self, message: M) -> Result<Request<M>, NfGrpcError> {
        let mut request = Request::new(message);
        let header = format!("Bearer {}", self.bearer.token);
        let value = MetadataValue::try_from(header).map_err(|_| NfGrpcError::Config)?;
        request.metadata_mut().insert("authorization", value);
        request.set_timeout(self.limits.deadline);
        Ok(request)
    }
}

fn checked_layer(layer: &str) -> Result<String, NfGrpcError> {
    if layer.len() > MAX_ID_LEN || layer.bytes().any(|byte| byte < 0x20 || byte == 0x7f) {
        return Err(NfGrpcError::InvalidArgument);
    }
    Ok(layer.to_string())
}

fn checked_page_size(page_size: i64) -> Result<i64, NfGrpcError> {
    if (1..=MAX_PAGE_SIZE).contains(&page_size) {
        Ok(page_size)
    } else {
        Err(NfGrpcError::InvalidArgument)
    }
}

fn checked_page_offset(page_offset: i64) -> Result<i64, NfGrpcError> {
    if page_offset >= 0 {
        Ok(page_offset)
    } else {
        Err(NfGrpcError::InvalidArgument)
    }
}

fn checked_ids(ids: &[&str]) -> Result<Vec<String>, NfGrpcError> {
    if ids.is_empty() || ids.len() > MAX_UUIDS {
        return Err(NfGrpcError::InvalidArgument);
    }
    let mut out = Vec::with_capacity(ids.len());
    for id in ids {
        if id.is_empty()
            || id.len() > MAX_ID_LEN
            || !id.bytes().all(|byte| (0x21..=0x7e).contains(&byte))
        {
            return Err(NfGrpcError::InvalidArgument);
        }
        out.push((*id).to_string());
    }
    Ok(out)
}

fn to_timestamp(at: DateTime<Utc>) -> Result<prost_types::Timestamp, NfGrpcError> {
    let nanos =
        i32::try_from(at.timestamp_subsec_nanos()).map_err(|_| NfGrpcError::InvalidArgument)?;
    Ok(prost_types::Timestamp {
        seconds: at.timestamp(),
        nanos,
    })
}

fn from_timestamp(ts: &prost_types::Timestamp) -> Result<DateTime<Utc>, NfGrpcError> {
    let nanos = u32::try_from(ts.nanos).map_err(|_| NfGrpcError::Contract)?;
    if nanos >= 1_000_000_000 {
        return Err(NfGrpcError::Contract);
    }
    DateTime::from_timestamp(ts.seconds, nanos).ok_or(NfGrpcError::Contract)
}

fn map_points(reply: GetPointsReply) -> Result<InventoryPage, NfGrpcError> {
    let mut points = Vec::with_capacity(reply.points.len());
    for point in reply.points {
        points.push(map_point(point)?);
    }
    Ok(InventoryPage {
        points,
        total_count: reply.total_count,
    })
}

fn map_point(point: Point) -> Result<PointRecord, NfGrpcError> {
    let latest = match point.latest_value {
        Some(value) => Some(map_sample(value)?),
        None => None,
    };
    Ok(PointRecord {
        uuid: point.uuid,
        name: point.name,
        layer: point.layer,
        description: point.description,
        display_units: point.display_units,
        units: point.units,
        point_type: point.point_type,
        archived: point.archived,
        attrs: point.attrs.into_iter().collect(),
        latest,
    })
}

fn map_history(reply: GetDataReply) -> Result<HistoryPage, NfGrpcError> {
    let mut series = Vec::with_capacity(reply.data.len());
    for vector in reply.data {
        series.push(map_series(vector)?);
    }
    Ok(HistoryPage { series })
}

fn map_series(vector: DataVector) -> Result<HistorySeries, NfGrpcError> {
    let mut samples = Vec::with_capacity(vector.values.len());
    for value in vector.values {
        samples.push(map_sample(value)?);
    }
    Ok(HistorySeries {
        uuid: vector.uuid,
        samples,
    })
}

fn map_sample(value: Value) -> Result<Sample, NfGrpcError> {
    let at = from_timestamp(value.ts.as_ref().ok_or(NfGrpcError::Contract)?)?;
    let scalar = match value.value_type.ok_or(NfGrpcError::Contract)? {
        ValueType::Null(_) => SampleScalar::Null,
        ValueType::Boolean(bit) => SampleScalar::Boolean(bit),
        ValueType::Unsigned(number) => SampleScalar::Unsigned(number),
        ValueType::Signed(number) => SampleScalar::Signed(number),
        ValueType::Real(number) => SampleScalar::Real(number),
        ValueType::Double(number) => SampleScalar::Double(number),
        ValueType::OctetString(bytes) => SampleScalar::OctetString(bytes),
        ValueType::CharacterString(text) => SampleScalar::Text(text),
    };
    Ok(Sample { at, value: scalar })
}
