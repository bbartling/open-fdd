//! BACnet field-bus client (mirrors `app/bacnet_client.py`).

use std::collections::{HashMap, HashSet};
use std::future::Future;
use std::net::Ipv4Addr;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use bacnet_client::client::BACnetClient;
use bacnet_client::discovery::RoutedDeviceConfig;
use bacnet_encoding::primitives::decode_application_value;
use bacnet_services::common::PropertyReference;
use bacnet_services::rpm::ReadAccessSpecification;
use bacnet_transport::bvll::encode_bip_mac;
use bacnet_types::enums::{AbortReason, ObjectType, PropertyIdentifier, Segmentation};
use bacnet_types::error::Error as BacnetError;
use bacnet_types::primitives::{ObjectIdentifier, PropertyValue};
use fdd_core::columns::{haystack_point_to_role, is_known_cookbook_role};
use serde_json::{json, Value};
use tokio::sync::{Mutex, MutexGuard, Semaphore};
use tracing::{info, warn};

use crate::config::{load_field_devices, FieldDevice, FieldPoint, Settings};
use crate::services::bacnet_server::{
    property_value_quality_error, property_value_tag, property_value_to_json,
};
use crate::services::bacnet_write::normalize_bacnet_write;

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

static NON_COMMANDABLE_TYPES: &[&str] = &[
    "analog-input",
    "binary-input",
    "device",
    "multi-state-input",
    "schedule",
    "calendar",
    "trend-log",
    "loop",
];

const PRIORITY_LEVELS: std::ops::RangeInclusive<u32> = 1..=16;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Commandability {
    Supported,
    Unsupported,
    Unknown,
}

impl Commandability {
    fn as_str(self) -> &'static str {
        match self {
            Self::Supported => "supported",
            Self::Unsupported => "unsupported",
            Self::Unknown => "unknown",
        }
    }

    fn is_supported(self) -> bool {
        self == Self::Supported
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WriteOutcome {
    Acknowledged,
    Rejected,
    Failed,
    Unknown,
}

#[derive(Debug)]
enum WriteVerificationFailure {
    Mismatch(String),
    Unknown(String),
}

#[derive(Debug)]
struct WriteReadback {
    selected_priority: Option<PropertyValue>,
    property_value: PropertyValue,
    effective_present_value: Option<PropertyValue>,
    masked: Option<bool>,
    winning_priority: Option<u8>,
}

impl WriteOutcome {
    fn status(self) -> &'static str {
        match self {
            Self::Acknowledged => "success",
            Self::Rejected => "rejected",
            Self::Failed => "failed",
            Self::Unknown => "unknown",
        }
    }

    fn outcome(self) -> &'static str {
        match self {
            Self::Acknowledged => "acknowledged",
            Self::Rejected => "rejected",
            Self::Failed => "failed",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Default)]
struct ObjectListRead {
    objects: Vec<ObjectIdentifier>,
    missing_indexes: Vec<u32>,
    errors: Vec<String>,
}

pub struct BacnetClientService {
    settings: Settings,
    field_devices: Vec<FieldDevice>,
    bus_lock: Mutex<()>,
    /// A BACnet/IP discovery client bound to the hosted Who-Is port must own
    /// that receive socket for its whole session. SO_REUSEADDR lets multiple
    /// sockets bind, but then replies can be delivered to the wrong client.
    discovery_port_lock: Mutex<()>,
    /// Interactive operations own the bus for their individual BACnet service
    /// call.  Scans use these permits to keep one active scan and one bounded
    /// waiter; an offline device therefore cannot create an unbounded socket
    /// or request flood.
    scan_gate: Semaphore,
    scan_admission: Semaphore,
}

impl BacnetClientService {
    pub fn new(settings: Settings) -> Result<Self, String> {
        Ok(Self {
            field_devices: load_field_devices(Some(&settings.field_devices_toml))?,
            settings,
            bus_lock: Mutex::new(()),
            discovery_port_lock: Mutex::new(()),
            scan_gate: Semaphore::const_new(1),
            scan_admission: Semaphore::const_new(2),
        })
    }

    fn find_device(&self, device_instance: u32) -> Option<&FieldDevice> {
        self.field_devices
            .iter()
            .find(|d| d.device_instance == device_instance)
    }

