//! Typed API errors — maps to FastAPI HTTPException + validation errors.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;
use thiserror::Error;
use validator::ValidationErrors;

#[derive(Debug, Error)]
pub enum ApiError {
    #[error("{0}")]
    BadRequest(String),

    #[error("{0}")]
    #[allow(dead_code)]
    Unauthorized(String),

    #[error("{0}")]
    Forbidden(String),

    #[error("{0}")]
    #[allow(dead_code)]
    NotFound(String),

    #[error("validation error")]
    Validation(ValidationErrors),

    #[error("bacnet error: {0}")]
    Bacnet(String),

    #[error("upstream error: {0}")]
    Upstream(String),

    #[error("internal error: {0}")]
    #[allow(dead_code)]
    Internal(String),
}

#[derive(Serialize)]
struct ErrorBody {
    detail: String,
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let (status, detail) = match &self {
            ApiError::BadRequest(m) => (StatusCode::BAD_REQUEST, m.clone()),
            ApiError::Unauthorized(m) => (StatusCode::UNAUTHORIZED, m.clone()),
            ApiError::Forbidden(m) => (StatusCode::FORBIDDEN, m.clone()),
            ApiError::NotFound(m) => (StatusCode::NOT_FOUND, m.clone()),
            ApiError::Validation(e) => (StatusCode::UNPROCESSABLE_ENTITY, e.to_string()),
            ApiError::Bacnet(m) | ApiError::Upstream(m) => (StatusCode::BAD_GATEWAY, m.clone()),
            ApiError::Internal(m) => (StatusCode::INTERNAL_SERVER_ERROR, m.clone()),
        };
        (status, Json(ErrorBody { detail })).into_response()
    }
}

pub type ApiResult<T> = Result<T, ApiError>;

pub fn validate<T: validator::Validate>(value: &T) -> ApiResult<()> {
    value.validate().map_err(ApiError::Validation)
}
