//! Live Modbus/TCP adapter via [rusty-modbus](https://github.com/jscott3201/rusty-modbus).

use rusty_modbus_client::client::ModbusClient;
use rusty_modbus_client::config::ClientConfig;
use rusty_modbus_types::UnitId;
use serde_json::{json, Value};
use std::env;
use std::net::ToSocketAddrs;
use std::sync::OnceLock;
use std::time::Duration;
use tokio::runtime::Runtime;

static RUNTIME: OnceLock<Runtime> = OnceLock::new();

fn runtime() -> &'static Runtime {
    RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("tokio runtime for Modbus")
    })
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    runtime().block_on(future)
}

pub fn is_live_mode() -> bool {
    env::var("OPENFDD_MODBUS_MODE")
        .map(|v| !v.eq_ignore_ascii_case("simulated"))
        .unwrap_or(true)
}

pub fn host_port() -> Result<(String, u16), String> {
    let profile = crate::validation::profile::active_profile();
    if crate::validation::profile::is_modbus_configured(&profile) {
        return Ok((profile.modbus_host.clone(), profile.modbus_port));
    }
    let host = env::var("OPENFDD_MODBUS_HOST")
        .map_err(|_| "OPENFDD_MODBUS_HOST not configured".to_string())?;
    if host.trim().is_empty() {
        return Err("OPENFDD_MODBUS_HOST not configured".to_string());
    }
    let port = env::var("OPENFDD_MODBUS_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(1502);
    Ok((host, port))
}

pub fn unit_id() -> u8 {
    env::var("OPENFDD_MODBUS_UNIT_ID")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(1)
}

pub fn timeout_ms() -> u64 {
    env::var("OPENFDD_MODBUS_TIMEOUT_MS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(3000)
}

fn modbus_address(register: u16, function: &str) -> Result<u16, String> {
    match function {
        "holding_register" => {
            if register >= 40001 {
                Ok(register - 40001)
            } else {
                Ok(register)
            }
        }
        "input_register" => {
            if register >= 30001 {
                Ok(register - 30001)
            } else {
                Ok(register)
            }
        }
        other => Err(format!("unsupported modbus function: {other}")),
    }
}

async fn connect_client(host: &str, port: u16) -> Result<ModbusClient, String> {
    let addr = format!("{host}:{port}")
        .to_socket_addrs()
        .map_err(|e| format!("resolve {host}:{port}: {e}"))?
        .next()
        .ok_or_else(|| format!("no address for {host}:{port}"))?;
    let config = ClientConfig {
        unit_id: UnitId(unit_id()),
        timeout: Duration::from_millis(timeout_ms()),
        ..Default::default()
    };
    ModbusClient::connect(addr, config)
        .await
        .map_err(|e| format!("connect {host}:{port}: {e}"))
}

async fn read_registers_async(
    host: &str,
    port: u16,
    function: &str,
    address: u16,
    count: u16,
) -> Result<Vec<u16>, String> {
    let client = connect_client(host, port).await?;
    let uid = UnitId(unit_id());
    match function {
        "holding_register" => client
            .read_holding_registers(uid, address, count)
            .await
            .map_err(|e| format!("read holding {address}: {e}")),
        "input_register" => client
            .read_input_registers(uid, address, count)
            .await
            .map_err(|e| format!("read input {address}: {e}")),
        other => Err(format!("unsupported modbus function: {other}")),
    }
}

fn read_registers(
    host: &str,
    port: u16,
    function: &str,
    address: u16,
    count: u16,
) -> Result<Vec<u16>, String> {
    block_on(read_registers_async(host, port, function, address, count))
}

pub fn read_register(register: u16, function: &str) -> Result<Value, String> {
    let (host, port) = host_port()?;
    let address = modbus_address(register, function)?;
    let values = read_registers(&host, port, function, address, 1)?;
    let raw = values.first().copied().unwrap_or(0);
    Ok(json!({
        "ok": true,
        "host": host,
        "port": port,
        "unit_id": unit_id(),
        "register": register,
        "function": function,
        "raw": raw,
        "value": raw,
        "source": "rusty-modbus"
    }))
}

pub fn read_scaled_register(
    register: u16,
    function: &str,
    scale: f64,
    unit_label: &str,
) -> Result<Value, String> {
    let mut out = read_register(register, function)?;
    if let Some(obj) = out.as_object_mut() {
        let raw = obj.get("raw").and_then(|v| v.as_u64()).unwrap_or(0) as f64;
        let scaled = raw * scale;
        obj.insert("value".to_string(), json!(scaled));
        obj.insert("unit".to_string(), json!(unit_label));
    }
    Ok(out)
}

pub fn scan_device() -> Result<Value, String> {
    let (host, port) = host_port()?;
    let unit = unit_id();
    let holding = read_registers(&host, port, "holding_register", 0, 6)?;
    let input = read_registers(&host, port, "input_register", 0, 4)?;

    let points = vec![
        json!({
            "id": format!("modbus:tcp:{unit}:40001"),
            "name": "RPi Temp °F",
            "register": 40001,
            "function": "holding_register",
            "raw": holding.first().copied().unwrap_or(0),
            "value": holding.first().copied().unwrap_or(0) as f64 / 10.0,
            "unit": "°F",
            "address": format!("{host}:{port}"),
            "unit_id": unit
        }),
        json!({
            "id": format!("modbus:tcp:{unit}:40002"),
            "name": "RPi Temp °C",
            "register": 40002,
            "function": "holding_register",
            "raw": holding.get(1).copied().unwrap_or(0),
            "value": holding.get(1).copied().unwrap_or(0) as f64 / 10.0,
            "unit": "°C",
            "address": format!("{host}:{port}"),
            "unit_id": unit
        }),
        json!({
            "id": format!("modbus:tcp:{unit}:40003"),
            "name": "RPi Setpoint °F",
            "register": 40003,
            "function": "holding_register",
            "writable": true,
            "raw": holding.get(2).copied().unwrap_or(0),
            "value": holding.get(2).copied().unwrap_or(0) as f64 / 10.0,
            "unit": "°F",
            "address": format!("{host}:{port}"),
            "unit_id": unit
        }),
        json!({
            "id": format!("modbus:tcp:{unit}:30003"),
            "name": "RPi Humidity",
            "register": 30003,
            "function": "input_register",
            "raw": input.get(2).copied().unwrap_or(0),
            "value": input.get(2).copied().unwrap_or(0) as f64 / 10.0,
            "unit": "%RH",
            "address": format!("{host}:{port}"),
            "unit_id": unit
        }),
    ];

    Ok(json!({
        "ok": true,
        "devices": [{
            "unit_id": unit,
            "address": format!("{host}:{port}"),
            "name": "RPi Modbus Temp Sensor",
            "protocol": "modbus/tcp"
        }],
        "points": points,
        "source": "rusty-modbus"
    }))
}

pub fn parse_point_id(point_id: &str) -> Option<(u8, u16, String)> {
    let parts: Vec<&str> = point_id.split(':').collect();
    if parts.len() != 4 || parts[0] != "modbus" || parts[1] != "tcp" {
        return None;
    }
    let unit = parts[2].parse().ok()?;
    let register = parts[3].parse().ok()?;
    let function = if (30001..40001).contains(&register) {
        "input_register".to_string()
    } else {
        "holding_register".to_string()
    };
    Some((unit, register, function))
}