    async fn acquire_discovery_port(
        &self,
        device: Option<&FieldDevice>,
    ) -> Option<MutexGuard<'_, ()>> {
        if device.is_none() {
            Some(self.discovery_port_lock.lock().await)
        } else {
            None
        }
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
        self.new_client_with_retries(device, None).await
    }

    /// Build a BACnet client for a live WriteProperty operation.
    ///
    /// The BACnet client library retransmits confirmed requests when its APDU
    /// retry count is nonzero. A lost write acknowledgement is ambiguous: the
    /// device may already have applied the value, so a write client must send
    /// exactly one APDU and surface the outcome as unknown on timeout.
    async fn new_write_client(
        &self,
        device: Option<&FieldDevice>,
    ) -> Result<BACnetClient<bacnet_transport::bip::BipTransport>, String> {
        self.new_client_with_retries(device, Some(0)).await
    }

    async fn new_client_with_retries(
        &self,
        device: Option<&FieldDevice>,
        apdu_retries: Option<u8>,
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
        let builder = BACnetClient::bip_builder()
            .interface(interface)
            .port(self.bind_port(device))
            .broadcast_address(cfg.broadcast)
            .apdu_timeout_ms(u64::from(cfg.apdu_timeout_ms));
        let builder = match apdu_retries {
            Some(retries) => builder.apdu_retries(retries),
            None => builder,
        };
        builder.build().await.map_err(|e| e.to_string())
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
            let seeded = routed_device_config(d)?;
            let net = seeded.remote_network;
            let dest_mac = seeded.remote_mac.first().copied().unwrap_or(0);
            client
                .add_routed_device(seeded)
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

    /// Prepare a background scan one BACnet service at a time.  The scan
    /// admission permits bound the number of whole scans; this bus mutex then
    /// yields between each network operation so an interactive request can
    /// run after at most one in-flight APDU completes.
    async fn prepare_scan(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device: Option<&FieldDevice>,
        device_instance: u32,
    ) -> Result<(), String> {
        let cfg = &self.settings.bacnet_client;
        if let Some(d) = device {
            if d.is_routed() {
                let seeded = routed_device_config(d)?;
                let net = seeded.remote_network;
                let dest_mac = seeded.remote_mac.first().copied().unwrap_or(0);
                {
                    let _guard = self.bus_lock.lock().await;
                    client
                        .add_routed_device(seeded)
                        .await
                        .map_err(|e| e.to_string())?;
                }
                info!(
                    device_instance = d.device_instance,
                    router = %d.host,
                    mstp_network = net,
                    mstp_mac = dest_mac,
                    "seeded routed BACnet device (add_routed_device)"
                );
                {
                    let _guard = self.bus_lock.lock().await;
                    if let Err(e) = client
                        .who_is_network(net, Some(d.device_instance), Some(d.device_instance))
                        .await
                    {
                        warn!(
                            "who_is_network for routed device {} (net {net}): {e}",
                            d.name
                        );
                    }
                }
            } else {
                let ip: Ipv4Addr = d.host.parse().map_err(|e| format!("bad host: {e}"))?;
                let mac = encode_bip_mac(ip.octets(), d.port);
                let _guard = self.bus_lock.lock().await;
                client
                    .add_device(d.device_instance, &mac)
                    .await
                    .map_err(|e| e.to_string())?;
            }
        } else {
            {
                let _guard = self.bus_lock.lock().await;
                client
                    .who_is(Some(device_instance), Some(device_instance))
                    .await
                    .map_err(|e| e.to_string())?;
            }
            // Sleeping is deliberately outside the bus lock.  A Who-Is
            // response window must not block a point read or write.
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
        let discovery_port_guard = self
            .acquire_discovery_port(self.find_device(device_instance))
            .await;
        let _guard = self.bus_lock.lock().await;
        let _discovery_port_guard = discovery_port_guard;
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
                    let Some(d) = device else {
                        return Err("device disappeared during read preparation".into());
                    };
                    let ip: Ipv4Addr = d.host.parse().map_err(|e| format!("bad host: {e}"))?;
                    let mac = encode_bip_mac(ip.octets(), d.port);
                    client
                        .read_property(&mac, oid, pid, None)
                        .await
                        .map_err(|e| e.to_string())?
                }
                Err(e) => return Err(e.to_string()),
            };

            let bytes = correlated_property_value(&ack, oid, pid, None)?;
            let pv = decode_complete_application_value(bytes)?;
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

    #[expect(
        clippy::too_many_arguments,
        reason = "verification keeps the exact BACnet target and requested value explicit"
    )]
    async fn verify_write_readback(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oid: ObjectIdentifier,
        pid: PropertyIdentifier,
        priority: Option<u8>,
        expected: &PropertyValue,
        released: bool,
    ) -> Result<WriteReadback, WriteVerificationFailure> {
        // A priority present-value write is verified by both the exact
        // selected slot and the effective present value. The second read is
        // evidence only; it never retries or retransmits the write.
        if pid == PropertyIdentifier::PRESENT_VALUE {
            if let Some(priority) = priority {
                let selected = Self::read_write_readback(
                    client,
                    device_instance,
                    oid,
                    PropertyIdentifier::PRIORITY_ARRAY,
                    Some(u32::from(priority)),
                )
                .await?;
                if selected != *expected {
                    return Err(WriteVerificationFailure::Mismatch(format!(
                        "priority-array P{priority} readback mismatch: expected {} {}, got {} {}",
                        property_value_tag(expected),
                        property_value_to_json(expected),
                        property_value_tag(&selected),
                        property_value_to_json(&selected)
                    )));
                }

                let present_value = Self::read_write_readback(
                    client,
                    device_instance,
                    oid,
                    PropertyIdentifier::PRESENT_VALUE,
                    None,
                )
                .await?;
                let (masked, winning_priority) = self
                    .read_priority_masking(client, device_instance, oid, priority, released)
                    .await;
                return Ok(WriteReadback {
                    selected_priority: Some(selected),
                    property_value: present_value.clone(),
                    effective_present_value: Some(present_value),
                    masked,
                    winning_priority,
                });
            }
        }

        let property_value =
            Self::read_write_readback(client, device_instance, oid, pid, None).await?;
        if property_value != *expected {
            return Err(WriteVerificationFailure::Mismatch(format!(
                "{} readback mismatch: expected {} {}, got {} {}",
                pid,
                property_value_tag(expected),
                property_value_to_json(expected),
                property_value_tag(&property_value),
                property_value_to_json(&property_value)
            )));
        }
        Ok(WriteReadback {
            selected_priority: None,
            property_value,
            effective_present_value: None,
            masked: None,
            winning_priority: None,
        })
    }

    async fn read_priority_masking(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oid: ObjectIdentifier,
        selected_priority: u8,
        released: bool,
    ) -> (Option<bool>, Option<u8>) {
        let mut active_higher = None;
        for level in 1..selected_priority {
            let Ok(value) = Self::read_write_readback(
                client,
                device_instance,
                oid,
                PropertyIdentifier::PRIORITY_ARRAY,
                Some(u32::from(level)),
            )
            .await
            else {
                return (None, None);
            };
            if value != PropertyValue::Null {
                active_higher = Some(level);
                break;
            }
        }
        match active_higher {
            Some(level) => (Some(true), Some(level)),
            None if released => (Some(false), None),
            None => (Some(false), Some(selected_priority)),
        }
    }

    async fn read_write_readback(
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oid: ObjectIdentifier,
        pid: PropertyIdentifier,
        array_index: Option<u32>,
    ) -> Result<PropertyValue, WriteVerificationFailure> {
        let ack = client
            .read_property_from_device(device_instance, oid, pid, array_index)
            .await
            .map_err(|error| {
                WriteVerificationFailure::Unknown(format!(
                    "readback {pid:?} index {array_index:?} failed: {error}"
                ))
            })?;
        let bytes = correlated_property_value(&ack, oid, pid, array_index)
            .map_err(WriteVerificationFailure::Unknown)?;
        decode_complete_application_value(bytes).map_err(WriteVerificationFailure::Unknown)
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "public request shape mirrors the BACnet WriteProperty route"
    )]
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
        let discovery_port_guard = self
            .acquire_discovery_port(self.find_device(device_instance))
            .await;
        let _guard = self.bus_lock.lock().await;
        let _discovery_port_guard = discovery_port_guard;
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

    #[expect(
        clippy::too_many_arguments,
        reason = "private implementation keeps the route's typed BACnet fields explicit"
    )]
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

        let normalized = normalize_bacnet_write(value.as_ref(), priority, value_type)?;
        let is_release = normalized.released;
        let write_priority = normalized.priority;
        let expected_value = normalized.property_value.clone();
        let encoded_value = normalized.encoded_value;

        let client = self.new_write_client(device).await?;
        let result = async {
            self.prepare(&client, device, device_instance).await?;

            // A confirmed WriteProperty may have reached the device even when
            // its acknowledgement is lost.  This is deliberately one-shot:
            // never resend through a second addressing path after an error.
            let mut write_attempts = 0;
            let write_result = write_once(&mut write_attempts, || async {
                client
                    .write_property_to_device(
                        device_instance,
                        oid,
                        pid,
                        None,
                        encoded_value,
                        write_priority,
                    )
                    .await
            })
            .await;
            let outcome = classify_write_error_result(&write_result);
            let routed = device.is_some_and(FieldDevice::is_routed);
            match write_result {
                Ok(()) => match self
                    .verify_write_readback(
                        &client,
                        device_instance,
                        oid,
                        pid,
                        write_priority,
                        &expected_value,
                        is_release,
                    )
                    .await
                {
                    Ok(readback) => Ok(json!({
                        "ok": true,
                        "status": outcome.status(),
                        "outcome": outcome.outcome(),
                        "write_attempts": write_attempts,
                        "device_instance": device_instance,
                        "object_type": object_type,
                        "object_instance": object_instance,
                        "property_id": property_id,
                        "released": is_release,
                        "verified": true,
                        "transmission_acknowledged": true,
                        "verification": "readback",
                        "readback": write_readback_json(&readback),
                        "priority": write_priority,
                        "routed": routed,
                    })),
                    Err(WriteVerificationFailure::Mismatch(error)) => Ok(json!({
                        "ok": false,
                        "status": WriteOutcome::Failed.status(),
                        "outcome": WriteOutcome::Failed.outcome(),
                        "write_attempts": write_attempts,
                        "device_instance": device_instance,
                        "object_type": object_type,
                        "object_instance": object_instance,
                        "property_id": property_id,
                        "released": false,
                        "verified": false,
                        "transmission_acknowledged": true,
                        "verification": "mismatch",
                        "verification_error": error,
                        "priority": write_priority,
                        "routed": routed,
                    })),
                    Err(WriteVerificationFailure::Unknown(error)) => Ok(json!({
                        "ok": false,
                        "status": WriteOutcome::Unknown.status(),
                        "outcome": WriteOutcome::Unknown.outcome(),
                        "write_attempts": write_attempts,
                        "device_instance": device_instance,
                        "object_type": object_type,
                        "object_instance": object_instance,
                        "property_id": property_id,
                        "released": false,
                        "verified": false,
                        "transmission_acknowledged": true,
                        "verification": "unavailable",
                        "verification_error": error,
                        "priority": write_priority,
                        "routed": routed,
                    })),
                },
                Err(error) => Ok(json!({
                    "ok": false,
                    "status": outcome.status(),
                    "outcome": outcome.outcome(),
                    "write_attempts": write_attempts,
                    "device_instance": device_instance,
                    "object_type": object_type,
                    "object_instance": object_instance,
                    "property_id": property_id,
                    "released": false,
                    "verified": false,
                    "transmission_acknowledged": false,
                    "priority": write_priority,
                    "routed": routed,
                    "error": error.to_string(),
                })),
            }
        }
        .await;
        Self::finish_client(client, result).await
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "dry-run API mirrors the live WriteProperty request"
    )]
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

        let normalized = normalize_bacnet_write(value.as_ref(), priority, value_type)?;
        let is_release = normalized.released;
        let write_priority = normalized.priority;
        let pv = normalized.property_value;

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
        let _discovery_port_guard = self
            .acquire_discovery_port(self.find_device(device_instance))
            .await;
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
            let specs = present_value_specs(&points)?;
            if specs.is_empty() {
                continue;
            }

            match self.poll_device(d, &specs).await {
                Ok(map) => {
                    for p in &points {
                        let Ok(ot) = parse_object_type(&p.object_type) else {
                            continue;
                        };
                        let Ok(oid) = ObjectIdentifier::new(ot, p.object_instance) else {
                            continue;
                        };
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
        let _discovery_port_guard = self.acquire_discovery_port(None).await;
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
        // Discovery can span a full object-list scan plus per-index repairs and
        // commandability probes. Admit one active scan and one waiter, then
        // arbitrate each BACnet service call below so interactive operations
        // remain responsive without allowing concurrent scan floods.
        let _admission = self
            .scan_admission
            .try_acquire()
            .map_err(|_| "BACnet scan queue full".to_string())?;
        let _active = self
            .scan_gate
            .acquire()
            .await
            .map_err(|_| "BACnet scan scheduler closed".to_string())?;
        self.point_discovery_impl(device_instance, false).await
    }

    async fn point_discovery_impl(
        &self,
        device_instance: u32,
        discovery_port_held: bool,
    ) -> Result<Value, String> {
        let device = self.find_device(device_instance);
        let _discovery_port_guard = if discovery_port_held {
            None
        } else {
            self.acquire_discovery_port(device).await
        };
        let client = self.new_client(device).await?;
        let result = async {
            self.prepare_scan(&client, device, device_instance).await?;
            let addr = self.resolve_address(&client, device, device_instance).await;

            let rpm_chunk = device.map_or(25, |d| d.rpm_chunk.max(1));
            let object_list = self
                .read_object_list(&client, device_instance, rpm_chunk)
                .await?;
            let oids: Vec<_> = object_list
                .objects
                .iter()
                .copied()
                .filter(|o| object_type_name(o.object_type()) != "device")
                .collect();

            let name_map = self
                .read_object_names(&client, device_instance, &oids)
                .await?;

            let mut commandability = HashMap::new();
            let candidates: Vec<_> = oids
                .iter()
                .filter(|o| COMMANDABLE_TYPES.contains(&object_type_name(o.object_type()).as_str()))
                .copied()
                .collect();
            for chunk in candidates.chunks(rpm_chunk) {
                for (oid, state) in self
                    .probe_commandability_batch(&client, device_instance, chunk)
                    .await
                {
                    commandability.insert(normalize_oid(&oid), state);
                }
            }

            let objects: Vec<_> = oids
                .iter()
                .map(|o| {
                    let oid_str = normalize_oid(o);
                    let state = commandability
                        .get(&oid_str)
                        .copied()
                        .unwrap_or_else(|| default_commandability(o.object_type()));
                    json!({
                        "object_identifier": oid_str,
                        "name": name_map.get(&oid_str).cloned().unwrap_or_else(|| json!("?")),
                        "commandable": state.is_supported(),
                        "commandability": state.as_str(),
                    })
                })
                .collect();

            Ok(json!({
                "device_address": addr,
                "device_instance": device_instance,
                "objects": objects,
                "object_list_complete": object_list.missing_indexes.is_empty()
                    && object_list.errors.is_empty(),
                "object_list_missing_indexes": object_list.missing_indexes,
                "object_list_errors": object_list.errors,
            }))
        }
        .await;
        Self::finish_client(client, result).await
    }

    async fn probe_commandability_batch(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oids: &[ObjectIdentifier],
    ) -> HashMap<ObjectIdentifier, Commandability> {
        let specs: Vec<_> = oids
            .iter()
            .map(|oid| ReadAccessSpecification {
                object_identifier: *oid,
                list_of_property_references: vec![PropertyReference {
                    property_identifier: PropertyIdentifier::PRIORITY_ARRAY,
                    property_array_index: Some(0),
                }],
            })
            .collect();
        let rpm_result = {
            let _guard = self.bus_lock.lock().await;
            client
                .read_property_multiple_from_device(device_instance, specs)
                .await
        };
        let rpm_states: HashMap<ObjectIdentifier, Commandability> = match rpm_result {
            Ok(response) => oids
                .iter()
                .map(|oid| (*oid, commandability_from_rpm_response(&response, *oid)))
                .collect(),
            Err(_) => oids
                .iter()
                .map(|oid| (*oid, Commandability::Unknown))
                .collect(),
        };

        let mut states = HashMap::new();
        for oid in oids {
            let rpm_state = rpm_states
                .get(oid)
                .copied()
                .unwrap_or(Commandability::Unknown);
            if rpm_state == Commandability::Supported {
                states.insert(*oid, rpm_state);
                continue;
            }

            // RPM can be unsupported or malformed while ordinary ReadProperty
            // still works. Probe the same object/index once before declaring
            // the commandability unknown; this is bounded to one repair read.
            let rp_result = {
                let _guard = self.bus_lock.lock().await;
                client
                    .read_property_from_device(
                        device_instance,
                        *oid,
                        PropertyIdentifier::PRIORITY_ARRAY,
                        Some(0),
                    )
                    .await
            };
            let state = commandability_from_priority_read_result(rp_result, *oid, rpm_state);
            states.insert(*oid, state);
        }
        states
    }

    async fn read_object_list(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        rpm_chunk: usize,
    ) -> Result<ObjectListRead, String> {
        let dev_oid = ObjectIdentifier::new(ObjectType::DEVICE, device_instance)
            .map_err(|e| e.to_string())?;
        let length_ack = {
            let _guard = self.bus_lock.lock().await;
            client
                .read_property_from_device(
                    device_instance,
                    dev_oid,
                    PropertyIdentifier::OBJECT_LIST,
                    Some(0),
                )
                .await
                .map_err(|e| e.to_string())?
        };
        let length_bytes = correlated_property_value(
            &length_ack,
            dev_oid,
            PropertyIdentifier::OBJECT_LIST,
            Some(0),
        )?;
        let length_pv = decode_complete_application_value(length_bytes)?;
        let length = match length_pv {
            PropertyValue::Unsigned(v) => usize::try_from(v)
                .map_err(|_| "object-list length exceeds platform limits".to_string())?,
            PropertyValue::Signed(v) if v >= 0 => v as usize,
            _ => return Err("unexpected object-list length type".into()),
        };
        const MAX_OBJECT_LIST_LENGTH: usize = 100_000;
        if length > MAX_OBJECT_LIST_LENGTH {
            return Err(format!(
                "object-list length {length} exceeds safety limit {MAX_OBJECT_LIST_LENGTH}"
            ));
        }

        let mut objects_by_index = HashMap::new();
        let mut missing_indexes = HashSet::new();
        let mut invalid_indexes = HashSet::new();
        let mut observed_indexes = HashSet::new();
        let mut errors = Vec::new();
        for (start, end) in rpm_chunk_ranges(length, rpm_chunk) {
            let idxs: Vec<u32> = (start..=end).map(|i| i as u32).collect();
            missing_indexes.extend(idxs.iter().copied());
            let expected: HashSet<u32> = idxs.iter().copied().collect();
            let specs = vec![object_list_index_spec(dev_oid, &idxs)];
            let rpm_result = {
                let _guard = self.bus_lock.lock().await;
                client
                    .read_property_multiple_from_device(device_instance, specs)
                    .await
            };
            match rpm_result {
                Ok(res) => {
                    for obj in &res.list_of_read_access_results {
                        if obj.object_identifier != dev_oid {
                            push_bounded_error(
                                &mut errors,
                                format!(
                                    "object-list RPM returned unexpected object {}",
                                    normalize_oid(&obj.object_identifier)
                                ),
                            );
                            continue;
                        }
                        for r in &obj.list_of_results {
                            let Some(index) = r.property_array_index else {
                                push_bounded_error(
                                    &mut errors,
                                    "object-list RPM result omitted array index".into(),
                                );
                                continue;
                            };
                            if !expected.contains(&index)
                                || r.property_identifier != PropertyIdentifier::OBJECT_LIST
                            {
                                push_bounded_error(
                                    &mut errors,
                                    format!(
                                        "object-list RPM returned invalid index/property {index}"
                                    ),
                                );
                                continue;
                            }
                            if invalid_indexes.contains(&index) {
                                continue;
                            }
                            if !observed_indexes.insert(index) {
                                invalidate_object_list_index(
                                    &mut objects_by_index,
                                    &mut missing_indexes,
                                    &mut invalid_indexes,
                                    &mut errors,
                                    index,
                                );
                                continue;
                            }
                            if let Some((class, code)) = r.error {
                                push_bounded_error(
                                    &mut errors,
                                    format!(
                                        "object-list index {index} error: class={class:?} code={code:?}"
                                    ),
                                );
                                continue;
                            }
                            let Some(bytes) = &r.property_value else {
                                push_bounded_error(
                                    &mut errors,
                                    format!("object-list index {index} omitted value"),
                                );
                                continue;
                            };
                            let Ok(PropertyValue::ObjectIdentifier(oid)) =
                                decode_complete_application_value(bytes)
                            else {
                                push_bounded_error(
                                    &mut errors,
                                    format!("object-list index {index} had malformed value"),
                                );
                                continue;
                            };
                            record_object_list_value(
                                &mut objects_by_index,
                                &mut missing_indexes,
                                &mut invalid_indexes,
                                &mut errors,
                                index,
                                oid,
                            );
                        }
                    }
                }
                Err(e) => {
                    push_bounded_error(
                        &mut errors,
                        format!("object-list RPM chunk {start}-{end} failed: {e}"),
                    );
                }
            }

            // Repair only indexes the RPM response proved missing or invalid.
            // The bound is the configured chunk, so a malformed response cannot
            // turn into an unbounded per-index request storm.
            let pending: Vec<u32> = missing_indexes
                .iter()
                .filter(|index| expected.contains(index))
                .copied()
                .collect();
            for index in pending {
                let repair_result = {
                    let _guard = self.bus_lock.lock().await;
                    client
                        .read_property_from_device(
                            device_instance,
                            dev_oid,
                            PropertyIdentifier::OBJECT_LIST,
                            Some(index),
                        )
                        .await
                };
                match repair_result {
                    Ok(ack) => match correlated_property_value(
                        &ack,
                        dev_oid,
                        PropertyIdentifier::OBJECT_LIST,
                        Some(index),
                    )
                    .and_then(decode_complete_application_value)
                    {
                        Ok(PropertyValue::ObjectIdentifier(oid)) => {
                            objects_by_index.insert(index, oid);
                            missing_indexes.remove(&index);
                            invalid_indexes.remove(&index);
                        }
                        Ok(other) => push_bounded_error(
                            &mut errors,
                            format!(
                                "object-list index {index} repair returned {}",
                                property_value_tag(&other)
                            ),
                        ),
                        Err(e) => push_bounded_error(
                            &mut errors,
                            format!("object-list index {index} repair decode failed: {e}"),
                        ),
                    },
                    Err(e) => push_bounded_error(
                        &mut errors,
                        format!("object-list index {index} repair failed: {e}"),
                    ),
                }
            }
        }
        let mut indexed: Vec<_> = objects_by_index.into_iter().collect();
        indexed.sort_by_key(|(index, _)| *index);
        let mut seen_objects = HashSet::new();
        let objects = indexed
            .into_iter()
            .filter_map(|(_, oid)| seen_objects.insert(oid).then_some(oid))
            .collect();
        let mut missing_indexes: Vec<_> = missing_indexes.into_iter().collect();
        missing_indexes.sort_unstable();
        Ok(ObjectListRead {
            objects,
            missing_indexes,
            errors,
        })
    }

    pub async fn read_priority_array(
        &self,
        device_instance: u32,
        object_type: &str,
        object_instance: u32,
    ) -> Result<Value, String> {
        let _discovery_port_guard = self
            .acquire_discovery_port(self.find_device(device_instance))
            .await;
        let _guard = self.bus_lock.lock().await;
        let device = self.find_device(device_instance);
        let ot = parse_object_type(object_type)?;
        let oid = ObjectIdentifier::new(ot, object_instance).map_err(|e| e.to_string())?;
        let client = self.new_client(device).await?;
        let result = async {
            self.prepare(&client, device, device_instance).await?;
            let slots = self
                .read_priority_slots_unarbitrated(&client, device_instance, oid)
                .await?;
            Ok(json!({
                "device_instance": device_instance,
                "object_identifier": normalize_oid(&oid),
                "priority_array": slots,
                "priority_array_state": priority_array_state(&slots),
            }))
        }
        .await;
        Self::finish_client(client, result).await
    }

    async fn read_priority_slots_unarbitrated(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oid: ObjectIdentifier,
    ) -> Result<Vec<Value>, String> {
        self.read_priority_slots_impl(client, device_instance, oid, false)
            .await
    }

    async fn read_priority_slots_scan(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oid: ObjectIdentifier,
    ) -> Result<Vec<Value>, String> {
        self.read_priority_slots_impl(client, device_instance, oid, true)
            .await
    }

    async fn read_priority_slots_impl(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oid: ObjectIdentifier,
        arbitrate: bool,
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
        let mut slots: Vec<Value> = (1..=16)
            .map(|level| priority_slot_unknown(level, "missing from RPM response"))
            .collect();
        let mut repair: HashSet<u32> = PRIORITY_LEVELS.collect();
        let mut seen = HashSet::new();
        let rpm_result = if arbitrate {
            let _guard = self.bus_lock.lock().await;
            client
                .read_property_multiple_from_device(device_instance, specs)
                .await
        } else {
            client
                .read_property_multiple_from_device(device_instance, specs)
                .await
        };
        match rpm_result {
            Ok(res) => {
                apply_priority_rpm_results(&mut slots, &mut repair, &mut seen, &res, oid);
            }
            Err(error) => {
                for slot in &mut slots {
                    slot["error"] = json!(format!("priority-array RPM failed: {error}"));
                }
            }
        }

        // Repair only the indexes that were absent, malformed, duplicated or
        // explicitly errored in the RPM response.  Every request is a single
        // ReadProperty, bounded to the fixed sixteen priority levels.
        for level in repair {
            let repair_result = if arbitrate {
                let _guard = self.bus_lock.lock().await;
                client
                    .read_property_from_device(
                        device_instance,
                        oid,
                        PropertyIdentifier::PRIORITY_ARRAY,
                        Some(level),
                    )
                    .await
            } else {
                client
                    .read_property_from_device(
                        device_instance,
                        oid,
                        PropertyIdentifier::PRIORITY_ARRAY,
                        Some(level),
                    )
                    .await
            };
            match repair_result {
                Ok(ack) => match correlated_property_value(
                    &ack,
                    oid,
                    PropertyIdentifier::PRIORITY_ARRAY,
                    Some(level),
                )
                .and_then(decode_complete_application_value)
                {
                    Ok(pv) => slots[(level - 1) as usize] = priority_slot_value(level, &pv),
                    Err(error) => {
                        let slot = &mut slots[(level - 1) as usize];
                        slot["repair_error"] = json!(format!(
                            "priority-array repair value decode failed: {error}"
                        ));
                    }
                },
                Err(error) => {
                    let slot = &mut slots[(level - 1) as usize];
                    slot["repair_error"] = json!(error.to_string());
                }
            }
        }
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
            let expected: HashSet<ObjectIdentifier> = chunk.iter().copied().collect();
            let rpm_result = {
                let _guard = self.bus_lock.lock().await;
                client
                    .read_property_multiple_from_device(device_instance, specs)
                    .await
            };
            match rpm_result {
                Ok(res) => {
                    for obj in res.list_of_read_access_results {
                        if !expected.contains(&obj.object_identifier) {
                            continue;
                        }
                        for r in obj.list_of_results {
                            if r.property_identifier != PropertyIdentifier::OBJECT_NAME
                                || r.property_array_index.is_some()
                                || r.error.is_some()
                            {
                                continue;
                            }
                            if let Some(bytes) = r.property_value {
                                if let Ok(PropertyValue::CharacterString(name)) =
                                    decode_complete_application_value(&bytes)
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
                    self.read_object_name_scan(client, device_instance, *oid)
                        .await
                        .unwrap_or_else(|| "?".into())
                };
                name_map.insert(oid_str, json!(name));
            }
        }

        Ok(name_map)
    }

    async fn read_object_name_scan(
        &self,
        client: &BACnetClient<bacnet_transport::bip::BipTransport>,
        device_instance: u32,
        oid: ObjectIdentifier,
    ) -> Option<String> {
        let result = {
            let _guard = self.bus_lock.lock().await;
            client
                .read_property_from_device(
                    device_instance,
                    oid,
                    PropertyIdentifier::OBJECT_NAME,
                    None,
                )
                .await
        };
        match result {
            Ok(ack) => correlated_property_value(&ack, oid, PropertyIdentifier::OBJECT_NAME, None)
                .and_then(decode_complete_application_value)
                .ok()
                .and_then(|pv| match pv {
                    PropertyValue::CharacterString(s) => Some(s),
                    _ => None,
                }),
            Err(_) => None,
        }
    }

    pub async fn supervisory_logic_check(&self, device_instance: u32) -> Result<Value, String> {
        // Supervisory audit calls point discovery and then reads P1-P16 for
        // each supported point. It shares the bounded scan scheduler with
        // point discovery and yields the bus between each network operation.
        let _admission = self
            .scan_admission
            .try_acquire()
            .map_err(|_| "BACnet scan queue full".to_string())?;
        let _active = self
            .scan_gate
            .acquire()
            .await
            .map_err(|_| "BACnet scan scheduler closed".to_string())?;
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
            .filter(|o| o["commandability"].as_str() == Some("supported"))
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
            self.prepare_scan(&client, device, device_instance).await?;

            let mut points = Vec::new();
            let mut overrides_by_oid: HashMap<String, Vec<Value>> = HashMap::new();
            let mut with_pa = 0usize;

            for o in &commandable {
                let Some(oid_str) = o["object_identifier"].as_str() else {
                    continue;
                };
                let mut parts = oid_str.split(',');
                let Some(type_name) = parts.next() else {
                    continue;
                };
                let Some(inst_text) = parts.next() else {
                    continue;
                };
                let Ok(inst) = inst_text.parse::<u32>() else {
                    continue;
                };
                let ot = parse_object_type(type_name)?;
                let oid = ObjectIdentifier::new(ot, inst).map_err(|e| e.to_string())?;
                let slots = self
                    .read_priority_slots_scan(&client, device_instance, oid)
                    .await?;
                let active: Vec<_> = slots
                    .iter()
                    .filter(|s| s["state"].as_str() == Some("value"))
                    .cloned()
                    .collect();
                if priority_array_state(&slots) == "supported" {
                    with_pa += 1;
                }
                for s in active {
                    let rec = json!({
                        "priority_level": s["priority_level"],
                        "object_identifier": oid_str,
                        "object_name": o["name"],
                        "state": s["state"],
                        "type": s["type"],
                        "value": s["value"],
                    });
                    points.push(rec.clone());
                    overrides_by_oid
                        .entry(oid_str.to_string())
                        .or_default()
                        .push(json!({
                            "priority_level": s["priority_level"],
                            "state": s["state"],
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

/// Present-value ReadPropertyMultiple specs for one poll cycle.
///
/// `poll_device` batches the returned slice with `rpm_request_chunks`.
fn present_value_specs(points: &[FieldPoint]) -> Result<Vec<ReadAccessSpecification>, String> {
    let mut specs = Vec::new();
    for p in points {
        let Ok(ot) = parse_object_type(&p.object_type) else {
            continue;
        };
        let oid = ObjectIdentifier::new(ot, p.object_instance).map_err(|e| e.to_string())?;
        specs.push(ReadAccessSpecification {
            object_identifier: oid,
            list_of_property_references: vec![PropertyReference {
                property_identifier: PropertyIdentifier::PRESENT_VALUE,
                property_array_index: None,
            }],
        });
    }
    Ok(specs)
}

/// Object-list RPM for one inclusive index window. Discovery uses the same
/// `rpm_chunk` as the poll path.
fn object_list_index_spec(dev_oid: ObjectIdentifier, indexes: &[u32]) -> ReadAccessSpecification {
    ReadAccessSpecification {
        object_identifier: dev_oid,
        list_of_property_references: indexes
            .iter()
            .map(|i| PropertyReference {
                property_identifier: PropertyIdentifier::OBJECT_LIST,
                property_array_index: Some(*i),
            })
            .collect(),
    }
}

/// Routed seed used by `seed_field_device`. Parses the router address and
/// copies `max_apdu` with segmentation none. It does not open a socket.
fn routed_device_config(d: &FieldDevice) -> Result<RoutedDeviceConfig, String> {
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
    Ok(RoutedDeviceConfig {
        instance: d.device_instance,
        router_mac: router_mac.to_vec(),
        remote_network: net,
        remote_mac: vec![dest_mac],
        max_apdu_length: d.max_apdu,
        segmentation_supported: Segmentation::NONE,
        max_segments_accepted: None,
    })
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

fn default_commandability(ot: ObjectType) -> Commandability {
    let name = object_type_name(ot);
    if NON_COMMANDABLE_TYPES.contains(&name.as_str()) {
        Commandability::Unsupported
    } else {
        // Candidate types are probed above. Proprietary or newly added types
        // have no safe inference from their object-type label alone.
        Commandability::Unknown
    }
}

fn normalize_oid(oid: &ObjectIdentifier) -> String {
    format!(
        "{},{}",
        object_type_name(oid.object_type()),
        oid.instance_number()
    )
}

fn correlated_property_value(
    ack: &bacnet_services::read_property::ReadPropertyACK,
    object_identifier: ObjectIdentifier,
    property_identifier: PropertyIdentifier,
    property_array_index: Option<u32>,
) -> Result<&[u8], String> {
    if ack.object_identifier != object_identifier {
        return Err(format!(
            "ReadPropertyACK object mismatch: expected {}, got {}",
            normalize_oid(&object_identifier),
            normalize_oid(&ack.object_identifier)
        ));
    }
    if ack.property_identifier != property_identifier {
        return Err(format!(
            "ReadPropertyACK property mismatch: expected {property_identifier:?}, got {:?}",
            ack.property_identifier
        ));
    }
    if ack.property_array_index != property_array_index {
        return Err(format!(
            "ReadPropertyACK array-index mismatch: expected {property_array_index:?}, got {:?}",
            ack.property_array_index
        ));
    }
    Ok(&ack.property_value)
}

fn decode_complete_application_value(bytes: &[u8]) -> Result<PropertyValue, String> {
    let (value, consumed) =
        decode_application_value(bytes, 0).map_err(|error| error.to_string())?;
    if consumed != bytes.len() {
        return Err(format!(
            "application value has trailing bytes: consumed {consumed} of {}",
            bytes.len()
        ));
    }
    Ok(value)
}

fn classify_write_error(error: &BacnetError) -> WriteOutcome {
    match error {
        BacnetError::Abort { reason } if *reason == AbortReason::TSM_TIMEOUT.to_raw() => {
            WriteOutcome::Unknown
        }
        BacnetError::Protocol { .. } | BacnetError::Reject { .. } | BacnetError::Abort { .. } => {
            WriteOutcome::Rejected
        }
        BacnetError::Encoding(_)
        | BacnetError::OutOfRange(_)
        | BacnetError::RoutedPathTooLong { .. }
        | BacnetError::RoutedPathCapacityExceeded { .. } => WriteOutcome::Failed,
        // Transport, timeout, segmentation and response-decoding failures are
        // ambiguous after dispatch.  They are never retried automatically.
        _ => WriteOutcome::Unknown,
    }
}

fn classify_write_error_result<T>(result: &Result<T, BacnetError>) -> WriteOutcome {
    match result {
        Ok(_) => WriteOutcome::Acknowledged,
        Err(error) => classify_write_error(error),
    }
}

async fn write_once<F, Fut>(attempts: &mut usize, send: F) -> Result<(), BacnetError>
where
    F: FnOnce() -> Fut,
    Fut: Future<Output = Result<(), BacnetError>>,
{
    *attempts += 1;
    send().await
}

fn is_unsupported_error_text(text: &str) -> bool {
    let normalized = text.to_ascii_lowercase().replace('_', "-");
    normalized.contains("unknown-property")
        || normalized.contains("property-is-not-supported")
        || normalized.contains("property-not-supported")
        || normalized.contains("property-is-not-an-array")
}

fn is_unsupported_bacnet_error(error: &BacnetError) -> bool {
    is_unsupported_error_text(&error.to_string())
}

fn commandability_from_error_codes(
    class: impl std::fmt::Debug,
    code: impl std::fmt::Debug,
) -> Commandability {
    if is_unsupported_error_text(&format!("{class:?} {code:?}")) {
        Commandability::Unsupported
    } else {
        Commandability::Unknown
    }
}

fn commandability_from_priority_value(value: &PropertyValue) -> Commandability {
    match value {
        // BACnet priority-array index 0 is the array length. A commandable
        // point must expose all sixteen priority slots; a decoded NULL,
        // Boolean, or arbitrary value is not evidence of commandability.
        PropertyValue::Unsigned(16) => Commandability::Supported,
        _ => Commandability::Unknown,
    }
}

fn write_readback_json(readback: &WriteReadback) -> Value {
    let mut value = json!({
        "property_value": property_value_to_json(&readback.property_value),
        "property_tag": property_value_tag(&readback.property_value),
        "effective_present_value": readback
            .effective_present_value
            .as_ref()
            .map(property_value_to_json),
        "effective_present_value_tag": readback
            .effective_present_value
            .as_ref()
            .map(property_value_tag),
        "masked": readback.masked,
        "winning_priority": readback.winning_priority,
    });
    if let Some(selected) = &readback.selected_priority {
        value["selected_priority"] = property_value_to_json(selected);
        value["selected_priority_tag"] = json!(property_value_tag(selected));
    }
    value
}

fn commandability_from_priority_ack(
    ack: &bacnet_services::read_property::ReadPropertyACK,
    oid: ObjectIdentifier,
) -> Commandability {
    let Ok(bytes) =
        correlated_property_value(ack, oid, PropertyIdentifier::PRIORITY_ARRAY, Some(0))
    else {
        return Commandability::Unknown;
    };
    let Ok(value) = decode_complete_application_value(bytes) else {
        return Commandability::Unknown;
    };
    commandability_from_priority_value(&value)
}

fn commandability_from_priority_read_result(
    result: Result<bacnet_services::read_property::ReadPropertyACK, BacnetError>,
    oid: ObjectIdentifier,
    fallback: Commandability,
) -> Commandability {
    match result {
        Ok(ack) => commandability_from_priority_ack(&ack, oid),
        Err(error) if is_unsupported_bacnet_error(&error) => Commandability::Unsupported,
        Err(_) => fallback,
    }
}

fn commandability_from_rpm_response(
    response: &bacnet_services::rpm::ReadPropertyMultipleACK,
    oid: ObjectIdentifier,
) -> Commandability {
    let mut observed_value: Option<PropertyValue> = None;
    let mut observed_error: Option<Commandability> = None;
    let mut found = false;

    for object in &response.list_of_read_access_results {
        if object.object_identifier != oid {
            return Commandability::Unknown;
        }
        for result in &object.list_of_results {
            found = true;
            if result.property_identifier != PropertyIdentifier::PRIORITY_ARRAY
                || result.property_array_index != Some(0)
            {
                return Commandability::Unknown;
            }
            if let Some((class, code)) = result.error {
                if observed_value.is_some() {
                    return Commandability::Unknown;
                }
                let state = commandability_from_error_codes(class, code);
                if observed_error.is_some_and(|previous| previous != state) {
                    return Commandability::Unknown;
                }
                observed_error = Some(state);
                continue;
            }

            let Some(bytes) = result.property_value.as_deref() else {
                return Commandability::Unknown;
            };
            let Ok(value) = decode_complete_application_value(bytes) else {
                return Commandability::Unknown;
            };
            if commandability_from_priority_value(&value) != Commandability::Supported {
                return Commandability::Unknown;
            }
            if observed_error.is_some() {
                return Commandability::Unknown;
            }
            if observed_value
                .as_ref()
                .is_some_and(|previous| previous != &value)
            {
                return Commandability::Unknown;
            }
            observed_value = Some(value);
        }
    }

    if observed_value.is_some() {
        Commandability::Supported
    } else if found {
        observed_error.unwrap_or(Commandability::Unknown)
    } else {
        Commandability::Unknown
    }
}

fn priority_slot_value(level: u32, value: &PropertyValue) -> Value {
    let tag = property_value_tag(value);
    json!({
        "priority_level": level,
        "state": if tag == "null" { "null" } else { "value" },
        "type": tag,
        "value": property_value_to_json(value),
    })
}

fn priority_slot_unknown(level: u32, reason: &str) -> Value {
    json!({
        "priority_level": level,
        "state": "unknown",
        "type": "unknown",
        "value": Value::Null,
        "error": reason,
    })
}

fn priority_slot_error(level: u32, reason: &str, kind: &str) -> Value {
    json!({
        "priority_level": level,
        "state": "error",
        "type": "error",
        "value": Value::Null,
        "error": reason,
        "error_kind": kind,
    })
}

fn apply_priority_rpm_results(
    slots: &mut [Value],
    repair: &mut HashSet<u32>,
    seen: &mut HashSet<u32>,
    response: &bacnet_services::rpm::ReadPropertyMultipleACK,
    oid: ObjectIdentifier,
) {
    for object in &response.list_of_read_access_results {
        if object.object_identifier != oid {
            continue;
        }
        for result in &object.list_of_results {
            if result.property_identifier != PropertyIdentifier::PRIORITY_ARRAY {
                continue;
            }
            let Some(level) = result.property_array_index else {
                continue;
            };
            if !PRIORITY_LEVELS.contains(&level) {
                continue;
            }
            let slot = &mut slots[(level - 1) as usize];
            if !seen.insert(level) {
                *slot = priority_slot_error(level, "duplicate priority-array result", "unknown");
                repair.insert(level);
                continue;
            }
            if let Some((class, code)) = result.error {
                let kind = commandability_from_error_codes(class, code);
                *slot = priority_slot_error(
                    level,
                    &format!("Error: class={class:?} code={code:?}"),
                    if kind == Commandability::Unsupported {
                        "unsupported"
                    } else {
                        "unknown"
                    },
                );
                repair.insert(level);
            } else if let Some(bytes) = &result.property_value {
                match decode_complete_application_value(bytes) {
                    Ok(pv) => {
                        *slot = priority_slot_value(level, &pv);
                        repair.remove(&level);
                    }
                    Err(error) => {
                        *slot = priority_slot_error(
                            level,
                            &format!("priority-array value decode failed: {error}"),
                            "unknown",
                        );
                        repair.insert(level);
                    }
                }
            } else {
                *slot = priority_slot_unknown(level, "RPM result omitted value");
                repair.insert(level);
            }
        }
    }
}

fn priority_array_state(slots: &[Value]) -> &'static str {
    if slots
        .iter()
        .any(|slot| matches!(slot["state"].as_str(), Some("value" | "null")))
    {
        return "supported";
    }
    if slots
        .iter()
        .any(|slot| slot["error_kind"].as_str() == Some("unsupported"))
    {
        return "unsupported";
    }
    "unknown"
}

fn push_bounded_error(errors: &mut Vec<String>, message: String) {
    const MAX_DIAGNOSTIC_ERRORS: usize = 64;
    if errors.len() < MAX_DIAGNOSTIC_ERRORS {
        errors.push(message);
    }
}

fn record_object_list_value(
    objects_by_index: &mut HashMap<u32, ObjectIdentifier>,
    missing_indexes: &mut HashSet<u32>,
    invalid_indexes: &mut HashSet<u32>,
    errors: &mut Vec<String>,
    index: u32,
    oid: ObjectIdentifier,
) {
    // Once an index has produced a duplicate, every later RPM value for that
    // index remains untrusted. Only the correlated ReadProperty repair may
    // clear the pending/invalid state.
    if invalid_indexes.contains(&index) {
        return;
    }
    if objects_by_index.insert(index, oid).is_some() {
        invalidate_object_list_index(
            objects_by_index,
            missing_indexes,
            invalid_indexes,
            errors,
            index,
        );
        return;
    }
    missing_indexes.remove(&index);
}

fn invalidate_object_list_index(
    objects_by_index: &mut HashMap<u32, ObjectIdentifier>,
    missing_indexes: &mut HashSet<u32>,
    invalid_indexes: &mut HashSet<u32>,
    errors: &mut Vec<String>,
    index: u32,
) {
    objects_by_index.remove(&index);
    missing_indexes.insert(index);
    if invalid_indexes.insert(index) {
        push_bounded_error(errors, format!("object-list index {index} was duplicated"));
    }
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
    use bacnet_encoding::primitives::encode_property_value;
    use bytes::BytesMut;

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

    fn unsegmented_rpm_request_apdu_len(specs: &[ReadAccessSpecification]) -> usize {
        let mut service = BytesMut::new();
        bacnet_services::rpm::ReadPropertyMultipleRequest {
            list_of_read_access_specs: specs.to_vec(),
        }
        .encode(&mut service);
        // Confirmed-request header is 4 octets before the service payload.
        4 + service.len()
    }

    fn unsegmented_present_value_ack_apdu_len(specs: &[ReadAccessSpecification]) -> usize {
        let mut service = BytesMut::new();
        let ack = bacnet_services::rpm::ReadPropertyMultipleACK {
            list_of_read_access_results: specs
                .iter()
                .map(|spec| {
                    let mut value = BytesMut::new();
                    encode_property_value(&mut value, &PropertyValue::Real(0.0))
                        .expect("real present-value encodes");
                    bacnet_services::rpm::ReadAccessResult {
                        object_identifier: spec.object_identifier,
                        list_of_results: vec![bacnet_services::rpm::ReadResultElement {
                            property_identifier: PropertyIdentifier::PRESENT_VALUE,
                            property_array_index: None,
                            property_value: Some(value.to_vec()),
                            error: None,
                        }],
                    }
                })
                .collect(),
        };
        ack.encode(&mut service);
        // Complex-ACK header is 3 octets (type, invoke id, service choice).
        3 + service.len()
    }

    #[test]
    fn poll_rpm_path_uses_configured_chunk_for_206_byte_profile() {
        // JCI FEC device class, instance 5007: routed, 206-byte APDU, no
        // segmentation, rpm_chunk 10. The host is documentation-only TEST-NET;
        // this test never opens a socket.
        const FEC_OBJECTS: u32 = 65;
        let points: Vec<_> = (1..=FEC_OBJECTS)
            .map(|instance| FieldPoint {
                object_type: "analog-input".into(),
                object_instance: instance,
                point_name: format!("ai-{instance}"),
                units: "°F".into(),
            })
            .collect();
        let mut fec = dev("jci-fec-5007", 5007, points);
        fec.rpm_chunk = 10;
        fec.max_apdu = 206;
        fec.mstp_network = Some(2001);
        fec.mstp_mac = vec![7];
        fec.host = "192.0.2.50".into();
        assert!(fec.is_routed());

        let seeded = routed_device_config(&fec).expect("fec seed");
        assert_eq!(seeded.instance, 5007);
        assert_eq!(seeded.max_apdu_length, 206);
        assert_eq!(seeded.segmentation_supported, Segmentation::NONE);
        assert_eq!(seeded.max_segments_accepted, None);
        assert_eq!(seeded.remote_network, 2001);
        assert_eq!(seeded.remote_mac, vec![7]);

        let specs = present_value_specs(&fec.points).expect("present-value specs");
        assert_eq!(specs.len(), FEC_OBJECTS as usize);
        let requests = rpm_request_chunks(&specs, fec.rpm_chunk);
        assert_eq!(
            requests.iter().map(|r| r.len()).collect::<Vec<_>>(),
            vec![10, 10, 10, 10, 10, 10, 5]
        );
        let max_apdu = fec.max_apdu as usize;
        for chunk in &requests {
            let request_len = unsegmented_rpm_request_apdu_len(chunk);
            let ack_len = unsegmented_present_value_ack_apdu_len(chunk);
            assert!(
                request_len <= max_apdu,
                "poll chunk request {request_len} exceeds max APDU {max_apdu}"
            );
            assert!(
                ack_len <= max_apdu,
                "poll chunk ack {ack_len} exceeds max APDU {max_apdu}"
            );
        }
        let whole_ack = unsegmented_present_value_ack_apdu_len(&specs);
        assert!(
            whole_ack > max_apdu,
            "unchunked FEC catalog ack {whole_ack} must exceed the 206-byte profile"
        );
        let default_chunk = rpm_request_chunks(&specs, 25);
        assert!(default_chunk
            .iter()
            .any(|chunk| { unsegmented_present_value_ack_apdu_len(chunk) > max_apdu }));

        // Twenty-five specs still split 10/10/5, which is the planner poll_device uses.
        let twenty_five = rpm_request_chunks(&specs[..25], fec.rpm_chunk);
        assert_eq!(
            twenty_five.iter().map(|r| r.len()).collect::<Vec<_>>(),
            vec![10, 10, 5]
        );
        assert_eq!(twenty_five[0][0].object_identifier.instance_number(), 1);
        assert_eq!(twenty_five[2][4].object_identifier.instance_number(), 25);

        let dev_oid = ObjectIdentifier::new(ObjectType::DEVICE, fec.device_instance).unwrap();
        for (start, end) in rpm_chunk_ranges(FEC_OBJECTS as usize, fec.rpm_chunk) {
            let idxs: Vec<u32> = (start as u32..=end as u32).collect();
            let spec = object_list_index_spec(dev_oid, &idxs);
            let request_len = unsegmented_rpm_request_apdu_len(std::slice::from_ref(&spec));
            assert!(
                request_len <= max_apdu,
                "object-list chunk {start}-{end} request {request_len} exceeds max APDU"
            );
        }
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

#[cfg(test)]
#[path = "bacnet_client_tests.rs"]
mod bacnet_correctness_tests;
