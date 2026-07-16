use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    /// Send DeviceCommunicationControl to a remote device.
    pub async fn device_communication_control(
        &self,
        destination_mac: &[u8],
        enable_disable: bacnet_types::enums::EnableDisable,
        time_duration: Option<u16>,
        password: Option<String>,
    ) -> Result<(), Error> {
        use bacnet_services::device_mgmt::DeviceCommunicationControlRequest;

        let request = DeviceCommunicationControlRequest {
            time_duration,
            enable_disable,
            password,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf)?;

        let _ = self
            .confirmed_request(
                destination_mac,
                ConfirmedServiceChoice::DEVICE_COMMUNICATION_CONTROL,
                &buf,
            )
            .await?;

        Ok(())
    }

    /// Send ReinitializeDevice to a remote device.
    pub async fn reinitialize_device(
        &self,
        destination_mac: &[u8],
        reinitialized_state: bacnet_types::enums::ReinitializedState,
        password: Option<String>,
    ) -> Result<(), Error> {
        use bacnet_services::device_mgmt::ReinitializeDeviceRequest;

        let request = ReinitializeDeviceRequest {
            reinitialized_state,
            password,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf)?;

        let _ = self
            .confirmed_request(
                destination_mac,
                ConfirmedServiceChoice::REINITIALIZE_DEVICE,
                &buf,
            )
            .await?;

        Ok(())
    }
    /// Send a TimeSynchronization request (unconfirmed, no response expected).
    pub async fn time_synchronization(
        &self,
        destination_mac: &[u8],
        date: bacnet_types::primitives::Date,
        time: bacnet_types::primitives::Time,
    ) -> Result<(), Error> {
        use bacnet_services::device_mgmt::TimeSynchronizationRequest;

        let request = TimeSynchronizationRequest { date, time };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        self.unconfirmed_request(
            destination_mac,
            UnconfirmedServiceChoice::TIME_SYNCHRONIZATION,
            &buf,
        )
        .await
    }

    /// Send a UTCTimeSynchronization request (unconfirmed, no response expected).
    pub async fn utc_time_synchronization(
        &self,
        destination_mac: &[u8],
        date: bacnet_types::primitives::Date,
        time: bacnet_types::primitives::Time,
    ) -> Result<(), Error> {
        use bacnet_services::device_mgmt::TimeSynchronizationRequest;

        let request = TimeSynchronizationRequest { date, time };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        self.unconfirmed_request(
            destination_mac,
            UnconfirmedServiceChoice::UTC_TIME_SYNCHRONIZATION,
            &buf,
        )
        .await
    }
}
