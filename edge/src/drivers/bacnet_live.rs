//! Live BACnet field-bus adapter via [rusty-bacnet](https://github.com/jscott3201/rusty-bacnet).
//!
//! Used when `OPENFDD_BACNET_MODE=live`. Simulated/CI mode never calls into this module.

use bacnet_client::client::BACnetClient;
use bacnet_client::discovery::DiscoveredDevice;
use bacnet_encoding::primitives::{decode_application_value, encode_property_value};
use bacnet_services::common::PropertyReference;
use bacnet_services::rpm::ReadAccessSpecification;
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
        .unwrap_or(true)
}

fn client_bind_port() -> u16 {
    if let Ok(v) = env::var("OPENFDD_BACNET_CLIENT_PORT") {
        if let Ok(p) = v.parse::<u16>() {
            return p;
        }
    }
    let server_on = env::var("OPENFDD_BACNET_SERVER_ENABLED")
        .map(|v| v != "0" && !v.eq_ignore_ascii_case("false"))
        .unwrap_or_else(|_| {
            env::var("OPENFDD_BACNET_ENABLED")
                .map(|v| v != "0" && !v.eq_ignore_ascii_case("false"))
                .unwrap_or(true)
        });
    if server_on {
        0
    } else {
        0xBAC0
    }
}

