pub mod bacnet;
pub mod compat;
pub mod haystack;
pub mod modbus;
pub mod rest;
pub mod root;
pub mod weather;

use axum::Router;

use crate::openapi::build_openapi;
use crate::state::AppState;

pub fn api_routes(state: AppState) -> Router {
    Router::new()
        .merge(root::router())
        .merge(bacnet::router())
        .merge(weather::router())
        .merge(modbus::router())
        .merge(haystack::router())
        .merge(rest::router())
        .merge(compat::router())
        .nest("/api", {
            Router::new()
                .merge(bacnet::router())
                .merge(weather::router())
                .merge(modbus::router())
                .merge(haystack::router())
                .merge(rest::router())
        })
        .with_state(state)
}

pub fn openapi_routes(_state: AppState) -> Router<()> {
    use utoipa_swagger_ui::{Config, SwaggerUi};

    let spec = build_openapi();

    Router::new().merge(
        SwaggerUi::new("/docs").url("/openapi.json", spec).config(
            Config::default()
                .validator_url("none")
                .persist_authorization(true)
                .try_it_out_enabled(true)
                .doc_expansion("list"),
        ),
    )
}
