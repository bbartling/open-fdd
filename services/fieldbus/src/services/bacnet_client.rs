//! BACnet field-bus client (mirrors `app/bacnet_client.py`).

use std::collections::{HashMap, HashSet};
use std::net::Ipv4Addr;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use bacnet_client::client::BACnetClient;
use bacnet_client::discovery::RoutedDeviceConfig;
use bacnet_encoding::primitives::{decode_application_value, encode_property_value};
use bacnet_services::common::PropertyReference;
use bacnet_services::rpm::ReadAccessSpecification;
use bacnet_transport::bvll::encode_bip_mac;
use bacnet_types::enums::{ObjectType, PropertyIdentifier, Segmentation};
use bacnet_types::primitives::{ObjectIdentifier, PropertyValue};
use bytes::BytesMut;
use fdd_core::columns::{haystack_point_to_role, is_known_cookbook_role};
use serde_json::{json, Value};
use tokio::sync::Mutex;
use tracing::{info, warn};

use crate::config::{load_field_devices, FieldDevice, FieldPoint, Settings};
use crate::services::bacnet_server::{
    property_value_quality_error, property_value_tag, property_value_to_json,
};

static OBJECT_TYPE_MAP: &[(&str, ObjectType)] = &[
    ("analog-input", ObjectType::ANALOG_INPUT),
    ("analog-output", ObjectType::ANALOG_OUTPUT),
    ("analog-value", ObjectType::ANALOG_VALUE),
    ("binary-input", ObjectType::BINARY_INPUT),
    ("binary-output", ObjectType::BINARY_OUTPUT),
    ("binary-value", ObjectType::BINARY_VALUE),
    ("device", ObjectType::DEVICE),
    ("multi-state-input", ObjectType::MULTI_STATE_INPUT),
    ("multi-state-output", ObjectType::MULTI_STATE_OUTPUT),
    ("multi-state-value", ObjectType::MULTI_STATE_VALUE),
    ("integer-value", ObjectType::INTEGER_VALUE),
    ("large-analog-value", ObjectType::LARGE_ANALOG_VALUE),
    ("positive-integer-value", ObjectType::POSITIVE_INTEGER_VALUE),
    ("characterstring-value", ObjectType::CHARACTERSTRING_VALUE),
    ("character-string-value", ObjectType::CHARACTERSTRING_VALUE),
    ("schedule", ObjectType::SCHEDULE),
    ("calendar", ObjectType::CALENDAR),
    ("trend-log", ObjectType::TREND_LOG),
    ("loop", ObjectType::LOOP),
];

static COMMANDABLE_TYPES: &[&str] = &[
    "analog-output",
    "analog-value",
    "binary-output",
    "binary-value",
    "multi-state-output",
    "multi-state-value",
    "integer-value",
    "large-analog-value",
    "positive-integer-value",
];

pub struct BacnetClientService {
    settings: Settings,
    field_devices: Vec<FieldDevice>,
    bus_lock: Mutex<()>,
}

impl BacnetClientService {
    pub fn new(settings: Settings) -> Result<Self, String> {
        Ok(Self {
            field_devices: load_field_devices(Some(&settings.field_devices_toml))?,
            settings,
            bus_lock: Mutex::new(()),
        })
    }

    fn find_device(&self, device_instance: u32) -> Option<&FieldDevice> {
        self.field_devices
            .iter()
            .find(|d| d.device_instance == device_instance)
    }

    /// UDP bind for a client session.
    ///
    /// - **Discovery / Who-Is** (`device == None`): hear broadcast I-Am on the BACnet/IP
    ///   port. `whois_bind_port = 0` means "use hosted `bacnet_server.port`" (default
    ///   47808). `bacnet-transport` BIP sets `SO_REUSEADDR`, so this coexists with the
    ///   hosted server for the short Who-Is window (#526).
    /// - **Routed MS/TP**: keep ephemeral (or explicit `whois_bind_port`) — do not hold
    ///   `:47808` across long poll cycles (would steal hosted-server unicast).
    /// - **IP field devices**: ephemeral `read_bind_port` for unicast ReadProperty.
    fn bind_port(&self, device: Option<&FieldDevice>) -> u16 {
        match device {
            None => discovery_bind_port(
                self.settings.bacnet_client.whois_bind_port,
                self.settings.bacnet_server.port,
            ),
            Some(d) if d.is_routed() => self.settings.bacnet_client.whois_bind_port,
            Some(_) => self.settings.bacnet_client.read_bind_port,
        }
    }

    async fn new_client(
        &self,
        device: Option<&FieldDevice>,
    ) -> Result<BACnetClient<bacnet_transport::bip::BipTransport>, String> {
        let cfg = &self.settings.bacnet_client;
        // Who-Is must bind INADDR_ANY to receive BACnet/IP directed-broadcast I-Am.
        // A unicast interface from OPENFDD_FIELDBUS_BIND (e.g. 192.168.204.55) misses
        // those datagrams on Linux even with SO_REUSEADDR on :47808 (#526).
        let interface = if device.is_none() {
            Ipv4Addr::UNSPECIFIED
        } else {
            cfg.interface
        };
        BACnetClient::bip_builder()
            .interface(interface)
            .port(self.bind_port(device))
            .broadcast_address(cfg.broadcast)
            .apdu_timeout_ms(u64::from(cfg.apdu_timeout_ms))
            .build()
            .await
            .map_err(|e| e.to_string())
    }

    /// Always `stop()` the client; preserve the primary operation result and log stop failures.
    async fn finish_client<T>(
        mut client: BACnetClient<bacnet_transport::bip::BipTransport>,
        result: Result<T, String>,
    ) -> Result<T, String> {
        if let Err(e) = client.stop().await {
            warn!("failed to stop BACnet client: {e}");
        }
        result
    }

