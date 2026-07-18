//! OpenAPI path documentation (utoipa path stubs — handlers live in `routes/`).

#![allow(dead_code)]

use crate::models::*;

/// Service index and quick links.
#[utoipa::path(
    get,
    path = "/",
    tag = "Root",
    responses((status = 200, description = "Service metadata"))
)]
pub(crate) fn doc_root() {}

/// Liveness probe.
#[utoipa::path(
    get,
    path = "/health",
    tag = "Root",
    responses((status = 200, description = "OK"))
)]
pub(crate) fn doc_health() {}

/// Open-FDD health shape (`service`, `version`, `git_sha`, `poll_running`).
#[utoipa::path(
    get,
    path = "/api/health",
    tag = "Open-FDD",
    responses((status = 200, description = "Sidecar health"))
)]
pub(crate) fn doc_api_health() {}

/// ReadProperty on a field device (bench/low-level).
#[utoipa::path(
    post,
    path = "/bacnet/read",
    tag = "BACnet (bench)",
    request_body = BacnetReadRequest,
    security(("BearerAuth" = [])),
    responses(
        (status = 200, description = "Property value"),
        (status = 502, description = "BACnet error")
    )
)]
pub(crate) fn doc_bacnet_read() {}

/// WriteProperty with optional dry-run when `approved` is false.
#[utoipa::path(
    post,
    path = "/bacnet/write",
    tag = "BACnet (bench)",
    request_body = BacnetWriteRequest,
    security(("BearerAuth" = [])),
    responses(
        (status = 200, description = "Write result"),
        (status = 400, description = "Validation error"),
        (status = 502, description = "BACnet error")
    )
)]
pub(crate) fn doc_bacnet_write() {}

/// Validate and encode a write without touching the BACnet bus.
#[utoipa::path(
    post,
    path = "/bacnet/write-dry-run",
    tag = "BACnet (bench)",
    request_body = BacnetWriteRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Dry-run result"))
)]
pub(crate) fn doc_bacnet_write_dry_run() {}

/// ReadPropertyMultiple batch read.
#[utoipa::path(
    post,
    path = "/bacnet/rpm",
    tag = "BACnet (bench)",
    request_body = BacnetRpmRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "RPM results"))
)]
pub(crate) fn doc_bacnet_rpm() {}

/// Who-Is device discovery — send `{}` to scan all instances (0–4194303); set `low`/`high` to narrow.
#[utoipa::path(
    post,
    path = "/bacnet/whois",
    tag = "Open-FDD",
    request_body = BacnetWhoisRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Discovered devices"))
)]
pub(crate) fn doc_bacnet_whois() {}

/// Who-Is router-to-network — discovers MS/TP routers on the BACnet/IP segment (no request body).
#[utoipa::path(
    post,
    path = "/bacnet/whois-router",
    tag = "Open-FDD",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Router list"))
)]
pub(crate) fn doc_bacnet_whois_router() {}

/// Point discovery — walks object-list, reads object names, flags commandable points.
#[utoipa::path(
    post,
    path = "/api/bacnet/point-discovery",
    tag = "Open-FDD",
    request_body = DeviceInstanceRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Discovered objects with names"))
)]
pub(crate) fn doc_api_point_discovery() {}

/// Read all 16 priority-array slots for one object.
#[utoipa::path(
    post,
    path = "/bacnet/priority-array",
    tag = "Open-FDD",
    request_body = BacnetObjectRef,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Priority array slots"))
)]
pub(crate) fn doc_bacnet_priority_array() {}

/// Supervisory override audit — scans commandable points and reports active priority overrides.
#[utoipa::path(
    post,
    path = "/bacnet/supervisory",
    tag = "Open-FDD",
    request_body = DeviceInstanceRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Override audit with points_with_overrides"))
)]
pub(crate) fn doc_bacnet_supervisory() {}

/// Open-FDD supervisory override audit (preferred path) — same as `/bacnet/supervisory`.
#[utoipa::path(
    post,
    path = "/api/bacnet/supervisory",
    tag = "Open-FDD",
    request_body = DeviceInstanceRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Override audit with points_with_overrides"))
)]
pub(crate) fn doc_api_supervisory() {}

/// Background poll engine status and last values.
#[utoipa::path(
    get,
    path = "/bacnet/poll/status",
    tag = "BACnet (bench)",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Poll status"))
)]
pub(crate) fn doc_bacnet_poll_status() {}

