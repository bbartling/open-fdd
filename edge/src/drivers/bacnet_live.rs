//! Live BACnet field-bus adapter via [rusty-bacnet](https://github.com/jscott3201/rusty-bacnet).
//!
//! Used when `OPENFDD_BACNET_MODE=live`. Simulated/CI mode never calls into this module.

use bacnet_client::client::BACnetClient;
use bacnet_client::discovery::DiscoveredDevice;
use bacnet_encoding::primitives::decode_application_value;
use bacnet_transport::bip::BipTransport;
use bacnet_types::enums::{ObjectType, PropertyIdentifier};
use bacnet_types::primitives::{ObjectIdentifier, PropertyValue};
use serde_json::{json, Value};
use std::env;
use std::net::Ipv4Addr;
use std::sync::OnceLock;
use tokio::runtime::Runtime;
use tokio::time::{sleep, Duration};

static RUNTIME: OnceLock<Runtime> = OnceLock::new();

fn runtime() -> &'static Runtime {
    RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("tokio runtime for BACnet")
    })
}

pub fn block_on<F: std::future::Future>(future: F) -> F::Output {
    runtime().block_on(future)
}

pub fn is_live_mode() -> bool {
    env::var("OPENFDD_BACNET_MODE")
        .map(|v| v.eq_ignore_ascii_case("live"))
        .unwrap_or(false)
}

fn parse_bind() -> (Ipv4Addr, u16, Ipv4Addr) {
    let bind = env::var("OPENFDD_BACNET_BIND").unwrap_or_else(|_| "0.0.0.0/24:47808".to_string());
    let mut ip_part = bind.as_str();
    let mut port: u16 = 0xBAC0;
    if let Some((left, right)) = bind.rsplit_once(':') {
        if let Ok(p) = right.parse::<u16>() {
            port = p;
            ip_part = left;
        }
    }
    let ip_str = ip_part.split('/').next().unwrap_or(ip_part);
    let ip: Ipv4Addr = ip_str.parse().unwrap_or(Ipv4Addr::UNSPECIFIED);
    let octets = ip.octets();
    let bcast = Ipv4Addr::new(octets[0], octets[1], octets[2], 255);
    (ip, port, bcast)
}

fn discover_low_high() -> (u32, u32) {
    let low = env::var("OPENFDD_BACNET_DISCOVER_LOW")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(5007);
    let high = env::var("OPENFDD_BACNET_DISCOVER_HIGH")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(low);
    (low, high)
}

fn discover_timeout_secs() -> u64 {
    env::var("OPENFDD_BACNET_DISCOVER_TIMEOUT_SECS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8)
}

fn router_network() -> Option<(Ipv4Addr, u16)> {
    let router = env::var("OPENFDD_BACNET_ROUTER_IP").ok()?;
    let net = env::var("OPENFDD_BACNET_MSTP_NET")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(2000);
    let ip: Ipv4Addr = router.parse().ok()?;
    Some((ip, net))
}

async fn build_client() -> Result<BACnetClient<BipTransport>, bacnet_types::error::Error> {
    let (iface, port, bcast) = parse_bind();
    BACnetClient::bip_builder()
        .interface(iface)
        .port(port)
        .broadcast_address(bcast)
        .apdu_timeout_ms(6000)
        .build()
        .await
}

fn mac_to_address(mac: &[u8]) -> String {
    if mac.len() >= 6 {
        format!(
            "{}.{}.{}.{}:{}",
            mac[0],
            mac[1],
            mac[2],
            mac[3],
            u16::from_be_bytes([mac[4], mac[5]])
        )
    } else {
        hex::encode(mac)
    }
}

fn object_type_name(t: ObjectType) -> &'static str {
    match t {
        ObjectType::ANALOG_INPUT => "analog-input",
        ObjectType::ANALOG_OUTPUT => "analog-output",
        ObjectType::ANALOG_VALUE => "analog-value",
        ObjectType::BINARY_INPUT => "binary-input",
        ObjectType::BINARY_OUTPUT => "binary-output",
        ObjectType::BINARY_VALUE => "binary-value",
        ObjectType::MULTI_STATE_INPUT => "multi-state-input",
        ObjectType::MULTI_STATE_OUTPUT => "multi-state-output",
        ObjectType::MULTI_STATE_VALUE => "multi-state-value",
        _ => "object",
    }
}

fn object_type_code(name: &str) -> Option<ObjectType> {
    match name {
        "analog-input" => Some(ObjectType::ANALOG_INPUT),
        "analog-output" => Some(ObjectType::ANALOG_OUTPUT),
        "analog-value" => Some(ObjectType::ANALOG_VALUE),
        "binary-input" => Some(ObjectType::BINARY_INPUT),
        "binary-output" => Some(ObjectType::BINARY_OUTPUT),
        "binary-value" => Some(ObjectType::BINARY_VALUE),
        "multi-state-input" => Some(ObjectType::MULTI_STATE_INPUT),
        "multi-state-output" => Some(ObjectType::MULTI_STATE_OUTPUT),
        "multi-state-value" => Some(ObjectType::MULTI_STATE_VALUE),
        _ => None,
    }
}

