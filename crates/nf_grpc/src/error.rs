//! gRPC status codes as stable categories. Display never includes the
//! server status message.

use std::fmt;

use tonic::Code;

/// Failure from the read-only NF gRPC client.
///
/// Categories are stable tokens. They do not carry vendor body text.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NfGrpcError {
    AuthNotConfigured,
    AuthFailed,
    Forbidden,
    InvalidArgument,
    NotFound,
    Throttled,
    DeadlineExceeded,
    ResponseTooLarge,
    RequestTooLarge,
    Unavailable,
    Unimplemented,
    Internal,
    Cancelled,
    Transport,
    Contract,
    TlsRequired,
    Config,
}

impl NfGrpcError {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::AuthNotConfigured => "auth_not_configured",
            Self::AuthFailed => "auth_failed",
            Self::Forbidden => "forbidden",
            Self::InvalidArgument => "invalid_argument",
            Self::NotFound => "not_found",
            Self::Throttled => "throttled",
            Self::DeadlineExceeded => "deadline_exceeded",
            Self::ResponseTooLarge => "response_too_large",
            Self::RequestTooLarge => "request_too_large",
            Self::Unavailable => "unavailable",
            Self::Unimplemented => "unimplemented",
            Self::Internal => "internal",
            Self::Cancelled => "cancelled",
            Self::Transport => "transport",
            Self::Contract => "contract",
            Self::TlsRequired => "tls_required",
            Self::Config => "config_invalid",
        }
    }

    pub fn retryable(self) -> bool {
        matches!(
            self,
            Self::Throttled | Self::DeadlineExceeded | Self::Unavailable | Self::Transport
        )
    }
}

impl fmt::Display for NfGrpcError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl std::error::Error for NfGrpcError {}

/// tonic 0.12 uses this prefix when the decoded frame exceeds the client cap.
const DECODED_TOO_LARGE: &str = "Error, decoded message length too large";
/// Same codec, for a request the client refused to encode.
const ENCODED_TOO_LARGE: &str = "Error, encoded message length too large";

pub(crate) fn map_status(status: &tonic::Status) -> NfGrpcError {
    let message = status.message();
    if message.starts_with(DECODED_TOO_LARGE) {
        return NfGrpcError::ResponseTooLarge;
    }
    if message.starts_with(ENCODED_TOO_LARGE) {
        return NfGrpcError::RequestTooLarge;
    }
    match status.code() {
        Code::Ok => NfGrpcError::Contract,
        // tonic reports an elapsed per-request deadline as CANCELLED with
        // the `TimeoutExpired` text, on the client and the server side.
        Code::Cancelled if status.message() == tonic::TimeoutExpired(()).to_string() => {
            NfGrpcError::DeadlineExceeded
        }
        Code::Cancelled => NfGrpcError::Cancelled,
        Code::Unknown => NfGrpcError::Transport,
        Code::InvalidArgument => NfGrpcError::InvalidArgument,
        Code::DeadlineExceeded => NfGrpcError::DeadlineExceeded,
        Code::NotFound => NfGrpcError::NotFound,
        Code::AlreadyExists => NfGrpcError::Contract,
        Code::PermissionDenied => NfGrpcError::Forbidden,
        Code::ResourceExhausted => NfGrpcError::Throttled,
        Code::FailedPrecondition => NfGrpcError::Contract,
        Code::Aborted => NfGrpcError::Transport,
        Code::OutOfRange => NfGrpcError::InvalidArgument,
        Code::Unimplemented => NfGrpcError::Unimplemented,
        Code::Internal => NfGrpcError::Internal,
        Code::Unavailable => NfGrpcError::Unavailable,
        Code::DataLoss => NfGrpcError::Contract,
        Code::Unauthenticated => NfGrpcError::AuthFailed,
    }
}
