//! Live Modbus/TCP adapter for bench devices (e.g. RPi temp sensor on :1502).

use serde_json::{json, Value};
use std::env;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

const FC_READ_HOLDING: u8 = 3;
const FC_READ_INPUT: u8 = 4;

pub fn is_live_mode() -> bool {
    env::var("OPENFDD_MODBUS_MODE")
        .map(|v| v.eq_ignore_ascii_case("live"))
        .unwrap_or(false)
}

pub fn host_port() -> (String, u16) {
    let host = env::var("OPENFDD_MODBUS_HOST").unwrap_or_else(|_| "192.168.204.14".to_string());
    let port = env::var("OPENFDD_MODBUS_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(1502);
    (host, port)
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

fn read_registers(
    host: &str,
    port: u16,
    unit: u8,
    fc: u8,
    address: u16,
    count: u16,
) -> Result<Vec<u16>, String> {
    let mut stream = TcpStream::connect(format!("{host}:{port}"))
        .map_err(|e| format!("connect {host}:{port}: {e}"))?;
    stream
        .set_read_timeout(Some(Duration::from_millis(timeout_ms())))
        .map_err(|e| e.to_string())?;
    stream
        .set_write_timeout(Some(Duration::from_millis(timeout_ms())))
        .map_err(|e| e.to_string())?;

    let pdu = [
        fc,
        (address >> 8) as u8,
        (address & 0xFF) as u8,
        (count >> 8) as u8,
        (count & 0xFF) as u8,
    ];
    let header = [
        0x00,
        0x01, // transaction id
        0x00,
        0x00, // protocol id
        0x00,
        (pdu.len() as u8 + 1), // length
        unit,
    ];
    stream
        .write_all(&header)
        .and_then(|_| stream.write_all(&pdu))
        .map_err(|e| format!("write: {e}"))?;

    let mut resp = [0_u8; 256];
    let n = stream.read(&mut resp).map_err(|e| format!("read: {e}"))?;
    if n < 9 {
        return Err(format!("short modbus response ({n} bytes)"));
    }

    let resp_unit = resp[6];
    if resp_unit != unit {
        return Err(format!("unexpected unit id {resp_unit}"));
    }
    let resp_fc = resp[7];
    if resp_fc & 0x80 != 0 {
        return Err(format!("modbus exception fc=0x{resp_fc:02x} code={}", resp[8]));
    }
    if resp_fc != fc {
        return Err(format!("unexpected function code {resp_fc}"));
    }

    let byte_count = resp[8] as usize;
    if 9 + byte_count > n {
        return Err("truncated modbus payload".to_string());
    }

    let mut values = Vec::with_capacity(count as usize);
    for i in 0..count as usize {
        let off = 9 + i * 2;
        values.push(u16::from_be_bytes([resp[off], resp[off + 1]]));
    }
    Ok(values)
}

pub fn read_register(register: u16, function: &str) -> Result<Value, String> {
    let (host, port) = host_port();
    let unit = unit_id();
    let address = modbus_address(register, function)?;
    let fc = match function {
        "holding_register" => FC_READ_HOLDING,
        "input_register" => FC_READ_INPUT,
        _ => return Err(format!("unsupported function: {function}")),
    };
    let values = read_registers(&host, port, unit, fc, address, 1)?;
    let raw = values.first().copied().unwrap_or(0);
    Ok(json!({
        "ok": true,
        "host": host,
        "port": port,
        "unit_id": unit,
        "register": register,
        "function": function,
        "raw": raw,
        "value": raw,
        "source": "modbus-tcp-live"
    }))
}

pub fn read_scaled_register(register: u16, function: &str, scale: f64, unit_label: &str) -> Result<Value, String> {
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
    let (host, port) = host_port();
    let unit = unit_id();
    let holding = read_registers(&host, port, unit, FC_READ_HOLDING, 0, 6)?;
    let input = read_registers(&host, port, unit, FC_READ_INPUT, 0, 4)?;

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
        "source": "modbus-tcp-live"
    }))
}

pub fn parse_point_id(point_id: &str) -> Option<(u8, u16, String)> {
    // modbus:tcp:1:40001
    let parts: Vec<&str> = point_id.split(':').collect();
    if parts.len() != 4 || parts[0] != "modbus" || parts[1] != "tcp" {
        return None;
    }
    let unit = parts[2].parse().ok()?;
    let register = parts[3].parse().ok()?;
    let function = if register >= 30001 && register < 40001 {
        "input_register".to_string()
    } else {
        "holding_register".to_string()
    };
    Some((unit, register, function))
}
