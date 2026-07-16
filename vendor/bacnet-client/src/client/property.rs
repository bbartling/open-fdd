use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    /// Read a property from a remote device.
    pub async fn read_property(
        &self,
        destination_mac: &[u8],
        object_identifier: bacnet_types::primitives::ObjectIdentifier,
        property_identifier: bacnet_types::enums::PropertyIdentifier,
        property_array_index: Option<u32>,
    ) -> Result<bacnet_services::read_property::ReadPropertyACK, Error> {
        use bacnet_services::read_property::ReadPropertyRequest;

        let request = ReadPropertyRequest {
            object_identifier,
            property_identifier,
            property_array_index,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let response_data = self
            .confirmed_request(destination_mac, ConfirmedServiceChoice::READ_PROPERTY, &buf)
            .await?;

        bacnet_services::read_property::ReadPropertyACK::decode(&response_data)
    }

    /// Read a property from a discovered device, auto-routing if needed.
    pub async fn read_property_from_device(
        &self,
        device_instance: u32,
        object_identifier: bacnet_types::primitives::ObjectIdentifier,
        property_identifier: bacnet_types::enums::PropertyIdentifier,
        property_array_index: Option<u32>,
    ) -> Result<bacnet_services::read_property::ReadPropertyACK, Error> {
        let (mac, routing) = {
            let dt = self.device_table.lock().await;
            let device = dt.get(device_instance).ok_or_else(|| {
                Error::Encoding(format!("device {device_instance} not in device table"))
            })?;
            let routing = match (&device.source_network, &device.source_address) {
                (Some(snet), Some(sadr)) => Some((*snet, sadr.to_vec())),
                _ => None,
            };
            (device.mac_address.to_vec(), routing)
        };

        if let Some((dnet, dadr)) = routing {
            self.read_property_routed(
                &mac,
                dnet,
                &dadr,
                object_identifier,
                property_identifier,
                property_array_index,
            )
            .await
        } else {
            self.read_property(
                &mac,
                object_identifier,
                property_identifier,
                property_array_index,
            )
            .await
        }
    }

    /// Read a property from a device on a remote BACnet network via a router.
    pub async fn read_property_routed(
        &self,
        router_mac: &[u8],
        dest_network: u16,
        dest_mac: &[u8],
        object_identifier: bacnet_types::primitives::ObjectIdentifier,
        property_identifier: bacnet_types::enums::PropertyIdentifier,
        property_array_index: Option<u32>,
    ) -> Result<bacnet_services::read_property::ReadPropertyACK, Error> {
        use bacnet_services::read_property::ReadPropertyRequest;

        let request = ReadPropertyRequest {
            object_identifier,
            property_identifier,
            property_array_index,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let response_data = self
            .confirmed_request_routed(
                router_mac,
                dest_network,
                dest_mac,
                ConfirmedServiceChoice::READ_PROPERTY,
                &buf,
            )
            .await?;

        bacnet_services::read_property::ReadPropertyACK::decode(&response_data)
    }

    /// Write a property on a remote device.
    pub async fn read_property_multiple(
        &self,
        destination_mac: &[u8],
        specs: Vec<bacnet_services::rpm::ReadAccessSpecification>,
    ) -> Result<bacnet_services::rpm::ReadPropertyMultipleACK, Error> {
        use bacnet_services::rpm::{ReadPropertyMultipleACK, ReadPropertyMultipleRequest};

        let request = ReadPropertyMultipleRequest {
            list_of_read_access_specs: specs,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let response_data = self
            .confirmed_request(
                destination_mac,
                ConfirmedServiceChoice::READ_PROPERTY_MULTIPLE,
                &buf,
            )
            .await?;

        ReadPropertyMultipleACK::decode(&response_data)
    }

    /// Write multiple properties on one or more objects on a remote device.
    pub async fn read_property_multiple_from_device(
        &self,
        device_instance: u32,
        specs: Vec<bacnet_services::rpm::ReadAccessSpecification>,
    ) -> Result<bacnet_services::rpm::ReadPropertyMultipleACK, Error> {
        let (mac, routing) = self.resolve_device(device_instance).await?;

        if let Some((dnet, dadr)) = routing {
            use bacnet_services::rpm::{ReadPropertyMultipleACK, ReadPropertyMultipleRequest};

            let request = ReadPropertyMultipleRequest {
                list_of_read_access_specs: specs,
            };
            let mut buf = BytesMut::new();
            request.encode(&mut buf);

            let response_data = self
                .confirmed_request_routed(
                    &mac,
                    dnet,
                    &dadr,
                    ConfirmedServiceChoice::READ_PROPERTY_MULTIPLE,
                    &buf,
                )
                .await?;

            ReadPropertyMultipleACK::decode(&response_data)
        } else {
            self.read_property_multiple(&mac, specs).await
        }
    }

    /// Write a property on a discovered device, auto-routing if needed.
    pub async fn read_property_from_devices(
        &self,
        requests: Vec<DeviceReadRequest>,
        max_concurrent: Option<usize>,
    ) -> Vec<DeviceReadResult> {
        use futures_util::stream::{self, StreamExt};

        let concurrency = max_concurrent.unwrap_or(DEFAULT_BATCH_CONCURRENCY);

        stream::iter(requests)
            .map(|req| async move {
                let result = self
                    .read_property_from_device(
                        req.device_instance,
                        req.object_identifier,
                        req.property_identifier,
                        req.property_array_index,
                    )
                    .await;
                DeviceReadResult {
                    device_instance: req.device_instance,
                    result,
                }
            })
            .buffer_unordered(concurrency)
            .collect()
            .await
    }

    /// Read multiple properties from multiple devices concurrently (RPM batch).
    ///
    /// Sends an RPM to each device concurrently. This is the most efficient
    /// way to poll many properties across many devices — RPM batches within
    /// a single device, and this method batches across devices.
    pub async fn read_property_multiple_from_devices(
        &self,
        requests: Vec<DeviceRpmRequest>,
        max_concurrent: Option<usize>,
    ) -> Vec<DeviceRpmResult> {
        use futures_util::stream::{self, StreamExt};

        let concurrency = max_concurrent.unwrap_or(DEFAULT_BATCH_CONCURRENCY);

        stream::iter(requests)
            .map(|req| async move {
                let result = self
                    .read_property_multiple_from_device(req.device_instance, req.specs)
                    .await;
                DeviceRpmResult {
                    device_instance: req.device_instance,
                    result,
                }
            })
            .buffer_unordered(concurrency)
            .collect()
            .await
    }

    /// Write a property on multiple devices concurrently.
    ///
    /// All writes are dispatched concurrently (up to `max_concurrent`,
    /// default 32). Results are returned in completion order.
    pub async fn write_property(
        &self,
        destination_mac: &[u8],
        object_identifier: bacnet_types::primitives::ObjectIdentifier,
        property_identifier: bacnet_types::enums::PropertyIdentifier,
        property_array_index: Option<u32>,
        property_value: Vec<u8>,
        priority: Option<u8>,
    ) -> Result<(), Error> {
        use bacnet_services::write_property::WritePropertyRequest;

        let request = WritePropertyRequest {
            object_identifier,
            property_identifier,
            property_array_index,
            property_value,
            priority,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let _ = self
            .confirmed_request(
                destination_mac,
                ConfirmedServiceChoice::WRITE_PROPERTY,
                &buf,
            )
            .await?;

        Ok(())
    }

    /// Read multiple properties from one or more objects on a remote device.
    pub async fn write_property_multiple(
        &self,
        destination_mac: &[u8],
        specs: Vec<bacnet_services::wpm::WriteAccessSpecification>,
    ) -> Result<(), Error> {
        use bacnet_services::wpm::WritePropertyMultipleRequest;

        let request = WritePropertyMultipleRequest {
            list_of_write_access_specs: specs,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let _ = self
            .confirmed_request(
                destination_mac,
                ConfirmedServiceChoice::WRITE_PROPERTY_MULTIPLE,
                &buf,
            )
            .await?;

        Ok(())
    }

    // -----------------------------------------------------------------------
    // Auto-routing _from_device variants (RPM, WP, WPM)
    // -----------------------------------------------------------------------

    /// Read multiple properties from a discovered device, auto-routing if needed.
    pub async fn write_property_to_device(
        &self,
        device_instance: u32,
        object_identifier: bacnet_types::primitives::ObjectIdentifier,
        property_identifier: bacnet_types::enums::PropertyIdentifier,
        property_array_index: Option<u32>,
        property_value: Vec<u8>,
        priority: Option<u8>,
    ) -> Result<(), Error> {
        let (mac, routing) = self.resolve_device(device_instance).await?;

        if let Some((dnet, dadr)) = routing {
            use bacnet_services::write_property::WritePropertyRequest;

            let request = WritePropertyRequest {
                object_identifier,
                property_identifier,
                property_array_index,
                property_value,
                priority,
            };
            let mut buf = BytesMut::new();
            request.encode(&mut buf);

            let _ = self
                .confirmed_request_routed(
                    &mac,
                    dnet,
                    &dadr,
                    ConfirmedServiceChoice::WRITE_PROPERTY,
                    &buf,
                )
                .await?;
            Ok(())
        } else {
            self.write_property(
                &mac,
                object_identifier,
                property_identifier,
                property_array_index,
                property_value,
                priority,
            )
            .await
        }
    }

    /// Write multiple properties on a discovered device, auto-routing if needed.
    pub async fn write_property_multiple_to_device(
        &self,
        device_instance: u32,
        specs: Vec<bacnet_services::wpm::WriteAccessSpecification>,
    ) -> Result<(), Error> {
        let (mac, routing) = self.resolve_device(device_instance).await?;

        if let Some((dnet, dadr)) = routing {
            use bacnet_services::wpm::WritePropertyMultipleRequest;

            let request = WritePropertyMultipleRequest {
                list_of_write_access_specs: specs,
            };
            let mut buf = BytesMut::new();
            request.encode(&mut buf);

            let _ = self
                .confirmed_request_routed(
                    &mac,
                    dnet,
                    &dadr,
                    ConfirmedServiceChoice::WRITE_PROPERTY_MULTIPLE,
                    &buf,
                )
                .await?;
            Ok(())
        } else {
            self.write_property_multiple(&mac, specs).await
        }
    }
    pub async fn write_property_to_devices(
        &self,
        requests: Vec<DeviceWriteRequest>,
        max_concurrent: Option<usize>,
    ) -> Vec<DeviceWriteResult> {
        use futures_util::stream::{self, StreamExt};

        let concurrency = max_concurrent.unwrap_or(DEFAULT_BATCH_CONCURRENCY);

        stream::iter(requests)
            .map(|req| async move {
                let result = self
                    .write_property_to_device(
                        req.device_instance,
                        req.object_identifier,
                        req.property_identifier,
                        req.property_array_index,
                        req.property_value,
                        req.priority,
                    )
                    .await;
                DeviceWriteResult {
                    device_instance: req.device_instance,
                    result,
                }
            })
            .buffer_unordered(concurrency)
            .collect()
            .await
    }
}