fn property_value_to_json(value: &PropertyValue) -> Value {
    match value {
        PropertyValue::Null => Value::Null,
        PropertyValue::Boolean(b) => json!(*b),
        PropertyValue::Unsigned(u) => json!(*u),
        PropertyValue::Signed(i) => json!(*i),
        PropertyValue::Real(r) => json!(*r),
        PropertyValue::Double(d) => json!(*d),
        PropertyValue::OctetString(b) => json!(hex::encode(b)),
        PropertyValue::CharacterString(s) => json!(s),
        PropertyValue::BitString { unused_bits, data } => {
            json!({"unused_bits": unused_bits, "data": hex::encode(data)})
        }
        PropertyValue::Enumerated(e) => json!(*e),
        PropertyValue::Date(d) => json!(format!("{d:?}")),
        PropertyValue::Time(t) => json!(format!("{t:?}")),
        PropertyValue::ObjectIdentifier(oid) => {
            json!([oid.object_type().to_raw(), oid.instance_number()])
        }
        PropertyValue::List(items) => {
            Value::Array(items.iter().map(property_value_to_json).collect())
        }
    }
}

fn decode_value_sequence(data: &[u8]) -> Result<Vec<PropertyValue>, String> {
    if data.is_empty() {
        return Ok(Vec::new());
    }
    let (first, mut offset) = decode_application_value(data, 0).map_err(|e| e.to_string())?;
    if let PropertyValue::List(items) = first {
        return Ok(items);
    }
    let mut items = vec![first];
    while offset < data.len() {
        let (value, new_offset) =
            decode_application_value(data, offset).map_err(|e| e.to_string())?;
        if new_offset <= offset {
            break;
        }
        items.push(value);
        offset = new_offset;
    }
    Ok(items)
}

fn device_to_json(dev: &DiscoveredDevice) -> Value {
    json!({
        "object_identifier": {
            "type": "device",
            "instance": dev.object_identifier.instance_number()
        },
        "vendor_id": dev.vendor_id,
        "address": mac_to_address(dev.mac_address.as_slice()),
        "label": format!("Device {}", dev.object_identifier.instance_number()),
        "protocol": "BACnet/IP",
        "source_network": dev.source_network,
        "source_address": dev.source_address.as_ref().map(hex::encode),
        "max_apdu_length": dev.max_apdu_length
    })
}

pub async fn whois_devices() -> Result<Vec<Value>, String> {
    let (low, high) = discover_low_high();
    let timeout = discover_timeout_secs();
    let mut client = build_client().await.map_err(|e| e.to_string())?;

    client
        .who_is(Some(low), Some(high))
        .await
        .map_err(|e| e.to_string())?;

    if let Some((_router_ip, mstp_net)) = router_network() {
        client
            .who_is_network(mstp_net, Some(low), Some(high))
            .await
            .map_err(|e| e.to_string())?;
    }

    sleep(Duration::from_secs(timeout)).await;
    let devices = client.discovered_devices().await;
    let _ = client.stop().await;
    Ok(devices.iter().map(device_to_json).collect())
}

pub async fn read_present_value(
    device_instance: u32,
    object_type: ObjectType,
    instance: u32,
) -> Result<Value, String> {
    let mut client = build_client().await.map_err(|e| e.to_string())?;
    let (low, high) = discover_low_high();
    client
        .who_is(Some(low), Some(high))
        .await
        .map_err(|e| e.to_string())?;
    if let Some((_, mstp_net)) = router_network() {
        let _ = client.who_is_network(mstp_net, Some(low), Some(high)).await;
    }
    sleep(Duration::from_secs(2)).await;

    let oid = ObjectIdentifier::new(object_type, instance).map_err(|e| e.to_string())?;
    let ack = client
        .read_property_from_device(
            device_instance,
            oid,
            PropertyIdentifier::PRESENT_VALUE,
            None,
        )
        .await
        .map_err(|e| e.to_string())?;
    let (value, _) = decode_application_value(&ack.property_value, 0).map_err(|e| e.to_string())?;
    let out = json!({
        "device_instance": device_instance,
        "object_id": [object_type.to_raw(), instance],
        "value": property_value_to_json(&value),
        "source": "rusty-bacnet"
    });
    let _ = client.stop().await;
    Ok(out)
}