    async fn seed_field_device(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        d: &FieldDevice,
    ) -> Result<(), String> {
        if d.is_routed() {
            let ip: Ipv4Addr = d.host.parse().map_err(|e| format!("bad host: {e}"))?;
            let router_mac = encode_bip_mac(ip.octets(), d.port);
            let net = d
                .mstp_network
                .ok_or_else(|| format!("routed device {} missing mstp_network", d.name))?;
            let dest_mac = d
                .mstp_mac
                .first()
                .copied()
                .ok_or_else(|| format!("routed device {} missing mstp_mac", d.name))?;
            client
                .add_routed_device(RoutedDeviceConfig {
                    instance: d.device_instance,
                    router_mac: router_mac.to_vec(),
                    remote_network: net,
                    remote_mac: vec![dest_mac],
                    max_apdu_length: d.max_apdu,
                    segmentation_supported: Segmentation::NONE,
                    max_segments_accepted: None,
                })
                .await
                .map_err(|e| e.to_string())?;
            info!(
                device_instance = d.device_instance,
                router = %d.host,
                mstp_network = net,
                mstp_mac = dest_mac,
                "seeded routed BACnet device (add_routed_device)"
            );
            // Best-effort: probe the remote MSTP network via the router.
            if let Err(e) = client
                .who_is_network(net, Some(d.device_instance), Some(d.device_instance))
                .await
            {
                warn!(
                    "who_is_network for routed device {} (net {net}): {e}",
                    d.name
                );
            }
            Ok(())
        } else {
            let ip: Ipv4Addr = d.host.parse().map_err(|e| format!("bad host: {e}"))?;
            let mac = encode_bip_mac(ip.octets(), d.port);
            client
                .add_device(d.device_instance, &mac)
                .await
                .map_err(|e| e.to_string())
        }
    }

    async fn seed_configured_field_devices(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
    ) -> Result<(), String> {
        for d in &self.field_devices {
            if d.enabled {
                self.seed_field_device(client, d).await?;
            }
        }
        Ok(())
    }

    async fn prepare(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device: Option<&FieldDevice>,
        device_instance: u32,
    ) -> Result<(), String> {
        let cfg = &self.settings.bacnet_client;
        if let Some(d) = device {
            self.seed_field_device(client, d).await?;
        } else {
            client
                .who_is(Some(device_instance), Some(device_instance))
                .await
                .map_err(|e| e.to_string())?;
            tokio::time::sleep(Duration::from_secs_f64(cfg.whois_timeout_secs.min(3.0))).await;
        }
        Ok(())
    }

    pub async fn read_property(
        &self,
        device_instance: u32,
        object_type: &str,
        object_instance: u32,
        property_id: &str,
    ) -> Result<Value, String> {
        let _guard = self.bus_lock.lock().await;
        self.read_property_impl(device_instance, object_type, object_instance, property_id)
            .await
    }

