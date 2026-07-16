//! BACnetClient: high-level and low-level request APIs.
//!
//! The client owns a NetworkLayer, spawns an APDU dispatch task, and provides
//! methods for sending confirmed and unconfirmed BACnet requests.

use std::collections::HashMap;
use std::net::Ipv4Addr;
#[cfg(feature = "ipv6")]
use std::net::Ipv6Addr;
use std::sync::Arc;
use std::time::Instant;

use bytes::{Bytes, BytesMut};
use tokio::sync::{broadcast, mpsc, Mutex};
use tokio::task::JoinHandle;
use tokio::time::{timeout, Duration};
use tracing::{debug, warn};

use bacnet_encoding::apdu::{
    self, encode_apdu, validate_max_apdu_length, AbortPdu, Apdu,
    ConfirmedRequest as ConfirmedRequestPdu, SegmentAck as SegmentAckPdu, SimpleAck,
};
use bacnet_encoding::npdu::NpduAddress;
use bacnet_network::layer::NetworkLayer;
use bacnet_services::cov::COVNotificationRequest;
use bacnet_transport::bip::BipTransport;
#[cfg(feature = "ipv6")]
use bacnet_transport::bip6::Bip6Transport;
use bacnet_transport::port::TransportPort;
use bacnet_types::enums::{ConfirmedServiceChoice, NetworkPriority, UnconfirmedServiceChoice};
use bacnet_types::error::Error;
use bacnet_types::MacAddr;

use crate::discovery::{DeviceTable, DiscoveredDevice};
use crate::segmentation::{max_segment_payload, split_payload, SegmentReceiver, SegmentedPduType};
use crate::tsm::{Tsm, TsmConfig, TsmResponse};

/// Client configuration.
#[derive(Debug, Clone)]
pub struct ClientConfig {
    /// Local interface to bind.
    pub interface: Ipv4Addr,
    /// UDP port (0 for ephemeral).
    pub port: u16,
    /// Directed broadcast address.
    pub broadcast_address: Ipv4Addr,
    /// APDU timeout in milliseconds.
    pub apdu_timeout_ms: u64,
    /// Number of APDU retries.
    pub apdu_retries: u8,
    /// Maximum APDU length this client accepts.
    pub max_apdu_length: u16,
    /// Maximum segments this client accepts (None = unspecified).
    pub max_segments: Option<u8>,
    /// Whether this client accepts segmented responses.
    pub segmented_response_accepted: bool,
    /// Proposed window size for segmented transfers (1-127, default 1).
    pub proposed_window_size: u8,
}

impl Default for ClientConfig {
    fn default() -> Self {
        Self {
            interface: Ipv4Addr::UNSPECIFIED,
            port: 0xBAC0,
            broadcast_address: Ipv4Addr::BROADCAST,
            apdu_timeout_ms: 6000,
            apdu_retries: 3,
            max_apdu_length: 1476,
            max_segments: None,
            segmented_response_accepted: true,
            proposed_window_size: 1,
        }
    }
}

/// Generic builder for BACnetClient with a pre-built transport.
pub struct ClientBuilder<T: TransportPort> {
    config: ClientConfig,
    transport: Option<T>,
}

impl<T: TransportPort + 'static> ClientBuilder<T> {
    /// Set the pre-built transport.
    pub fn transport(mut self, transport: T) -> Self {
        self.transport = Some(transport);
        self
    }

    /// Set APDU timeout in milliseconds.
    pub fn apdu_timeout_ms(mut self, ms: u64) -> Self {
        self.config.apdu_timeout_ms = ms;
        self
    }

    /// Set the maximum APDU length this client accepts.
    pub fn max_apdu_length(mut self, len: u16) -> Self {
        self.config.max_apdu_length = len;
        self
    }

    /// Build and start the client.
    pub async fn build(self) -> Result<BACnetClient<T>, Error> {
        let transport = self
            .transport
            .ok_or_else(|| Error::Encoding("transport not set on ClientBuilder".into()))?;
        BACnetClient::start(self.config, transport).await
    }
}

/// BIP-specific builder that constructs `BipTransport` from interface/port/broadcast fields.
pub struct BipClientBuilder {
    config: ClientConfig,
}

impl BipClientBuilder {
    /// Set the local interface IP.
    pub fn interface(mut self, ip: Ipv4Addr) -> Self {
        self.config.interface = ip;
        self
    }

    /// Set the UDP port (0 for ephemeral).
    pub fn port(mut self, port: u16) -> Self {
        self.config.port = port;
        self
    }

    /// Set the directed broadcast address.
    pub fn broadcast_address(mut self, addr: Ipv4Addr) -> Self {
        self.config.broadcast_address = addr;
        self
    }

