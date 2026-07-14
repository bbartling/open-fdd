use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};

use crate::error::{validate, ApiError, ApiResult};
use crate::models::*;
use crate::state::AppState;

async fn bacnet_read(
    State(state): State<AppState>,
    Json(body): Json<BacnetReadRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .bacnet_client
        .read_property(
            body.device_instance,
            &body.object_type,
            body.object_instance,
            &body.property_id,
        )
        .await
        .map_err(ApiError::Bacnet)?;
    Ok(Json(merge_ok(result)))
}

async fn bacnet_write(
    State(state): State<AppState>,
    Json(body): Json<BacnetWriteRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    if !body.approved {
        let result = state
            .bacnet_client
            .write_dry_run(
                body.device_instance,
                &body.object_type,
                body.object_instance,
                body.value,
                &body.property_id,
                body.priority,
                body.value_type.as_deref(),
            )
            .map_err(ApiError::BadRequest)?;
        let mut v = merge_ok(result);
        v["skipped"] = json!("not approved");
        return Ok(Json(v));
    }
    let result = state
        .bacnet_client
        .write_property(
            body.device_instance,
            &body.object_type,
            body.object_instance,
            body.value,
            &body.property_id,
            body.priority,
            body.value_type.as_deref(),
        )
        .await
        .map_err(|e| {
            if e.contains("requires") || e.contains("unknown") {
                ApiError::BadRequest(e)
            } else {
                ApiError::Bacnet(e)
            }
        })?;
    Ok(Json(merge_ok(result)))
}

async fn bacnet_write_dry_run(
    State(state): State<AppState>,
    Json(body): Json<BacnetWriteRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .bacnet_client
        .write_dry_run(
            body.device_instance,
            &body.object_type,
            body.object_instance,
            body.value,
            &body.property_id,
            body.priority,
            body.value_type.as_deref(),
        )
        .map_err(ApiError::BadRequest)?;
    Ok(Json(merge_ok(result)))
}

async fn bacnet_poll_status(State(state): State<AppState>) -> Json<Value> {
    let status = state.poll_engine.status().await;
    let mut v = json!({ "ok": true });
    if let Some(obj) = v.as_object_mut() {
        if let Some(s) = status.as_object() {
            for (k, val) in s {
                obj.insert(k.clone(), val.clone());
            }
        }
    }
    Json(v)
}

async fn bacnet_poll_once(State(state): State<AppState>) -> ApiResult<Json<Value>> {
    let result = state
        .poll_engine
        .poll_once()
        .await
        .map_err(ApiError::Bacnet)?;
    Ok(Json(merge_ok(result)))
}

async fn bacnet_rpm(
    State(state): State<AppState>,
    Json(body): Json<BacnetRpmRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let objects: Vec<Value> = body
        .objects
        .iter()
        .map(|o| {
            json!({
                "object_type": o.object_type,
                "object_instance": o.object_instance,
                "properties": o.properties.iter().map(|p| json!({
                    "property_id": p.property_id,
                    "array_index": p.array_index,
                })).collect::<Vec<_>>(),
            })
        })
        .collect();
    let result = state
        .bacnet_client
        .read_property_multiple(body.device_instance, &objects)
        .await
        .map_err(ApiError::Bacnet)?;
    Ok(Json(merge_ok(result)))
}

async fn bacnet_whois(
    State(state): State<AppState>,
    Json(body): Json<BacnetWhoisRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let devices = state
        .bacnet_client
        .who_is(body.low, body.high)
        .await
        .map_err(ApiError::Bacnet)?;
    Ok(Json(
        json!({ "ok": true, "count": devices.len(), "devices": devices }),
    ))
}

async fn bacnet_whois_router(State(state): State<AppState>) -> ApiResult<Json<Value>> {
    let routers = state
        .bacnet_client
        .who_is_router_to_network()
        .await
        .map_err(ApiError::Bacnet)?;
    Ok(Json(
        json!({ "ok": true, "count": routers.len(), "routers": routers }),
    ))
}

async fn bacnet_priority_array(
    State(state): State<AppState>,
    Json(body): Json<BacnetObjectRef>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .bacnet_client
        .read_priority_array(
            body.device_instance,
            &body.object_type,
            body.object_instance,
        )
        .await
        .map_err(ApiError::Bacnet)?;
    Ok(Json(merge_ok(result)))
}

async fn bacnet_supervisory(
    State(state): State<AppState>,
    Json(body): Json<DeviceInstanceRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .bacnet_client
        .supervisory_logic_check(body.device_instance)
        .await
        .map_err(ApiError::Bacnet)?;
    Ok(Json(merge_ok(result)))
}

async fn list_server_objects(State(state): State<AppState>) -> ApiResult<Json<Value>> {
    let objects = state
        .bacnet_server
        .list_objects()
        .await
        .map_err(ApiError::BadRequest)?;
    Ok(Json(json!({ "ok": true, "objects": objects })))
}

async fn list_server_commandable(State(state): State<AppState>) -> ApiResult<Json<Value>> {
    let objects = state
        .bacnet_server
        .list_commandable()
        .await
        .map_err(ApiError::BadRequest)?;
    Ok(Json(json!({ "ok": true, "objects": objects })))
}

async fn update_server_points(
    State(state): State<AppState>,
    Json(body): Json<ServerUpdatePointsRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .bacnet_server
        .update_points(body.updates)
        .await
        .map_err(ApiError::BadRequest)?;
    Ok(Json(json!({ "ok": true, "result": result })))
}

fn merge_ok(result: Value) -> Value {
    let mut base = json!({ "ok": true });
    if let Some(obj) = base.as_object_mut() {
        if let Some(res) = result.as_object() {
            for (k, v) in res {
                obj.insert(k.clone(), v.clone());
            }
        }
    }
    base
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/bacnet/read", post(bacnet_read))
        .route("/bacnet/write", post(bacnet_write))
        .route("/bacnet/write-dry-run", post(bacnet_write_dry_run))
        .route("/bacnet/poll/status", get(bacnet_poll_status))
        .route("/bacnet/poll/once", post(bacnet_poll_once))
        .route("/bacnet/rpm", post(bacnet_rpm))
        .route("/bacnet/whois", post(bacnet_whois))
        .route("/bacnet/whois-router", post(bacnet_whois_router))
        .route("/bacnet/priority-array", post(bacnet_priority_array))
        .route("/bacnet/supervisory", post(bacnet_supervisory))
        .route("/bacnet/server/objects", get(list_server_objects))
        .route("/bacnet/server/commandable", get(list_server_commandable))
        .route("/bacnet/server/update", post(update_server_points))
}