    async fn read_property_impl(
        &self,
        device_instance: u32,
        object_type: &str,
        object_instance: u32,
        property_id: &str,
    ) -> Result<Value, String> {
        let device = self.find_device(device_instance);
        let ot = parse_object_type(object_type)?;
        let oid = ObjectIdentifier::new(ot, object_instance).map_err(|e| e.to_string())?;
        let pid = parse_property_id(property_id);
        let bind_port = self.bind_port(device);

        let client = self.new_client(device).await?;
        let result = async {
            self.prepare(&client, device, device_instance).await?;

            let ack = match client
                .read_property_from_device(device_instance, oid, pid, None)
                .await
            {
                Ok(a) => a,
                Err(_) if device.is_some() => {
                    let d = device.unwrap();
                    let ip: Ipv4Addr = d.host.parse().map_err(|e| format!("bad host: {e}"))?;
                    let mac = encode_bip_mac(ip.octets(), d.port);
                    client
                        .read_property(&mac, oid, pid, None)
                        .await
                        .map_err(|e| e.to_string())?
                }
                Err(e) => return Err(e.to_string()),
            };

            let (pv, _) =
                decode_application_value(&ack.property_value, 0).map_err(|e| e.to_string())?;
            Ok(json!({
                "device_instance": device_instance,
                "object_type": object_type,
                "object_instance": object_instance,
                "property_id": property_id,
                "tag": property_value_tag(&pv),
                "value": property_value_to_json(&pv),
                "quality": if property_value_quality_error(&pv).is_some() { "bad" } else { "good" },
                "error": property_value_quality_error(&pv),
                "client_bind_port": bind_port,
            }))
        }
        .await;
        Self::finish_client(client, result).await
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn write_property(
        &self,
        device_instance: u32,
        object_type: &str,
        object_instance: u32,
        value: Option<Value>,
        property_id: &str,
        priority: Option<u8>,
        value_type: Option<&str>,
    ) -> Result<Value, String> {
        let _guard = self.bus_lock.lock().await;
        self.write_property_impl(
            device_instance,
            object_type,
            object_instance,
            value,
            property_id,
            priority,
            value_type,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    async fn write_property_impl(
        &self,
        device_instance: u32,
        object_type: &str,
        object_instance: u32,
        value: Option<Value>,
        property_id: &str,
        priority: Option<u8>,
        value_type: Option<&str>,
    ) -> Result<Value, String> {
        let device = self.find_device(device_instance);
        let ot = parse_object_type(object_type)?;
        let oid = ObjectIdentifier::new(ot, object_instance).map_err(|e| e.to_string())?;
        let pid = parse_property_id(property_id);

        let is_release = match &value {
            None | Some(Value::Null) => true,
            Some(Value::String(s)) => s.trim().eq_ignore_ascii_case("null"),
            _ => false,
        };
        let (pv, write_priority) = if is_release {
            let p = priority
                .ok_or_else(|| "Null requires a priority (1-16) to release override".to_string())?;
            if !(1..=16).contains(&p) {
                return Err("Null requires a priority (1-16) to release override".into());
            }
            (PropertyValue::Null, Some(p))
        } else {
            (
                make_property_value(value.as_ref().unwrap(), value_type)?,
                priority,
            )
        };

        let mut buf = BytesMut::new();
        encode_property_value(&mut buf, &pv).map_err(|e| e.to_string())?;

        let client = self.new_client(device).await?;
        let result = async {
            self.prepare(&client, device, device_instance).await?;

            if let Err(_e) = client
                .write_property_to_device(
                    device_instance,
                    oid,
                    pid,
                    None,
                    buf.to_vec(),
                    write_priority,
                )
                .await
            {
                if let Some(d) = device {
                    let ip: Ipv4Addr = d.host.parse().map_err(|e| format!("bad host: {e}"))?;
                    let mac = encode_bip_mac(ip.octets(), d.port);
                    client
                        .write_property(&mac, oid, pid, None, buf.to_vec(), write_priority)
                        .await
                        .map_err(|e| e.to_string())?;
                } else {
                    return Err("write failed".into());
                }
            }

            Ok(json!({
                "status": "success",
                "device_instance": device_instance,
                "object_type": object_type,
                "object_instance": object_instance,
                "property_id": property_id,
                "released": is_release,
                "priority": write_priority,
            }))
        }
        .await;
        Self::finish_client(client, result).await
    }

    #[allow(clippy::too_many_arguments)]
    pub fn write_dry_run(
        &self,
        device_instance: u32,
        object_type: &str,
        object_instance: u32,
        value: Option<Value>,
        property_id: &str,
        priority: Option<u8>,
        value_type: Option<&str>,
    ) -> Result<Value, String> {
        let device = self.find_device(device_instance);
        let _ot = parse_object_type(object_type)?;

        let is_release = match &value {
            None | Some(Value::Null) => true,
            Some(Value::String(s)) => s.trim().eq_ignore_ascii_case("null"),
            _ => false,
        };
        let (pv, write_priority) = if is_release {
            let p = priority
                .ok_or_else(|| "Null requires a priority (1-16) to release override".to_string())?;
            if !(1..=16).contains(&p) {
                return Err("Null requires a priority (1-16) to release override".into());
            }
            (PropertyValue::Null, Some(p))
        } else {
            (
                make_property_value(value.as_ref().unwrap(), value_type)?,
                priority,
            )
        };

        Ok(json!({
            "dry_run": true,
            "would_write": true,
            "device_instance": device_instance,
            "object_type": object_type,
            "object_instance": object_instance,
            "property_id": property_id,
            "released": is_release,
            "priority": write_priority,
            "encoded_tag": property_value_tag(&pv),
            "encoded_value": property_value_to_json(&pv),
            "device_known": device.is_some(),
            "routed": device.map(|d| d.is_routed()),
        }))
    }

    pub async fn read_property_multiple(
        &self,
        device_instance: u32,
        objects: &[Value],
    ) -> Result<Value, String> {
        let _guard = self.bus_lock.lock().await;
        let device = self.find_device(device_instance);
        let mut specs = Vec::new();
        for obj in objects {
            let ot = parse_object_type(obj["object_type"].as_str().unwrap_or(""))?;
            let inst = obj["object_instance"].as_u64().unwrap_or(0) as u32;
            let oid = ObjectIdentifier::new(ot, inst).map_err(|e| e.to_string())?;
            let props: Vec<PropertyReference> = obj["properties"]
                .as_array()
                .unwrap_or(&vec![])
                .iter()
                .filter_map(|p| {
                    Some(PropertyReference {
                        property_identifier: parse_property_id(p["property_id"].as_str()?),
                        property_array_index: p["array_index"].as_u64().map(|v| v as u32),
                    })
                })
                .collect();
            specs.push(ReadAccessSpecification {
                object_identifier: oid,
                list_of_property_references: props,
            });
        }
        let bind_port = self.bind_port(device);
        let client = self.new_client(device).await?;
        let result = async {
            self.prepare(&client, device, device_instance).await?;
            let rpm = client
                .read_property_multiple_from_device(device_instance, specs)
                .await
                .map_err(|e| e.to_string())?;
            Ok(json!({
                "device_instance": device_instance,
                "results": serialize_rpm(&rpm),
                "client_bind_port": bind_port,
            }))
        }
        .await;
        Self::finish_client(client, result).await
    }

    pub async fn poll_points(&self) -> Result<Vec<Value>, String> {
        let _guard = self.bus_lock.lock().await;
        let mut out = Vec::new();
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();

        for d in &self.field_devices {
            if !d.enabled || d.points.is_empty() {
                continue;
            }
            let points = select_poll_points(d, self.settings.poll.health_roles_only);
            if points.is_empty() {
                continue;
            }
            let mut specs = Vec::new();
            for p in &points {
                let Ok(ot) = parse_object_type(&p.object_type) else {
                    continue;
                };
                let oid =
                    ObjectIdentifier::new(ot, p.object_instance).map_err(|e| e.to_string())?;
                specs.push(ReadAccessSpecification {
                    object_identifier: oid,
                    list_of_property_references: vec![PropertyReference {
                        property_identifier: PropertyIdentifier::PRESENT_VALUE,
                        property_array_index: None,
                    }],
                });
            }
            if specs.is_empty() {
                continue;
            }

            match self.poll_device(d, &specs).await {
                Ok(map) => {
                    for p in &points {
                        let Ok(ot) = parse_object_type(&p.object_type) else {
                            continue;
                        };
                        let oid = ObjectIdentifier::new(ot, p.object_instance).unwrap();
                        let oid_str = normalize_oid(&oid);
                        let entry = map.get(&oid_str);
                        out.push(json!({
                            "device_instance": d.device_instance,
                            "device_name": d.name,
                            "object_type": p.object_type,
                            "object_instance": p.object_instance,
                            "point_name": p.point_name,
                            "value": entry.and_then(|e| e.0.clone()),
                            "error": entry.and_then(|e| e.1.clone()),
                            "ts": ts,
                        }));
                    }
                }
                Err(e) => {
                    warn!("poll cycle failed for device {}: {e}", d.device_instance);
                    for p in &points {
                        out.push(json!({
                            "device_instance": d.device_instance,
                            "device_name": d.name,
                            "object_type": p.object_type,
                            "object_instance": p.object_instance,
                            "point_name": p.point_name,
                            "value": Value::Null,
                            "error": e,
                            "ts": ts,
                        }));
                    }
                }
            }
        }
        Ok(out)
    }

    async fn poll_device(
        &self,
        device: &FieldDevice,
        specs: &[ReadAccessSpecification],
    ) -> Result<HashMap<String, (Option<Value>, Option<String>)>, String> {
        let client = self.new_client(Some(device)).await?;
        let result = async {
            self.prepare(&client, Some(device), device.device_instance)
                .await?;
            let mut map = HashMap::new();
            for chunk in rpm_request_chunks(specs, device.rpm_chunk) {
                let rpm = client
                    .read_property_multiple_from_device(device.device_instance, chunk.to_vec())
                    .await
                    .map_err(|e| e.to_string())?;
                for obj in rpm.list_of_read_access_results {
                    let oid_str = normalize_oid(&obj.object_identifier);
                    for r in obj.list_of_results {
                        if let Some((class, code)) = r.error {
                            map.insert(
                                oid_str.clone(),
                                (None, Some(format!("Error: class={class:?} code={code:?}"))),
                            );
                        } else if let Some(bytes) = r.property_value {
                            let (pv, _) =
                                decode_application_value(&bytes, 0).map_err(|e| e.to_string())?;
                            map.insert(
                                oid_str.clone(),
                                (
                                    Some(property_value_to_json(&pv)),
                                    property_value_quality_error(&pv),
                                ),
                            );
                        }
                    }
                }
            }
            Ok(map)
        }
        .await;
        Self::finish_client(client, result).await
    }

    pub async fn who_is(&self, low: Option<u32>, high: Option<u32>) -> Result<Vec<Value>, String> {
        let _guard = self.bus_lock.lock().await;
        let cfg = &self.settings.bacnet_client;
        let client = self.new_client(None).await?;
        let result = async {
            self.seed_configured_field_devices(&client).await?;
            client.who_is(low, high).await.map_err(|e| e.to_string())?;
            tokio::time::sleep(Duration::from_secs_f64(cfg.whois_timeout_secs)).await;
            // Re-seed configured devices (table may already include live I-Am from #526 bind).
            self.seed_configured_field_devices(&client).await?;
            let devices = client.discovered_devices().await;
            // #539: discovered_devices() is a full device-table snapshot (incl.
            // seeded devices); honor the caller's requested instance range.
            let mut out: Vec<Value> = devices
                .iter()
                .filter(|d| {
                    let instance = d.object_identifier.instance_number();
                    low.is_none_or(|lo| instance >= lo) && high.is_none_or(|hi| instance <= hi)
                })
                .map(device_summary)
                .collect();
            // Fallback only: live I-Am should cover remote + co-located hosted after
            // discovery bind on bacnet_server.port (#526). Keep synthesize for edge cases.
            self.merge_local_hosted_device(&mut out, low, high);
            self.merge_configured_routed_devices(&mut out, low, high);
            Ok(out)
        }
        .await;
        Self::finish_client(client, result).await
    }

    /// Enrich Who-Is results with configured MS/TP routing metadata.
    fn merge_configured_routed_devices(
        &self,
        out: &mut Vec<Value>,
        low: Option<u32>,
        high: Option<u32>,
    ) {
        for d in &self.field_devices {
            if !d.enabled || !d.is_routed() {
                continue;
            }
            let inst = d.device_instance;
            if low.is_some_and(|lo| inst < lo) || high.is_some_and(|hi| inst > hi) {
                continue;
            }
            let net = d.mstp_network.unwrap_or(0);
            if let Some(row) = out.iter_mut().find(|v| {
                v.get("device_instance")
                    .and_then(|x| x.as_u64())
                    .is_some_and(|n| n as u32 == inst)
            }) {
                if row.get("source_network").and_then(|v| v.as_u64()).is_none() {
                    row["source_network"] = json!(net);
                }
                continue;
            }
            out.push(json!({
                "device_instance": inst,
                "address": d.address(),
                "vendor_id": null,
                "source_network": net,
                "max_apdu": null,
                "configured_routed": true,
                "note": "synthesized from field_devices.toml — I-Am lacked source_network",
            }));
        }
    }

    /// Append configured hosted BACnet server instance when missing from discovery.
    fn merge_local_hosted_device(&self, out: &mut Vec<Value>, low: Option<u32>, high: Option<u32>) {
        let hosted = self.settings.bacnet_server.device_instance;
        if low.is_some_and(|lo| hosted < lo) || high.is_some_and(|hi| hosted > hi) {
            return;
        }
        let already = out.iter().any(|v| {
            v.get("device_instance")
                .and_then(|x| x.as_u64())
                .is_some_and(|n| n as u32 == hosted)
        });
        if already {
            return;
        }
        let port = self.settings.bacnet_server.port;
        out.push(json!({
            "device_instance": hosted,
            "address": format!("local-hosted:{port}"),
            "vendor_id": 999,
            "source_network": null,
            "max_apdu": null,
            "hosted_local": true,
            "note": "synthesized fallback — live I-Am missing after discovery bind on server port",
        }));
    }

    pub async fn who_is_router_to_network(&self) -> Result<Vec<Value>, String> {
        let _guard = self.bus_lock.lock().await;
        // bacnet-client 0.9 has no router discovery API; synthesize from configured
        // field devices (same JSON shape as the previous native + fallback path).
        let mut by_router: HashMap<String, HashSet<u16>> = HashMap::new();
        for d in &self.field_devices {
            if d.enabled && d.is_routed() {
                if let Some(net) = d.mstp_network {
                    by_router.entry(d.host.clone()).or_default().insert(net);
                }
            }
        }
        Ok(by_router
            .into_iter()
            .map(|(source, nets)| {
                let mut networks: Vec<_> = nets.into_iter().collect();
                networks.sort_unstable();
                json!({ "source": source, "networks": networks })
            })
            .collect())
    }

    pub async fn point_discovery(&self, device_instance: u32) -> Result<Value, String> {
        let _guard = self.bus_lock.lock().await;
        self.point_discovery_impl(device_instance).await
    }

    async fn point_discovery_impl(&self, device_instance: u32) -> Result<Value, String> {
        let device = self.find_device(device_instance);
        let client = self.new_client(device).await?;
        let result = async {
            self.prepare(&client, device, device_instance).await?;
            let addr = self.resolve_address(&client, device, device_instance).await;

            let rpm_chunk = device.map_or(25, |d| d.rpm_chunk.max(1));
            let raw_oids = self
                .read_object_list(&client, device_instance, rpm_chunk)
                .await?;
            let oids: Vec<_> = raw_oids
                .into_iter()
                .filter(|o| object_type_name(o.object_type()) != "device")
                .collect();

            let name_map = self
                .read_object_names(&client, device_instance, &oids)
                .await?;

            let mut commandable = HashSet::new();
            let candidates: Vec<_> = oids
                .iter()
                .filter(|o| COMMANDABLE_TYPES.contains(&object_type_name(o.object_type()).as_str()))
                .copied()
                .collect();
            for chunk in candidates.chunks(rpm_chunk) {
                let specs: Vec<_> = chunk
                    .iter()
                    .map(|o| ReadAccessSpecification {
                        object_identifier: *o,
                        list_of_property_references: vec![PropertyReference {
                            property_identifier: PropertyIdentifier::PRIORITY_ARRAY,
                            property_array_index: Some(0),
                        }],
                    })
                    .collect();
                if let Ok(res) = client
                    .read_property_multiple_from_device(device_instance, specs)
                    .await
                {
                    for obj in res.list_of_read_access_results {
                        let oid_str = normalize_oid(&obj.object_identifier);
                        for r in obj.list_of_results {
                            if r.error.is_none() && r.property_value.is_some() {
                                commandable.insert(oid_str.clone());
                            }
                        }
                    }
                }
            }

            let objects: Vec<_> = oids
                .iter()
                .map(|o| {
                    let oid_str = normalize_oid(o);
                    json!({
                        "object_identifier": oid_str,
                        "name": name_map.get(&oid_str).cloned().unwrap_or_else(|| json!("?")),
                        "commandable": commandable.contains(&oid_str),
                    })
                })
                .collect();

            Ok(json!({
                "device_address": addr,
                "device_instance": device_instance,
                "objects": objects,
            }))
        }
        .await;
        Self::finish_client(client, result).await
    }

    async fn read_object_list(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        rpm_chunk: usize,
    ) -> Result<Vec<ObjectIdentifier>, String> {
        let dev_oid = ObjectIdentifier::new(ObjectType::DEVICE, device_instance)
            .map_err(|e| e.to_string())?;
        let length_ack = client
            .read_property_from_device(
                device_instance,
                dev_oid,
                PropertyIdentifier::OBJECT_LIST,
                Some(0),
            )
            .await
            .map_err(|e| e.to_string())?;
        let (length_pv, _) =
            decode_application_value(&length_ack.property_value, 0).map_err(|e| e.to_string())?;
        let length = match length_pv {
            PropertyValue::Unsigned(v) => v as usize,
            PropertyValue::Signed(v) => v as usize,
            _ => return Err("unexpected object-list length type".into()),
        };

        let mut oids = Vec::new();
        for (start, end) in rpm_chunk_ranges(length, rpm_chunk) {
            let idxs: Vec<u32> = (start..=end).map(|i| i as u32).collect();
            let specs = vec![ReadAccessSpecification {
                object_identifier: dev_oid,
                list_of_property_references: idxs
                    .iter()
                    .map(|i| PropertyReference {
                        property_identifier: PropertyIdentifier::OBJECT_LIST,
                        property_array_index: Some(*i),
                    })
                    .collect(),
            }];
            match client
                .read_property_multiple_from_device(device_instance, specs)
                .await
            {
                Ok(res) => {
                    for r in &res.list_of_read_access_results[0].list_of_results {
                        if let Some(bytes) = &r.property_value {
                            if let Ok((PropertyValue::ObjectIdentifier(oid), _)) =
                                decode_application_value(bytes, 0)
                            {
                                oids.push(oid);
                            }
                        }
                    }
                }
                Err(e) => {
                    warn!("object-list RPM chunk failed ({e}); per-index fallback");
                    for i in start..=end {
                        if let Ok(ack) = client
                            .read_property_from_device(
                                device_instance,
                                dev_oid,
                                PropertyIdentifier::OBJECT_LIST,
                                Some(i as u32),
                            )
                            .await
                        {
                            if let Ok((PropertyValue::ObjectIdentifier(oid), _)) =
                                decode_application_value(&ack.property_value, 0)
                            {
                                oids.push(oid);
                            }
                        }
                    }
                }
            }
        }
        Ok(oids)
    }

    pub async fn read_priority_array(
        &self,
        device_instance: u32,
        object_type: &str,
        object_instance: u32,
    ) -> Result<Value, String> {
        let _guard = self.bus_lock.lock().await;
        let device = self.find_device(device_instance);
        let ot = parse_object_type(object_type)?;
        let oid = ObjectIdentifier::new(ot, object_instance).map_err(|e| e.to_string())?;
        let client = self.new_client(device).await?;
        let result = async {
            self.prepare(&client, device, device_instance).await?;
            let slots = self
                .read_priority_slots(&client, device_instance, oid)
                .await?;
            Ok(json!({
                "device_instance": device_instance,
                "object_identifier": normalize_oid(&oid),
                "priority_array": slots,
            }))
        }
        .await;
        Self::finish_client(client, result).await
    }

    async fn read_priority_slots(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oid: ObjectIdentifier,
    ) -> Result<Vec<Value>, String> {
        let specs = vec![ReadAccessSpecification {
            object_identifier: oid,
            list_of_property_references: (1..=16)
                .map(|i| PropertyReference {
                    property_identifier: PropertyIdentifier::PRIORITY_ARRAY,
                    property_array_index: Some(i),
                })
                .collect(),
        }];
        let mut slots = Vec::new();
        match client
            .read_property_multiple_from_device(device_instance, specs)
            .await
        {
            Ok(res) => {
                for r in &res.list_of_read_access_results[0].list_of_results {
                    let idx = r.property_array_index.unwrap_or(0);
                    if let Some((class, code)) = r.error {
                        slots.push(json!({
                            "priority_level": idx,
                            "type": "error",
                            "value": format!("Error: class={class:?} code={code:?}"),
                        }));
                    } else if let Some(bytes) = &r.property_value {
                        let (pv, _) =
                            decode_application_value(bytes, 0).map_err(|e| e.to_string())?;
                        let tag = property_value_tag(&pv);
                        slots.push(json!({
                            "priority_level": idx,
                            "type": tag,
                            "value": if tag == "null" { Value::Null } else { property_value_to_json(&pv) },
                        }));
                    }
                }
            }
            Err(_) => {
                for i in 1..=16u32 {
                    match client
                        .read_property_from_device(
                            device_instance,
                            oid,
                            PropertyIdentifier::PRIORITY_ARRAY,
                            Some(i),
                        )
                        .await
                    {
                        Ok(ack) => {
                            let (pv, _) = decode_application_value(&ack.property_value, 0)
                                .map_err(|e| e.to_string())?;
                            let tag = property_value_tag(&pv);
                            slots.push(json!({
                                "priority_level": i,
                                "type": tag,
                                "value": if tag == "null" { Value::Null } else { property_value_to_json(&pv) },
                            }));
                        }
                        Err(e) => slots.push(json!({
                            "priority_level": i,
                            "type": "error",
                            "value": e.to_string(),
                        })),
                    }
                }
            }
        }
        slots.sort_by_key(|s| s["priority_level"].as_u64().unwrap_or(0));
        Ok(slots)
    }

    /// Read object names via RPM batches with per-object ReadProperty fallback
    /// (mirrors `point-discover` sample).
    async fn read_object_names(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oids: &[ObjectIdentifier],
    ) -> Result<HashMap<String, Value>, String> {
        const BATCH: usize = 10;
        let mut name_map = HashMap::new();

        for chunk in oids.chunks(BATCH) {
            let specs: Vec<_> = chunk
                .iter()
                .map(|o| ReadAccessSpecification {
                    object_identifier: *o,
                    list_of_property_references: vec![PropertyReference {
                        property_identifier: PropertyIdentifier::OBJECT_NAME,
                        property_array_index: None,
                    }],
                })
                .collect();

            let mut batch_names: HashMap<ObjectIdentifier, String> = HashMap::new();
            match client
                .read_property_multiple_from_device(device_instance, specs)
                .await
            {
                Ok(res) => {
                    for obj in res.list_of_read_access_results {
                        for r in obj.list_of_results {
                            if r.property_identifier != PropertyIdentifier::OBJECT_NAME {
                                continue;
                            }
                            if let Some(bytes) = r.property_value {
                                if let Ok((PropertyValue::CharacterString(name), _)) =
                                    decode_application_value(&bytes, 0)
                                {
                                    batch_names.insert(obj.object_identifier, name);
                                }
                            }
                        }
                    }
                }
                Err(e) => {
                    warn!("object-name RPM batch failed ({e}); per-object fallback");
                }
            }

            for oid in chunk {
                let oid_str = normalize_oid(oid);
                let name = if let Some(n) = batch_names.get(oid) {
                    n.clone()
                } else {
                    self.read_object_name(client, device_instance, *oid)
                        .await
                        .unwrap_or_else(|| "?".into())
                };
                name_map.insert(oid_str, json!(name));
            }
        }

        Ok(name_map)
    }

    async fn read_object_name(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oid: ObjectIdentifier,
    ) -> Option<String> {
        match client
            .read_property_from_device(device_instance, oid, PropertyIdentifier::OBJECT_NAME, None)
            .await
        {
            Ok(ack) => decode_application_value(&ack.property_value, 0)
                .ok()
                .and_then(|(pv, _)| match pv {
                    PropertyValue::CharacterString(s) => Some(s),
                    _ => None,
                }),
            Err(_) => None,
        }
    }

    pub async fn supervisory_logic_check(&self, device_instance: u32) -> Result<Value, String> {
        let _guard = self.bus_lock.lock().await;
        let disc = self.point_discovery_impl(device_instance).await?;
        let device_address = disc["device_address"].clone();
        let objects = disc["objects"].as_array().cloned().unwrap_or_default();

        let empty = json!({
            "device_id": device_instance,
            "address": device_address,
            "points": [],
            "points_with_overrides": [],
            "summary": {
                "total_points": objects.len(),
                "with_priority_array": 0,
                "without_priority_array": 0,
                "points_with_override_count": 0,
            }
        });
        if objects.is_empty() {
            return Ok(empty);
        }

        let commandable: Vec<_> = objects
            .iter()
            .filter(|o| o["commandable"].as_bool().unwrap_or(false))
            .cloned()
            .collect();
        let name_by_oid: HashMap<_, _> = objects
            .iter()
            .filter_map(|o| {
                Some((
                    o["object_identifier"].as_str()?.to_string(),
                    o["name"].clone(),
                ))
            })
            .collect();

        let device = self.find_device(device_instance);
        let client = self.new_client(device).await?;
        let result = async {
            self.prepare(&client, device, device_instance).await?;

            let mut points = Vec::new();
            let mut overrides_by_oid: HashMap<String, Vec<Value>> = HashMap::new();
            let mut with_pa = 0usize;

            for o in &commandable {
                let oid_str = o["object_identifier"].as_str().unwrap_or("");
                let mut parts = oid_str.split(',');
                let type_name = parts.next().unwrap_or("");
                let inst: u32 = parts.next().unwrap_or("0").parse().unwrap_or(0);
                let ot = parse_object_type(type_name)?;
                let oid = ObjectIdentifier::new(ot, inst).map_err(|e| e.to_string())?;
                let slots = self
                    .read_priority_slots(&client, device_instance, oid)
                    .await?;
                let active: Vec<_> = slots
                    .iter()
                    .filter(|s| {
                        s["type"]
                            .as_str()
                            .map(|t| t != "null" && t != "error")
                            .unwrap_or(false)
                    })
                    .cloned()
                    .collect();
                if !slots.is_empty() {
                    with_pa += 1;
                }
                for s in active {
                    let rec = json!({
                        "priority_level": s["priority_level"],
                        "object_identifier": oid_str,
                        "object_name": o["name"],
                        "type": s["type"],
                        "value": s["value"],
                    });
                    points.push(rec.clone());
                    overrides_by_oid
                        .entry(oid_str.to_string())
                        .or_default()
                        .push(json!({
                            "priority_level": s["priority_level"],
                            "type": s["type"],
                            "value": s["value"],
                        }));
                }
            }

            let points_with_overrides: Vec<_> = overrides_by_oid
                .into_iter()
                .map(|(oid_str, slots)| {
                    let levels: Vec<_> = slots
                        .iter()
                        .filter_map(|s| s["priority_level"].as_u64())
                        .collect();
                    json!({
                        "object_identifier": oid_str,
                        "object_name": name_by_oid.get(&oid_str).cloned().unwrap_or(json!("")),
                        "override_priority_levels": levels,
                        "has_multiple_overrides": levels.len() > 1,
                        "overrides": slots,
                    })
                })
                .collect();

            Ok(json!({
                "device_id": device_instance,
                "address": device_address,
                "points": points,
                "points_with_overrides": points_with_overrides,
                "summary": {
                    "total_points": objects.len(),
                    "with_priority_array": with_pa,
                    "without_priority_array": objects.len().saturating_sub(with_pa),
                    "points_with_override_count": points_with_overrides.len(),
                }
            }))
        }
        .await;
        Self::finish_client(client, result).await
    }

    async fn resolve_address(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device: Option<&FieldDevice>,
        device_instance: u32,
    ) -> Option<String> {
        if let Some(d) = device {
            if !d.is_routed() {
                return Some(d.address());
            }
        }
        if let Some(d) = client.get_device(device_instance).await {
            return Some(
                device_summary(&d)["address"]
                    .as_str()
                    .unwrap_or("")
                    .to_string(),
            );
        }
        device.map(|d| d.address())
    }
}

/// Return inclusive object-list index ranges for a configured RPM chunk.
///
/// The configured `rpm_chunk` is deliberately independent of APDU negotiation:
/// a routed MS/TP device with a 206-byte, no-segmentation profile can set a
/// conservative value such as 10 and keep every request below its limit.
fn rpm_chunk_ranges(length: usize, configured_chunk: usize) -> Vec<(usize, usize)> {
    let chunk = configured_chunk.max(1);
    if length == 0 {
        return Vec::new();
    }
    (1..=length)
        .step_by(chunk)
        .map(|start| (start, (start + chunk - 1).min(length)))
        .collect()
}

/// Build the ReadPropertyMultiple request batches used by the live poll path.
/// Keep the configured chunk independent from APDU negotiation so conservative
/// routed profiles (for example max APDU 206 with no segmentation) can select
/// a safe request size.
fn rpm_request_chunks<T>(items: &[T], configured_chunk: usize) -> Vec<&[T]> {
    items.chunks(configured_chunk.max(1)).collect()
}

fn parse_object_type(name: &str) -> Result<ObjectType, String> {
    let key = name.trim().to_ascii_lowercase();
    if let Some((_, ot)) = OBJECT_TYPE_MAP.iter().find(|(k, _)| *k == key) {
        return Ok(*ot);
    }
    if name.trim().chars().all(|c| c.is_ascii_digit()) {
        return Ok(ObjectType::from_raw(
            name.trim().parse().map_err(|e| format!("{e}"))?,
        ));
    }
    Err(format!("unknown object_type {name}"))
}

fn parse_property_id(name: &str) -> PropertyIdentifier {
    let key = name.trim().to_ascii_lowercase().replace('-', "_");
    match key.as_str() {
        "present_value" => PropertyIdentifier::PRESENT_VALUE,
        "object_name" => PropertyIdentifier::OBJECT_NAME,
        "object_list" => PropertyIdentifier::OBJECT_LIST,
        "priority_array" => PropertyIdentifier::PRIORITY_ARRAY,
        "units" => PropertyIdentifier::UNITS,
        "description" => PropertyIdentifier::DESCRIPTION,
        "status_flags" => PropertyIdentifier::STATUS_FLAGS,
        _ => PropertyIdentifier::PRESENT_VALUE,
    }
}

fn object_type_name(ot: ObjectType) -> String {
    // Display yields ANALOG_OUTPUT; hyphenate for API parity with Python/FastAPI.
    format!("{ot}").to_ascii_lowercase().replace('_', "-")
}

fn normalize_oid(oid: &ObjectIdentifier) -> String {
    format!(
        "{},{}",
        object_type_name(oid.object_type()),
        oid.instance_number()
    )
}

fn make_property_value(value: &Value, value_type: Option<&str>) -> Result<PropertyValue, String> {
    let vt = value_type.unwrap_or("").trim().to_ascii_lowercase();
    if vt == "null" {
        return Ok(PropertyValue::Null);
    }
    if !vt.is_empty() {
        return match vt.as_str() {
            "real" => Ok(PropertyValue::Real(value.as_f64().unwrap_or(0.0) as f32)),
            "double" => Ok(PropertyValue::Double(value.as_f64().unwrap_or(0.0))),
            "unsigned" => Ok(PropertyValue::Unsigned(value.as_u64().unwrap_or(0))),
            "signed" => Ok(PropertyValue::Signed(value.as_i64().unwrap_or(0) as i32)),
            "enumerated" => Ok(PropertyValue::Enumerated(value.as_u64().unwrap_or(0) as u32)),
            "boolean" => Ok(PropertyValue::Boolean(value.as_bool().unwrap_or(false))),
            "character_string" | "character-string" => Ok(PropertyValue::CharacterString(
                value.as_str().unwrap_or("").to_string(),
            )),
            _ => Err(format!("unknown value_type {vt}")),
        };
    }
    if let Some(b) = value.as_bool() {
        return Ok(PropertyValue::Enumerated(if b { 1 } else { 0 }));
    }
    if let Some(f) = value.as_f64() {
        return Ok(PropertyValue::Real(f as f32));
    }
    if let Some(i) = value.as_i64() {
        return Ok(PropertyValue::Real(i as f32));
    }
    if let Some(s) = value.as_str() {
        return Ok(PropertyValue::CharacterString(s.to_string()));
    }
    Err("unsupported value type".into())
}

fn property_name(pid: PropertyIdentifier) -> String {
    format!("{pid}").to_ascii_lowercase().replace('_', "-")
}

fn serialize_rpm(rpm: &bacnet_services::rpm::ReadPropertyMultipleACK) -> Vec<Value> {
    let mut out = Vec::new();
    for obj in &rpm.list_of_read_access_results {
        let oid_str = normalize_oid(&obj.object_identifier);
        for r in &obj.list_of_results {
            let mut rec = json!({
                "object_identifier": oid_str,
                "property_identifier": property_name(r.property_identifier),
                "property_array_index": r.property_array_index,
            });
            if let Some((class, code)) = r.error {
                rec["value"] = json!(format!("Error: class={class:?} code={code:?}"));
            } else if let Some(bytes) = &r.property_value {
                if let Ok((pv, _)) = decode_application_value(bytes, 0) {
                    rec["value"] = property_value_to_json(&pv);
                }
            }
            out.push(rec);
        }
    }
    out
}

/// Select BACnet points for a poll cycle; optional health-role subset (~30% cap).
fn select_poll_points(device: &FieldDevice, health_only: bool) -> Vec<FieldPoint> {
    if !health_only {
        return device.points.clone();
    }
    let total = device.points.len();
    let mut selected: Vec<FieldPoint> = device
        .points
        .iter()
        .filter(|p| is_known_cookbook_role(&haystack_point_to_role(&p.point_name)))
        .cloned()
        .collect();
    if total == 0 {
        return selected;
    }
    let max_keep = ((total as f64) * 0.30).ceil() as usize;
    let max_keep = max_keep.max(1);
    if selected.len() > max_keep {
        warn!(
            device = %device.name,
            total,
            kept = max_keep,
            "health-only poll capped to ~30% of configured catalog"
        );
        selected.truncate(max_keep);
    }
    selected
}

/// Resolve Who-Is / discovery UDP bind. `whois_bind_port == 0` → hosted server port
/// so broadcast I-Am on BACnet/IP is receivable (`SO_REUSEADDR` in bacnet-transport).
fn discovery_bind_port(whois_bind_port: u16, server_port: u16) -> u16 {
    if whois_bind_port != 0 {
        whois_bind_port
    } else {
        server_port
    }
}

fn device_summary(d: &bacnet_client::discovery::DiscoveredDevice) -> Value {
    let mac = d.mac_address.as_slice();
    let addr = if mac.len() == 6 {
        format!(
            "{}.{}.{}.{}:{:04x}",
            mac[0],
            mac[1],
            mac[2],
            mac[3],
            ((mac[4] as u16) << 8) | mac[5] as u16
        )
    } else {
        mac.iter().map(|b| format!("{b:02x}")).collect::<String>()
    };
    json!({
        "device_instance": d.object_identifier.instance_number(),
        "address": addr,
        "vendor_id": d.vendor_id,
        "source_network": d.source_network,
        "max_apdu": d.max_apdu_length,
    })
}

#[cfg(test)]
mod poll_select_tests {
    use super::*;
    use crate::config::FieldPoint;

    fn dev(name: &str, inst: u32, points: Vec<FieldPoint>) -> FieldDevice {
        FieldDevice {
            name: name.into(),
            enabled: true,
            device_instance: inst,
            host: "127.0.0.1".into(),
            port: 47808,
            mstp_network: None,
            mstp_mac: vec![],
            rpm_chunk: 25,
            max_apdu: 480,
            points,
        }
    }

    #[test]
    fn health_only_caps_to_thirty_percent() {
        let points: Vec<_> = (0..10)
            .map(|i| FieldPoint {
                object_type: "analog-input".into(),
                object_instance: i,
                point_name: "fan-status".into(),
                units: "bool".into(),
            })
            .collect();
        let d = dev("ahu", 1, points);
        let selected = select_poll_points(&d, true);
        assert_eq!(selected.len(), 3);
    }

    #[test]
    fn discovery_bind_port_auto_uses_server_port() {
        assert_eq!(discovery_bind_port(0, 47808), 47808);
        assert_eq!(discovery_bind_port(0, 47809), 47809);
        assert_eq!(discovery_bind_port(47900, 47808), 47900);
    }

    #[test]
    fn poll_rpm_path_uses_configured_chunk_for_206_byte_profile() {
        let mut fec = dev("fec-5007", 5007, vec![]);
        fec.rpm_chunk = 10;
        fec.max_apdu = 206;
        assert_eq!(fec.max_apdu, 206);
        let specs: Vec<_> = (1..=25)
            .map(|instance| ReadAccessSpecification {
                object_identifier: ObjectIdentifier::new(ObjectType::ANALOG_INPUT, instance)
                    .unwrap(),
                list_of_property_references: vec![PropertyReference {
                    property_identifier: PropertyIdentifier::PRESENT_VALUE,
                    property_array_index: None,
                }],
            })
            .collect();
        // This is the planner consumed by poll_device, rather than a separate
        // object-list range helper: every request stays at ten objects.
        let requests = rpm_request_chunks(&specs, fec.rpm_chunk);
        assert_eq!(
            requests.iter().map(|r| r.len()).collect::<Vec<_>>(),
            vec![10, 10, 5]
        );
        assert_eq!(requests[0][0].object_identifier.instance_number(), 1);
        assert_eq!(requests[2][4].object_identifier.instance_number(), 25);
        assert!(requests.iter().flat_map(|chunk| chunk.iter()).all(|spec| {
            spec.list_of_property_references[0].property_identifier
                == PropertyIdentifier::PRESENT_VALUE
        }));
        // Object-list RPM uses the same configured chunk, including a zero
        // request size that must still advance one object at a time.
        assert_eq!(
            rpm_chunk_ranges(25, fec.rpm_chunk),
            vec![(1, 10), (11, 20), (21, 25)]
        );
        assert_eq!(rpm_chunk_ranges(0, fec.rpm_chunk), Vec::new());
        assert_eq!(rpm_chunk_ranges(3, 0), vec![(1, 1), (2, 2), (3, 3)]);
    }
}

#[cfg(test)]
mod oid_tests {
    use super::*;
    use bacnet_types::enums::ObjectType;

    #[test]
    fn object_type_name_hyphenates_display_output() {
        assert_eq!(object_type_name(ObjectType::ANALOG_OUTPUT), "analog-output");
        assert_eq!(object_type_name(ObjectType::ANALOG_INPUT), "analog-input");
        assert_eq!(object_type_name(ObjectType::DEVICE), "device");
    }

    #[test]
    fn normalize_oid_matches_python_contract() {
        let oid = ObjectIdentifier::new(ObjectType::ANALOG_OUTPUT, 2466).unwrap();
        assert_eq!(normalize_oid(&oid), "analog-output,2466");
    }
}