    /// Set APDU timeout in milliseconds.
    pub fn apdu_timeout_ms(mut self, ms: u64) -> Self {
        self.config.apdu_timeout_ms = ms;
        self
    }

    /// Set the maximum APDU length this client accepts.
    pub fn max_apdu_length(mut self, len: u16) -> Self {
        self.config.max_apdu_length = len;
        self
    }

    /// Build and start the client, constructing a BipTransport from the config.
    pub async fn build(self) -> Result<BACnetClient<BipTransport>, Error> {
        let transport = BipTransport::new(
            self.config.interface,
            self.config.port,
            self.config.broadcast_address,
        );
        BACnetClient::start(self.config, transport).await
    }
}

// ---------------------------------------------------------------------------
// Multi-device batch operation types
// ---------------------------------------------------------------------------

/// Default concurrency limit for multi-device batch operations.
const DEFAULT_BATCH_CONCURRENCY: usize = 32;

/// A request to read a single property from a discovered device.
#[derive(Debug, Clone)]
pub struct DeviceReadRequest {
    /// Device instance number (must be in the device table).
    pub device_instance: u32,
    /// Object to read from.
    pub object_identifier: bacnet_types::primitives::ObjectIdentifier,
    /// Property to read.
    pub property_identifier: bacnet_types::enums::PropertyIdentifier,
    /// Optional array index.
    pub property_array_index: Option<u32>,
}

/// Result of a single-property read from a device within a batch.
#[derive(Debug)]
pub struct DeviceReadResult {
    /// The device instance this result corresponds to.
    pub device_instance: u32,
    /// The read result (Ok = decoded ACK, Err = protocol/timeout error).
    pub result: Result<bacnet_services::read_property::ReadPropertyACK, Error>,
}

/// A request to read multiple properties from a discovered device (RPM).
#[derive(Debug, Clone)]
pub struct DeviceRpmRequest {
    /// Device instance number (must be in the device table).
    pub device_instance: u32,
    /// ReadAccessSpecifications to send in a single RPM.
    pub specs: Vec<bacnet_services::rpm::ReadAccessSpecification>,
}

/// Result of an RPM to a single device within a batch.
#[derive(Debug)]
pub struct DeviceRpmResult {
    /// The device instance this result corresponds to.
    pub device_instance: u32,
    /// The RPM result.
    pub result: Result<bacnet_services::rpm::ReadPropertyMultipleACK, Error>,
}

/// A request to write a single property on a discovered device.
#[derive(Debug, Clone)]
pub struct DeviceWriteRequest {
    /// Device instance number (must be in the device table).
    pub device_instance: u32,
    /// Object to write to.
    pub object_identifier: bacnet_types::primitives::ObjectIdentifier,
    /// Property to write.
    pub property_identifier: bacnet_types::enums::PropertyIdentifier,
    /// Optional array index.
    pub property_array_index: Option<u32>,
    /// Encoded property value bytes.
    pub property_value: Vec<u8>,
    /// Optional write priority (1-16).
    pub priority: Option<u8>,
}

/// Result of a single-property write to a device within a batch.
#[derive(Debug)]
pub struct DeviceWriteResult {
    /// The device instance this result corresponds to.
    pub device_instance: u32,
    /// The write result (Ok = success, Err = protocol/timeout error).
    pub result: Result<(), Error>,
}

/// In-progress segmented receive state.
struct SegmentedReceiveState {
    receiver: SegmentReceiver,
    /// Immediate MAC used to send SegmentAck/Abort PDUs.
    reply_mac: MacAddr,
    /// Next expected sequence number (for gap detection).
    expected_next_seq: u8,
    /// Timestamp of last received segment (for reaping stale sessions).
    last_activity: Instant,
    /// Window position counter for per-window SegmentAck (Clause 5.2.2).
    window_position: u8,
    /// Proposed window size from the server.
    proposed_window_size: u8,
}

/// Timeout for idle segmented reassembly sessions.
const SEG_RECEIVER_TIMEOUT: Duration = Duration::from_secs(4);

/// Key for tracking in-progress segmented receives: (correlation_mac, invoke_id).
type SegKey = (MacAddr, u8);

/// BACnet client with low-level and high-level request APIs.
pub struct BACnetClient<T: TransportPort> {
    config: ClientConfig,
    network: Arc<NetworkLayer<T>>,
    tsm: Arc<Mutex<Tsm>>,
    device_table: Arc<Mutex<DeviceTable>>,
    cov_tx: broadcast::Sender<COVNotificationRequest>,
    dispatch_task: Option<JoinHandle<()>>,
    seg_ack_senders: Arc<Mutex<HashMap<SegKey, mpsc::Sender<SegmentAckPdu>>>>,
    local_mac: MacAddr,
}