fn parse_bind() -> (Ipv4Addr, u16, Ipv4Addr) {
    let bind = env::var("OPENFDD_BACNET_BIND").unwrap_or_else(|_| "0.0.0.0/24:47808".to_string());
    let mut ip_part = bind.as_str();
    let mut port: u16 = client_bind_port();
    if port == 0 {
        // Ephemeral client port when local BACnet server owns :47808.
    } else if let Some((left, right)) = bind.rsplit_once(':') {
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
    if let (Ok(low_s), Ok(high_s)) = (
        env::var("OPENFDD_BACNET_DISCOVER_LOW"),
        env::var("OPENFDD_BACNET_DISCOVER_HIGH"),
    ) {
        if let (Ok(low), Ok(high)) = (low_s.parse::<u32>(), high_s.parse::<u32>()) {
            return (low, high);
        }
    }
    let profile = crate::validation::profile::active_profile();
    let field = profile.device_instance;
    let local = super::bacnet_server::device_instance();
    let mut low = if field > 0 { field } else { 0 };
    let mut high = if field > 0 { field } else { 0 };
    if local > 0 {
        low = low.min(local);
        high = high.max(local);
    }
    if low == 0 && high == 0 {
        (0, 4_194_303)
    } else {
        (low, high)
    }
}

fn server_udp_port() -> u16 {
    env::var("OPENFDD_BACNET_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(47808)
}

fn local_server_bip_mac() -> Vec<u8> {
    let (iface, _, _) = parse_bind();
    let ip = if iface == Ipv4Addr::UNSPECIFIED {
        Ipv4Addr::LOCALHOST
    } else {
        iface
    };
    let port = server_udp_port();
    let mut mac = Vec::with_capacity(6);
    mac.extend_from_slice(&ip.octets());
    mac.extend_from_slice(&port.to_be_bytes());
    mac
}

async fn run_whois(
    client: &mut BACnetClient<BipTransport>,
    low: u32,
    high: u32,
) -> Result<(), String> {
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
    Ok(())
}

async fn prepare_device_for_read(
    client: &mut BACnetClient<BipTransport>,
    device_instance: u32,
) -> Result<(), String> {
    let local = super::bacnet_server::device_instance();
    if device_instance == local {
        if client.get_device(local).await.is_none() {
            let mac = local_server_bip_mac();
            client
                .add_device(local, &mac)
                .await
                .map_err(|e| e.to_string())?;
        }
        return Ok(());
    }
    let (mut low, mut high) = discover_low_high();
    if device_instance > 0 {
        low = low.min(device_instance);
        high = high.max(device_instance);
    }
    run_whois(client, low, high).await?;
    sleep(Duration::from_secs(2)).await;
    Ok(())
}

async fn stop_client(mut client: BACnetClient<BipTransport>) {
    let _ = client.stop().await;
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

pub async fn whois_devices_with_range(
    low: Option<u32>,
    high: Option<u32>,
) -> Result<Vec<Value>, String> {
    let (default_low, default_high) = discover_low_high();
    let low = low.unwrap_or(default_low);
    let high = high.unwrap_or(default_high);
    let mut client = build_client().await.map_err(|e| e.to_string())?;
    let result = async {
        run_whois(&mut client, low, high).await?;
        sleep(Duration::from_secs(discover_timeout_secs())).await;
        let devices = client.discovered_devices().await;
        Ok(devices.iter().map(device_to_json).collect())
    }
    .await;
    stop_client(client).await;
    result
}

pub async fn whois_devices() -> Result<Vec<Value>, String> {
    whois_devices_with_range(None, None).await
}

pub async fn read_present_value(
    device_instance: u32,
    object_type: ObjectType,
    instance: u32,
) -> Result<Value, String> {
    let mut client = build_client().await.map_err(|e| e.to_string())?;
    let result = async {
        prepare_device_for_read(&mut client, device_instance).await?;

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
        let (value, _) =
            decode_application_value(&ack.property_value, 0).map_err(|e| e.to_string())?;
        Ok(json!({
            "device_instance": device_instance,
            "object_id": [object_type.to_raw(), instance],
            "value": property_value_to_json(&value),
            "source": "rusty-bacnet"
        }))
    }
    .await;
    stop_client(client).await;
    result
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
    // bacnet:<device>:analog-input:<instance>
    let parts: Vec<&str> = point_id.split(':').collect();
    if parts.len() != 4 || parts[0] != "bacnet" {
        return None;
    }
    let device_instance = parts[1].parse().ok()?;
    let object_type = object_type_code(parts[2])?;
    let instance = parts[3].parse().ok()?;
    Some((device_instance, object_type, instance))
}

fn decode_prop(bytes: &[u8]) -> Option<PropertyValue> {
    decode_application_value(bytes, 0).ok().map(|(v, _)| v)
}

pub async fn discover_device_points_rpm(device_instance: u32) -> Result<Vec<Value>, String> {
    let mut client = build_client().await.map_err(|e| e.to_string())?;
    let (low, high) = discover_low_high();
    client
        .who_is(Some(low), Some(high))
        .await
        .map_err(|e| e.to_string())?;
    if let Some((_, mstp_net)) = router_network() {
        let _ = client.who_is_network(mstp_net, Some(low), Some(high)).await;
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

    let object_ids: Vec<ObjectIdentifier> = list_items
        .into_iter()
        .filter_map(|item| match item {
            PropertyValue::ObjectIdentifier(o) if o.object_type() != ObjectType::DEVICE => Some(o),
            _ => None,
        })
        .collect();

    if object_ids.is_empty() {
        let _ = client.stop().await;
        return Ok(Vec::new());
    }

    let specs: Vec<ReadAccessSpecification> = object_ids
        .iter()
        .map(|oid| ReadAccessSpecification {
            object_identifier: *oid,
            list_of_property_references: vec![
                PropertyReference {
                    property_identifier: PropertyIdentifier::OBJECT_NAME,
                    property_array_index: None,
                },
                PropertyReference {
                    property_identifier: PropertyIdentifier::PRESENT_VALUE,
                    property_array_index: None,
                },
                PropertyReference {
                    property_identifier: PropertyIdentifier::OBJECT_TYPE,
                    property_array_index: None,
                },
            ],
        })
        .collect();

    let rpm = client
        .read_property_multiple_from_device(device_instance, specs)
        .await
        .map_err(|e| e.to_string())?;

    let mut points = Vec::new();
    for result in rpm.list_of_read_access_results {
        let oid = result.object_identifier;
        let mut name = format!(
            "{}:{}",
            object_type_name(oid.object_type()),
            oid.instance_number()
        );
        let mut value: Option<Value> = None;
        for prop in result.list_of_results {
            if prop.error.is_some() {
                continue;
            }
            let Some(bytes) = prop.property_value.as_ref() else {
                continue;
            };
            let Some(val) = decode_prop(bytes) else {
                continue;
            };
            match prop.property_identifier {
                PropertyIdentifier::OBJECT_NAME => {
                    if let PropertyValue::CharacterString(s) = val {
                        name = s;
                    }
                }
                PropertyIdentifier::PRESENT_VALUE => {
                    value = Some(property_value_to_json(&val));
                }
                _ => {}
            }
        }
        let writable = matches!(
            oid.object_type(),
            ObjectType::ANALOG_VALUE
                | ObjectType::ANALOG_OUTPUT
                | ObjectType::BINARY_VALUE
                | ObjectType::BINARY_OUTPUT
                | ObjectType::MULTI_STATE_VALUE
                | ObjectType::MULTI_STATE_OUTPUT
        );
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
            "read_method": "ReadPropertyMultiple"
        }));
    }

    let _ = client.stop().await;
    Ok(points)
}

fn priority_slots_from_bytes(data: &[u8]) -> Result<Vec<(u8, Value)>, String> {
    let items = decode_value_sequence(data)?;
    let mut out = Vec::new();
    for (idx, item) in items.iter().enumerate() {
        let priority = (idx + 1) as u8;
        if priority > 16 {
            continue;
        }
        if !matches!(item, PropertyValue::Null) {
            out.push((priority, property_value_to_json(item)));
        }
    }
    Ok(out)
}

pub async fn read_priority_arrays_rpm(
    device_instance: u32,
    objects: &[(ObjectType, u32)],
) -> Result<std::collections::HashMap<(ObjectType, u32), Vec<(u8, Value)>>, String> {
    if objects.is_empty() {
        return Ok(std::collections::HashMap::new());
    }
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

    let specs: Vec<ReadAccessSpecification> = objects
        .iter()
        .filter_map(|(object_type, instance)| {
            ObjectIdentifier::new(*object_type, *instance)
                .ok()
                .map(|oid| ReadAccessSpecification {
                    object_identifier: oid,
                    list_of_property_references: vec![PropertyReference {
                        property_identifier: PropertyIdentifier::PRIORITY_ARRAY,
                        property_array_index: None,
                    }],
                })
        })
        .collect();

    let rpm = client
        .read_property_multiple_from_device(device_instance, specs)
        .await
        .map_err(|e| e.to_string())?;

    let mut out = std::collections::HashMap::new();
    for result in rpm.list_of_read_access_results {
        let ot = result.object_identifier.object_type();
        let inst = result.object_identifier.instance_number();
        for prop in result.list_of_results {
            if prop.error.is_some() {
                continue;
            }
            let Some(bytes) = prop.property_value.as_ref() else {
                continue;
            };
            if prop.property_identifier != PropertyIdentifier::PRIORITY_ARRAY {
                continue;
            }
            if let Ok(slots) = priority_slots_from_bytes(bytes) {
                out.insert((ot, inst), slots);
            }
        }
    }
    let _ = client.stop().await;
    Ok(out)
}

pub async fn poll_present_values_rpm(
    device_instance: u32,
    objects: &[(ObjectType, u32)],
) -> Result<Vec<Value>, String> {
    if objects.is_empty() {
        return Ok(Vec::new());
    }
    let objects = objects.to_vec();
    let mut client = build_client().await.map_err(|e| e.to_string())?;
    let result = async {
        prepare_device_for_read(&mut client, device_instance).await?;

        let specs: Vec<ReadAccessSpecification> = objects
            .iter()
            .filter_map(|(object_type, instance)| {
                ObjectIdentifier::new(*object_type, *instance)
                    .ok()
                    .map(|oid| ReadAccessSpecification {
                        object_identifier: oid,
                        list_of_property_references: vec![PropertyReference {
                            property_identifier: PropertyIdentifier::PRESENT_VALUE,
                            property_array_index: None,
                        }],
                    })
            })
            .collect();

        let rpm = client
            .read_property_multiple_from_device(device_instance, specs)
            .await
            .map_err(|e| e.to_string())?;

        let mut samples = Vec::new();
        let at = chrono::Utc::now().to_rfc3339();
        for result in rpm.list_of_read_access_results {
            let ot = result.object_identifier.object_type();
            let inst = result.object_identifier.instance_number();
            let mut value = Value::Null;
            for prop in result.list_of_results {
                if prop.error.is_some() {
                    continue;
                }
                let Some(bytes) = prop.property_value.as_ref() else {
                    continue;
                };
                if let Some(val) = decode_prop(bytes) {
                    value = property_value_to_json(&val);
                }
            }
            samples.push(json!({
                "device_instance": device_instance,
                "object_id": [ot.to_raw(), inst],
                "id": format!("bacnet:{}:{}:{}", device_instance, object_type_name(ot), inst),
                "present_value": value,
                "last_read_at": at,
                "read_method": "ReadPropertyMultiple"
            }));
        }
        Ok(samples)
    }
    .await;
    stop_client(client).await;
    result
}

pub async fn write_present_value(
    device_instance: u32,
    object_type: ObjectType,
    instance: u32,
    value: &PropertyValue,
    priority: Option<u8>,
) -> Result<Value, String> {
    let mut client = build_client().await.map_err(|e| e.to_string())?;
    let (low, high) = discover_low_high();
    client
        .who_is(Some(low), Some(high))
        .await
        .map_err(|e| e.to_string())?;
    sleep(Duration::from_secs(2)).await;

    let oid = ObjectIdentifier::new(object_type, instance).map_err(|e| e.to_string())?;
    let mut buf = bytes::BytesMut::new();
    encode_property_value(&mut buf, value).map_err(|e| e.to_string())?;
    client
        .write_property_to_device(
            device_instance,
            oid,
            PropertyIdentifier::PRESENT_VALUE,
            None,
            buf.to_vec(),
            priority,
        )
        .await
        .map_err(|e| e.to_string())?;

    let out = json!({
        "ok": true,
        "device_instance": device_instance,
        "object_id": [object_type.to_raw(), instance],
        "priority": priority,
        "source": "rusty-bacnet-write"
    });
    let _ = client.stop().await;
    Ok(out)
}

/// RPM-first discovery; falls back to sequential ReadProperty when RPM fails.
pub async fn discover_device_points_with_fallback(
    device_instance: u32,
) -> Result<Vec<Value>, String> {
    match discover_device_points_rpm(device_instance).await {
        Ok(points) if !points.is_empty() => Ok(points),
        Ok(_) | Err(_) => discover_device_points(device_instance).await,
    }
}
