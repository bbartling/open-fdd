use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    /// Resolve a device instance to its MAC address and optional routing info.
    pub(super) async fn resolve_device(
        &self,
        device_instance: u32,
    ) -> Result<(Vec<u8>, Option<(u16, Vec<u8>)>), Error> {
        let dt = self.device_table.lock().await;
        let device = dt.get(device_instance).ok_or_else(|| {
            Error::Encoding(format!("device {device_instance} not in device table"))
        })?;
        let routing = match (&device.source_network, &device.source_address) {
            (Some(snet), Some(sadr)) => Some((*snet, sadr.to_vec())),
            _ => None,
        };
        Ok((device.mac_address.to_vec(), routing))
    }

    // -----------------------------------------------------------------------
    // Multi-device batch operations
    // -----------------------------------------------------------------------

    /// Read a property from multiple discovered devices concurrently.
    ///
    /// All requests are dispatched concurrently (up to `max_concurrent`,
    /// default 32) and results are returned in completion order. Each device
    /// is resolved from the device table and auto-routed if behind a router.
    /// Send a WhoIs broadcast to discover devices.
    pub async fn who_is(
        &self,
        low_limit: Option<u32>,
        high_limit: Option<u32>,
    ) -> Result<(), Error> {
        use bacnet_services::who_is::WhoIsRequest;

        let request = WhoIsRequest {
            low_limit,
            high_limit,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        self.broadcast_global_unconfirmed(UnconfirmedServiceChoice::WHO_IS, &buf)
            .await
    }

    /// Send a directed (unicast) WhoIs to a specific device.
    pub async fn who_is_directed(
        &self,
        destination_mac: &[u8],
        low_limit: Option<u32>,
        high_limit: Option<u32>,
    ) -> Result<(), Error> {
        use bacnet_services::who_is::WhoIsRequest;

        let request = WhoIsRequest {
            low_limit,
            high_limit,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        self.unconfirmed_request(destination_mac, UnconfirmedServiceChoice::WHO_IS, &buf)
            .await
    }

    /// Send a WhoIs broadcast to a specific remote network.
    pub async fn who_is_network(
        &self,
        dest_network: u16,
        low_limit: Option<u32>,
        high_limit: Option<u32>,
    ) -> Result<(), Error> {
        use bacnet_services::who_is::WhoIsRequest;

        let request = WhoIsRequest {
            low_limit,
            high_limit,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        self.broadcast_network_unconfirmed(UnconfirmedServiceChoice::WHO_IS, &buf, dest_network)
            .await
    }

    /// Send a WhoHas broadcast to find an object by identifier or name.
    pub async fn who_has(
        &self,
        object: bacnet_services::who_has::WhoHasObject,
        low_limit: Option<u32>,
        high_limit: Option<u32>,
    ) -> Result<(), Error> {
        use bacnet_services::who_has::WhoHasRequest;

        let request = WhoHasRequest {
            low_limit,
            high_limit,
            object,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf)?;

        self.broadcast_unconfirmed(UnconfirmedServiceChoice::WHO_HAS, &buf)
            .await
    }

    /// Subscribe to COV notifications for an object on a remote device.
    /// Get a snapshot of all discovered devices.
    pub async fn discovered_devices(&self) -> Vec<DiscoveredDevice> {
        self.device_table.lock().await.all()
    }

    /// Look up a discovered device by instance number.
    pub async fn get_device(&self, instance: u32) -> Option<DiscoveredDevice> {
        self.device_table.lock().await.get(instance).cloned()
    }

    /// Clear the discovered devices table.
    pub async fn clear_devices(&self) {
        self.device_table.lock().await.clear();
    }

    /// Manually register a device in the device table.
    ///
    /// Useful for adding known devices without requiring WhoIs/IAm exchange.
    /// Sets default values for max_apdu_length (1476), segmentation (NONE),
    /// and vendor_id (0) since these are unknown without IAm.
    pub async fn add_device(&self, instance: u32, mac: &[u8]) -> Result<(), Error> {
        let oid = bacnet_types::primitives::ObjectIdentifier::new(
            bacnet_types::enums::ObjectType::DEVICE,
            instance,
        )?;
        let device = DiscoveredDevice {
            object_identifier: oid,
            mac_address: MacAddr::from_slice(mac),
            max_apdu_length: 1476,
            segmentation_supported: bacnet_types::enums::Segmentation::NONE,
            max_segments_accepted: None,
            vendor_id: 0,
            last_seen: std::time::Instant::now(),
            source_network: None,
            source_address: None,
        };
        self.device_table.lock().await.upsert(device);
        Ok(())
    }

    /// Manually register a routed (e.g. MS/TP) device behind a BACnet/IP router.
    ///
    /// `mac` is the router's BIP MAC; `dest_network` + `dest_mac` identify the
    /// remote device (MS/TP MAC is typically a single byte).
    ///
    /// Open-FDD patch over crates.io `bacnet-client` 0.9.0 — upstream does not
    /// yet expose this helper (device table fields already support routing).
    pub async fn add_routed_device(
        &self,
        instance: u32,
        mac: &[u8],
        dest_network: u16,
        dest_mac: &[u8],
    ) -> Result<(), Error> {
        let oid = bacnet_types::primitives::ObjectIdentifier::new(
            bacnet_types::enums::ObjectType::DEVICE,
            instance,
        )?;
        let device = DiscoveredDevice {
            object_identifier: oid,
            mac_address: MacAddr::from_slice(mac),
            max_apdu_length: 1476,
            segmentation_supported: bacnet_types::enums::Segmentation::NONE,
            max_segments_accepted: None,
            vendor_id: 0,
            last_seen: std::time::Instant::now(),
            source_network: Some(dest_network),
            source_address: Some(MacAddr::from_slice(dest_mac)),
        };
        self.device_table.lock().await.upsert(device);
        Ok(())
    }
}
