use axum::{routing::post, Json, Router};
use serde_json::Value;

use crate::error::{validate, ApiError, ApiResult};
use crate::models::ModbusReadRequest;
use crate::services::modbus::execute_modbus_read;
use crate::state::AppState;

async fn modbus_read(Json(body): Json<ModbusReadRequest>) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let host = body.host.trim().to_string();
    if host.is_empty() {
        return Err(ApiError::BadRequest("host must be non-empty".into()));
    }
    let payload = serde_json::json!({
        "host": host,
        "port": body.port,
        "unit_id": body.unit_id,
        "timeout": body.timeout,
        "registers": body.registers,
    });
    let result = execute_modbus_read(&payload).await.map_err(|e| {
        let msg = e.to_string();
        if msg.contains("transport error")
            || msg.contains("Connection refused")
            || msg.contains("timed out")
            || msg.contains("I/O error")
        {
            ApiError::Upstream(format!("modbus_error: {msg}"))
        } else {
            ApiError::BadRequest(msg)
        }
    })?;
    Ok(Json(result))
}

pub fn router() -> Router<AppState> {
    Router::new().route("/modbus/read", post(modbus_read))
}