impl BACnetClient<BipTransport> {
    /// Create a BIP-specific builder with interface/port/broadcast fields.
    pub fn bip_builder() -> BipClientBuilder {
        BipClientBuilder {
            config: ClientConfig::default(),
        }
    }

    pub fn builder() -> BipClientBuilder {
        Self::bip_builder()
    }

    /// Read the Broadcast Distribution Table from a BBMD.
    pub async fn read_bdt(
        &self,
        target: &[u8],
    ) -> Result<Vec<bacnet_transport::bbmd::BdtEntry>, Error> {
        self.network.transport().read_bdt(target).await
    }

    /// Write the Broadcast Distribution Table to a BBMD.
    pub async fn write_bdt(
        &self,
        target: &[u8],
        entries: &[bacnet_transport::bbmd::BdtEntry],
    ) -> Result<bacnet_types::enums::BvlcResultCode, Error> {
        self.network.transport().write_bdt(target, entries).await
    }

    /// Read the Foreign Device Table from a BBMD.
    pub async fn read_fdt(
        &self,
        target: &[u8],
    ) -> Result<Vec<bacnet_transport::bbmd::FdtEntryWire>, Error> {
        self.network.transport().read_fdt(target).await
    }

    /// Delete a Foreign Device Table entry on a BBMD.
    pub async fn delete_fdt_entry(
        &self,
        target: &[u8],
        ip: [u8; 4],
        port: u16,
    ) -> Result<bacnet_types::enums::BvlcResultCode, Error> {
        self.network
            .transport()
            .delete_fdt_entry(target, ip, port)
            .await
    }

    /// Register as a foreign device with a BBMD and return the result code.
    pub async fn register_foreign_device_bvlc(
        &self,
        target: &[u8],
        ttl: u16,
    ) -> Result<bacnet_types::enums::BvlcResultCode, Error> {
        self.network
            .transport()
            .register_foreign_device_bvlc(target, ttl)
            .await
    }
}

#[cfg(feature = "ipv6")]
impl BACnetClient<Bip6Transport> {
    /// Create a BIP6-specific builder for BACnet/IPv6 transport.
    pub fn bip6_builder() -> Bip6ClientBuilder {
        Bip6ClientBuilder {
            config: ClientConfig::default(),
            interface: Ipv6Addr::UNSPECIFIED,
            device_instance: None,
        }
    }
}

/// BIP6-specific builder that constructs `Bip6Transport` from IPv6 interface/port/device-instance.
#[cfg(feature = "ipv6")]
pub struct Bip6ClientBuilder {
    config: ClientConfig,
    interface: Ipv6Addr,
    device_instance: Option<u32>,
}

#[cfg(feature = "ipv6")]
impl Bip6ClientBuilder {
    /// Set the local IPv6 interface address.
    pub fn interface(mut self, ip: Ipv6Addr) -> Self {
        self.interface = ip;
        self
    }

    /// Set the UDP port (0 for ephemeral).
    pub fn port(mut self, port: u16) -> Self {
        self.config.port = port;
        self
    }

    /// Set the device instance for VMAC derivation (Annex U.5).
    pub fn device_instance(mut self, instance: u32) -> Self {
        self.device_instance = Some(instance);
        self
    }

    /// Set APDU timeout in milliseconds.
    pub fn apdu_timeout_ms(mut self, ms: u64) -> Self {
        self.config.apdu_timeout_ms = ms;
        self
    }

    /// Set the maximum APDU length this client accepts.
    pub fn max_apdu_length(mut self, len: u16) -> Self {
        self.config.max_apdu_length = len;
        self
    }

    /// Build and start the client, constructing a Bip6Transport from the config.
    pub async fn build(self) -> Result<BACnetClient<Bip6Transport>, Error> {
        let transport = Bip6Transport::new(self.interface, self.config.port, self.device_instance);
        BACnetClient::start(self.config, transport).await
    }
}

#[cfg(feature = "sc-tls")]
impl BACnetClient<bacnet_transport::sc::ScTransport<bacnet_transport::sc_tls::TlsWebSocket>> {
    /// Create an SC-specific builder that connects to a BACnet/SC hub.
    pub fn sc_builder() -> ScClientBuilder {
        ScClientBuilder {
            config: ClientConfig::default(),
            hub_url: String::new(),
            tls_config: None,
            vmac: [0; 6],
            heartbeat_interval_ms: 30_000,
            heartbeat_timeout_ms: 60_000,
            reconnect: None,
        }
    }
}

