//! Modbus TCP client (mirrors `app/modbus_client.py`).

use std::net::SocketAddr;
use std::time::Duration;

use rusty_modbus_client::{ClientConfig, ModbusClient};
use rusty_modbus_types::UnitId;
use serde_json::{json, Value};

const MAX_REGS_PER_OPERATION: u16 = 125;
const MAX_OPERATIONS_PER_REQUEST: usize = 32;

#[derive(Debug)]
pub struct ModbusServiceError(pub String);

impl std::fmt::Display for ModbusServiceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for ModbusServiceError {}

pub async fn execute_modbus_read(payload: &Value) -> Result<Value, ModbusServiceError> {
    let host = payload["host"]
        .as_str()
        .ok_or_else(|| ModbusServiceError("host required".into()))?
        .trim()
        .to_string();
    if host.is_empty() {
        return Err(ModbusServiceError("host must be non-empty".into()));
    }
    let port = payload["port"].as_u64().unwrap_or(502) as u16;
    let unit_id = payload["unit_id"].as_u64().unwrap_or(1) as u8;
    let timeout = payload["timeout"].as_f64().unwrap_or(5.0);
    let registers = payload["registers"]
        .as_array()
        .ok_or_else(|| ModbusServiceError("registers required".into()))?;

    if registers.len() > MAX_OPERATIONS_PER_REQUEST {
        return Err(ModbusServiceError(format!(
            "At most {MAX_OPERATIONS_PER_REQUEST} operations per request"
        )));
    }

    let addr: SocketAddr = format!("{host}:{port}")
        .parse()
        .map_err(|e| ModbusServiceError(format!("bad host:port: {e}")))?;

    let config = ClientConfig {
        timeout: Duration::from_secs_f64(timeout),
        ..ClientConfig::default()
    };
    let client = ModbusClient::connect(addr, config)
        .await
        .map_err(|e| ModbusServiceError(e.to_string()))?;

    let mut readings = Vec::new();
    for spec in registers {
        let address = spec["address"].as_u64().unwrap_or(0) as u16;
        let count = spec["count"].as_u64().unwrap_or(1) as u16;
        let function = spec["function"].as_str().unwrap_or("holding");
        let decode = spec["decode"].as_str();
        let scale = spec["scale"].as_f64();
        let offset = spec["offset"].as_f64();
        let label = spec["label"].clone();

        if !(1..=MAX_REGS_PER_OPERATION).contains(&count) {
            return Err(ModbusServiceError(format!(
                "count must be 1..{MAX_REGS_PER_OPERATION}"
            )));
        }
        if matches!(decode, Some("float32" | "uint32" | "int32")) && count < 2 {
            return Err(ModbusServiceError(format!(
                "decode={decode:?} requires count >= 2"
            )));
        }

        let result = async {
            let words = match function {
                "holding" => client
                    .read_holding_registers(UnitId(unit_id), address, count)
                    .await
                    .map_err(|e| ModbusServiceError(e.to_string()))?,
                "input" => client
                    .read_input_registers(UnitId(unit_id), address, count)
                    .await
                    .map_err(|e| ModbusServiceError(e.to_string()))?,
                other => return Err(ModbusServiceError(format!("Invalid function: {other}"))),
            };
            let words_list: Vec<u16> = words.to_vec();
            let decoded = decode_words(&words_list, decode)?;
            let decoded = apply_scale_offset(decoded, scale, offset);
            Ok(json!({
                "address": address,
                "function": function,
                "count": count,
                "success": true,
                "words": words_list,
                "decoded": decoded,
                "label": label,
                "error": Value::Null,
            }))
        }
        .await;

        match result {
            Ok(row) => readings.push(row),
            Err(e) => readings.push(json!({
                "address": address,
                "function": function,
                "count": count,
                "success": false,
                "words": Value::Null,
                "decoded": Value::Null,
                "label": label,
                "error": e.to_string(),
            })),
        }
    }

    client.shutdown().await;

    Ok(json!({
        "ok": true,
        "host": host,
        "port": port,
        "unit_id": unit_id,
        "timeout": timeout,
        "readings": readings,
    }))
}

fn decode_words(words: &[u16], decode: Option<&str>) -> Result<Option<Value>, ModbusServiceError> {
    let decode = match decode {
        None | Some("raw") => return Ok(None),
        Some(d) => d,
    };
    if words.is_empty() {
        return Err(ModbusServiceError("No register words to decode".into()));
    }
    match decode {
        "uint16" => Ok(Some(json!(words[0]))),
        "int16" => Ok(Some(json!((words[0] as i16)))),
        "uint32" | "int32" | "float32" => {
            if words.len() < 2 {
                return Err(ModbusServiceError(format!("{decode} needs count >= 2")));
            }
            let hi = words[0] as u32;
            let lo = words[1] as u32;
            let packed = (hi << 16) | lo;
            match decode {
                "uint32" => Ok(Some(json!(packed))),
                "int32" => Ok(Some(json!(packed as i32))),
                "float32" => Ok(Some(json!(f32::from_bits(packed)))),
                _ => unreachable!(),
            }
        }
        other => Err(ModbusServiceError(format!("Unknown decode: {other}"))),
    }
}

fn apply_scale_offset(
    value: Option<Value>,
    scale: Option<f64>,
    offset: Option<f64>,
) -> Option<Value> {
    let v = value?;
    let n = v.as_f64().or_else(|| v.as_i64().map(|i| i as f64))?;
    let mut out = n;
    if let Some(s) = scale {
        out *= s;
    }
    if let Some(o) = offset {
        out += o;
    }
    Some(json!(out))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decode_uint16() {
        assert_eq!(
            decode_words(&[0x00FF], Some("uint16")).unwrap(),
            Some(json!(255))
        );
    }

    #[test]
    fn decode_float32() {
        let words = [0x4248, 0x0000]; // 50.0
        let v = decode_words(&words, Some("float32")).unwrap().unwrap();
        assert!((v.as_f64().unwrap() - 50.0).abs() < 0.01);
    }

    #[test]
    fn scale_offset() {
        assert_eq!(
            apply_scale_offset(Some(serde_json::json!(10)), Some(0.1), Some(1.0)),
            Some(serde_json::json!(2.0))
        );
    }
}