pub async fn read_priority_array(
    device_instance: u32,
    object_type: ObjectType,
    instance: u32,
) -> Result<Vec<(u8, Value)>, String> {
    let mut client = build_client().await.map_err(|e| e.to_string())?;
    let (low, high) = discover_low_high();
    client
        .who_is(Some(low), Some(high))
        .await
        .map_err(|e| e.to_string())?;
    if let Some((_, mstp_net)) = router_network() {
        let _ = client.who_is_network(mstp_net, Some(low), Some(high)).await;
    }
    sleep(Duration::from_secs(2)).await;

    let oid = ObjectIdentifier::new(object_type, instance).map_err(|e| e.to_string())?;
    let ack = client
        .read_property_from_device(
            device_instance,
            oid,
            PropertyIdentifier::PRIORITY_ARRAY,
            None,
        )
        .await
        .map_err(|e| e.to_string())?;
    let items = decode_value_sequence(&ack.property_value)?;

    let mut out = Vec::new();
    for (idx, item) in items.iter().enumerate() {
        // BACnet priority array: priority levels 1–16 map to sequence indices 0–15.
        let priority = (idx + 1) as u8;
        if priority > 16 {
            continue;
        }
        if !matches!(item, PropertyValue::Null) {
            out.push((priority, property_value_to_json(item)));
        }
    }
    let _ = client.stop().await;
    Ok(out)
}

pub async fn discover_device_points(device_instance: u32) -> Result<Vec<Value>, String> {
    let mut client = build_client().await.map_err(|e| e.to_string())?;
    let (low, high) = discover_low_high();
    client
        .who_is(Some(low), Some(high))
        .await
        .map_err(|e| e.to_string())?;
    if let Some((_, mstp_net)) = router_network() {
        client
            .who_is_network(mstp_net, Some(low), Some(high))
            .await
            .map_err(|e| e.to_string())?;
    }
    sleep(Duration::from_secs(discover_timeout_secs())).await;

    let dev = client
        .get_device(device_instance)
        .await
        .ok_or_else(|| format!("device {device_instance} not discovered"))?;

    let device_oid =
        ObjectIdentifier::new(ObjectType::DEVICE, device_instance).map_err(|e| e.to_string())?;
    let list_ack = client
        .read_property_from_device(
            device_instance,
            device_oid,
            PropertyIdentifier::OBJECT_LIST,
            None,
        )
        .await
        .map_err(|e| e.to_string())?;
    let list_items = decode_value_sequence(&list_ack.property_value)?;

    let mut points = Vec::new();
    for item in list_items {
        let oid = match item {
            PropertyValue::ObjectIdentifier(o) => o,
            _ => continue,
        };
        if oid.object_type() == ObjectType::DEVICE {
            continue;
        }

        let name_ack = client
            .read_property_from_device(device_instance, oid, PropertyIdentifier::OBJECT_NAME, None)
            .await;
        let pv_ack = client
            .read_property_from_device(
                device_instance,
                oid,
                PropertyIdentifier::PRESENT_VALUE,
                None,
            )
            .await;
        let wp_ack = client
            .read_property_from_device(device_instance, oid, PropertyIdentifier::OBJECT_TYPE, None)
            .await;

        let name = name_ack
            .ok()
            .and_then(|a| decode_application_value(&a.property_value, 0).ok())
            .map(|(v, _)| match v {
                PropertyValue::CharacterString(s) => s,
                other => format!("{other:?}"),
            })
            .unwrap_or_else(|| {
                format!(
                    "{}:{}",
                    object_type_name(oid.object_type()),
                    oid.instance_number()
                )
            });

        let value = pv_ack
            .ok()
            .and_then(|a| decode_application_value(&a.property_value, 0).ok())
            .map(|(v, _)| property_value_to_json(&v));

        let writable = matches!(
            oid.object_type(),
            ObjectType::ANALOG_VALUE
                | ObjectType::ANALOG_OUTPUT
                | ObjectType::BINARY_VALUE
                | ObjectType::BINARY_OUTPUT
                | ObjectType::MULTI_STATE_VALUE
                | ObjectType::MULTI_STATE_OUTPUT
        ) || wp_ack.is_ok();

        points.push(json!({
            "id": format!("bacnet:{}:{}:{}", device_instance, object_type_name(oid.object_type()), oid.instance_number()),
            "device_instance": device_instance,
            "object_id": [oid.object_type().to_raw(), oid.instance_number()],
            "name": name,
            "polling_enabled": true,
            "writable": writable,
            "present_value": value,
            "address": mac_to_address(dev.mac_address.as_slice()),
            "source_network": dev.source_network,
        }));
    }

    let _ = client.stop().await;
    Ok(points)
}

pub fn point_object_from_json(point: &Value) -> Option<(u32, ObjectType, u32)> {
    let device_instance = point.get("device_instance")?.as_u64()? as u32;
    let arr = point.get("object_id")?.as_array()?;
    if arr.len() < 2 {
        return None;
    }
    let type_code = arr[0].as_u64()? as u16;
    let instance = arr[1].as_u64()? as u32;
    let object_type = ObjectType::from_raw(type_code as u32);
    Some((device_instance, object_type, instance))
}

pub fn point_object_from_id(point_id: &str) -> Option<(u32, ObjectType, u32)> {
    // bacnet:5007:analog-input:1173
    let parts: Vec<&str> = point_id.split(':').collect();
    if parts.len() != 4 || parts[0] != "bacnet" {
        return None;
    }
    let device_instance = parts[1].parse().ok()?;
    let object_type = object_type_code(parts[2])?;
    let instance = parts[3].parse().ok()?;
    Some((device_instance, object_type, instance))
}