/// Run one poll cycle immediately.
#[utoipa::path(
    post,
    path = "/bacnet/poll/once",
    tag = "BACnet (bench)",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Poll cycle result"))
)]
pub(crate) fn doc_bacnet_poll_once() {}

/// List all hosted server objects (device 599999).
#[utoipa::path(
    get,
    path = "/bacnet/server/objects",
    tag = "Hosted server",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Server object list"))
)]
pub(crate) fn doc_bacnet_server_objects() {}

/// Open-FDD alias for `/bacnet/server/objects`.
#[utoipa::path(
    get,
    path = "/api/bacnet/server/points",
    tag = "Hosted server",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Server object list"))
)]
pub(crate) fn doc_api_server_points() {}

/// Commandable points on the hosted server (BACnet-writable, REST read-only).
#[utoipa::path(
    get,
    path = "/bacnet/server/commandable",
    tag = "Hosted server",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Commandable server points"))
)]
pub(crate) fn doc_bacnet_server_commandable() {}

/// Update server-owned points via REST (rejects commandable points).
#[utoipa::path(
    post,
    path = "/bacnet/server/update",
    tag = "Hosted server",
    request_body = ServerUpdatePointsRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Update result"))
)]
pub(crate) fn doc_bacnet_server_update() {}

/// Cached Open-Meteo weather for the hosted server.
#[utoipa::path(
    get,
    path = "/weather",
    tag = "Weather",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Weather cache", body = WeatherResponse))
)]
pub(crate) fn doc_weather() {}

/// Force refresh weather from Open-Meteo.
#[utoipa::path(
    post,
    path = "/weather/refresh",
    tag = "Weather",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Refreshed weather"))
)]
pub(crate) fn doc_weather_refresh() {}

/// Modbus TCP read (registers specified in body).
#[utoipa::path(
    post,
    path = "/modbus/read",
    tag = "Modbus",
    request_body = ModbusReadRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Register values"))
)]
pub(crate) fn doc_modbus_read() {}

/// Haystack server metadata.
#[utoipa::path(
    get,
    path = "/haystack/about",
    tag = "Haystack",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Haystack about"))
)]
pub(crate) fn doc_haystack_about() {}

/// Haystack read by filter.
#[utoipa::path(
    post,
    path = "/haystack/read",
    tag = "Haystack",
    request_body = HaystackReadRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Haystack grid"))
)]
pub(crate) fn doc_haystack_read() {}

/// Haystack nav tree.
#[utoipa::path(
    post,
    path = "/haystack/nav",
    tag = "Haystack",
    request_body = HaystackNavRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Nav nodes"))
)]
pub(crate) fn doc_haystack_nav() {}

/// Haystack history read.
#[utoipa::path(
    post,
    path = "/haystack/his-read",
    tag = "Haystack",
    request_body = HaystackHisReadRequest,
    security(("BearerAuth" = [])),
    responses((status = 200, description = "History grid"))
)]
pub(crate) fn doc_haystack_his_read() {}

/// List configured REST/JSON devices with per-device health.
#[utoipa::path(
    get,
    path = "/rest/devices",
    tag = "REST/JSON",
    security(("BearerAuth" = [])),
    responses((status = 200, description = "Device catalog + circuit-breaker health"))
)]
pub(crate) fn doc_rest_devices() {}

/// Live read of one configured point (select + scale applied).
#[utoipa::path(
    post,
    path = "/rest/read",
    tag = "REST/JSON",
    request_body = RestReadRequest,
    security(("BearerAuth" = [])),
    responses(
        (status = 200, description = "Point value"),
        (status = 404, description = "Unknown device or point"),
        (status = 502, description = "Upstream error or circuit open")
    )
)]
pub(crate) fn doc_rest_read() {}

/// Raw passthrough GET below the device base_url (relative path only).
#[utoipa::path(
    post,
    path = "/rest/get",
    tag = "REST/JSON",
    request_body = RestGetRequest,
    security(("BearerAuth" = [])),
    responses(
        (status = 200, description = "Raw upstream response"),
        (status = 400, description = "Path must be relative")
    )
)]
pub(crate) fn doc_rest_get() {}

/// Allowlisted write — 403 unless rest.allow_write AND the binding are enabled.
#[utoipa::path(
    post,
    path = "/rest/write",
    tag = "REST/JSON",
    request_body = RestWriteRequest,
    security(("BearerAuth" = [])),
    responses(
        (status = 200, description = "Write executed"),
        (status = 403, description = "Writes disabled (fail closed)"),
        (status = 404, description = "Unknown device or write binding")
    )
)]
pub(crate) fn doc_rest_write() {}
