use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};

use crate::state::AppState;

async fn get_weather(State(state): State<AppState>) -> Json<Value> {
    Json(state.weather.to_dict().await)
}

async fn refresh_weather(State(state): State<AppState>) -> Json<Value> {
    let _ = state.weather.refresh_now().await;
    let mut v = state.weather.to_dict().await;
    if let Some(obj) = v.as_object_mut() {
        obj.insert("ok".into(), json!(true));
    }
    Json(v)
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/weather", get(get_weather))
        .route("/weather/refresh", post(refresh_weather))
}