/// SC-specific client builder.
///
/// Created by [`BACnetClient::sc_builder()`].  Requires the `sc-tls` feature.
#[cfg(feature = "sc-tls")]
pub struct ScClientBuilder {
    config: ClientConfig,
    hub_url: String,
    tls_config: Option<std::sync::Arc<tokio_rustls::rustls::ClientConfig>>,
    vmac: bacnet_transport::sc_frame::Vmac,
    heartbeat_interval_ms: u64,
    heartbeat_timeout_ms: u64,
    reconnect: Option<bacnet_transport::sc::ScReconnectConfig>,
}

#[cfg(feature = "sc-tls")]
impl ScClientBuilder {
    /// Set the hub WebSocket URL (e.g. `wss://hub.example.com/bacnet`).
    pub fn hub_url(mut self, url: &str) -> Self {
        self.hub_url = url.to_string();
        self
    }

    /// Set the TLS client configuration.
    pub fn tls_config(
        mut self,
        config: std::sync::Arc<tokio_rustls::rustls::ClientConfig>,
    ) -> Self {
        self.tls_config = Some(config);
        self
    }

    /// Set the local VMAC address.
    pub fn vmac(mut self, vmac: [u8; 6]) -> Self {
        self.vmac = vmac;
        self
    }

    /// Set the APDU timeout in milliseconds.
    pub fn apdu_timeout_ms(mut self, ms: u64) -> Self {
        self.config.apdu_timeout_ms = ms;
        self
    }

    /// Set the heartbeat interval in milliseconds (default 30 000).
    pub fn heartbeat_interval_ms(mut self, ms: u64) -> Self {
        self.heartbeat_interval_ms = ms;
        self
    }

    /// Set the heartbeat timeout in milliseconds (default 60 000).
    pub fn heartbeat_timeout_ms(mut self, ms: u64) -> Self {
        self.heartbeat_timeout_ms = ms;
        self
    }

    /// Enable automatic reconnection with the given configuration.
    pub fn reconnect(mut self, config: bacnet_transport::sc::ScReconnectConfig) -> Self {
        self.reconnect = Some(config);
        self
    }

    /// Connect to the hub and start the client.
    pub async fn build(
        self,
    ) -> Result<
        BACnetClient<bacnet_transport::sc::ScTransport<bacnet_transport::sc_tls::TlsWebSocket>>,
        Error,
    > {
        let tls_config = self
            .tls_config
            .ok_or_else(|| Error::Encoding("SC client builder: tls_config is required".into()))?;

        let ws = bacnet_transport::sc_tls::TlsWebSocket::connect(&self.hub_url, tls_config).await?;

        let mut transport = bacnet_transport::sc::ScTransport::new(ws, self.vmac)
            .with_heartbeat_interval_ms(self.heartbeat_interval_ms)
            .with_heartbeat_timeout_ms(self.heartbeat_timeout_ms);
        if let Some(rc) = self.reconnect {
            #[allow(deprecated)]
            {
                transport = transport.with_reconnect(rc);
            }
        }

        BACnetClient::start(self.config, transport).await
    }
}

/// Routing target for confirmed requests.
#[derive(Clone, Copy)]
enum ConfirmedTarget<'a> {
    Local {
        mac: &'a [u8],
    },
    Routed {
        router_mac: &'a [u8],
        dest_network: u16,
        dest_mac: &'a [u8],
    },
}

impl<'a> ConfirmedTarget<'a> {
    /// The key used for TSM transaction matching.
    fn tsm_mac(&self) -> MacAddr {
        match self {
            Self::Local { mac } => MacAddr::from_slice(mac),
            Self::Routed {
                dest_network,
                dest_mac,
                ..
            } => routed_tsm_mac(*dest_network, dest_mac),
        }
    }
}

fn routed_tsm_mac(network: u16, mac: &[u8]) -> MacAddr {
    let mut key = MacAddr::new();
    key.extend_from_slice(&[0xFF, b'R']);
    key.extend_from_slice(&network.to_be_bytes());
    key.push(mac.len() as u8);
    key.extend_from_slice(mac);
    key
}

fn response_tsm_mac(source_mac: &[u8], source_network: &Option<NpduAddress>) -> MacAddr {
    match source_network {
        Some(address) if !address.mac_address.is_empty() => {
            routed_tsm_mac(address.network, &address.mac_address)
        }
        _ => MacAddr::from_slice(source_mac),
    }
}

mod cov;
mod device_mgmt;
mod discovery;
mod dispatch;
mod file_list;
mod lifecycle;
mod object_mgmt;
mod property;
mod requests;
mod segmentation;

#[cfg(test)]
mod tests;

impl<T: TransportPort + 'static> BACnetClient<T> {
    /// Create a generic builder that accepts a pre-built transport.
    pub fn generic_builder() -> ClientBuilder<T> {
        ClientBuilder {
            config: ClientConfig::default(),
            transport: None,
        }
    }
}
