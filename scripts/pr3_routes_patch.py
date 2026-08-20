from pathlib import Path

path = Path('services/central/src/routes.rs')
s = path.read_text()

old = '''        .route("/api/analytics/ahu-health", post(analytics_ahu_health))
        .route(
            "/api/analytics/chiller-health",
            post(analytics_chiller_health),
        )
'''
new = '''        .route("/api/analytics/ahu-health", post(analytics_ahu_health))
        .route(
            "/api/analytics/ahu-temperature-health",
            post(analytics_ahu_temperature_health),
        )
        .route(
            "/api/analytics/ahu-pressure-health",
            post(analytics_ahu_pressure_health),
        )
        .route(
            "/api/analytics/ahu-economizer-health",
            post(analytics_ahu_economizer_health),
        )
        .route(
            "/api/analytics/chiller-health",
            post(analytics_chiller_health),
        )
        .route(
            "/api/analytics/cooling-tower-health",
            post(analytics_cooling_tower_health),
        )
        .route(
            "/api/analytics/sensor-faults",
            post(analytics_sensor_faults),
        )
        .route(
            "/api/analytics/pid-hunting",
            post(analytics_pid_hunting),
        )
'''
if old not in s:
    raise SystemExit('route anchor not found')
s = s.replace(old, new, 1)

old = '''async fn analytics_ahu_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_ahu(&req).await.to_json(),
    }))
}

async fn analytics_chiller_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
'''
new = '''async fn analytics_ahu_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_ahu(&req).await.to_json(),
    }))
}

async fn analytics_ahu_temperature_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_ahu_temperature(&req).await.to_json(),
    }))
}

async fn analytics_ahu_pressure_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_ahu_pressure(&req).await.to_json(),
    }))
}

async fn analytics_ahu_economizer_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_ahu_economizer(&req).await.to_json(),
    }))
}

async fn analytics_chiller_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
'''
if old not in s:
    raise SystemExit('AHU handler anchor not found')
s = s.replace(old, new, 1)

old = '''async fn analytics_chiller_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_chiller(&req).await.to_json(),
    }))
}

async fn analytics_boiler_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
'''
new = '''async fn analytics_chiller_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_chiller(&req).await.to_json(),
    }))
}

async fn analytics_cooling_tower_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_cooling_tower(&req).await.to_json(),
    }))
}

async fn analytics_sensor_faults(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_sensor_faults(&req).await.to_json(),
    }))
}

async fn analytics_pid_hunting(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant_health::handle_pid_hunting(&req).await.to_json(),
    }))
}

async fn analytics_boiler_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
'''
if old not in s:
    raise SystemExit('chiller handler anchor not found')
s = s.replace(old, new, 1)

path.write_text(s)
