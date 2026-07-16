use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    pub async fn subscribe_cov(
        &self,
        destination_mac: &[u8],
        subscriber_process_identifier: u32,
        monitored_object_identifier: bacnet_types::primitives::ObjectIdentifier,
        confirmed: bool,
        lifetime: Option<u32>,
    ) -> Result<(), Error> {
        use bacnet_services::cov::SubscribeCOVRequest;

        let request = SubscribeCOVRequest {
            subscriber_process_identifier,
            monitored_object_identifier,
            issue_confirmed_notifications: Some(confirmed),
            lifetime,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let _ = self
            .confirmed_request(destination_mac, ConfirmedServiceChoice::SUBSCRIBE_COV, &buf)
            .await?;

        Ok(())
    }

    /// Cancel a COV subscription on a remote device.
    pub async fn unsubscribe_cov(
        &self,
        destination_mac: &[u8],
        subscriber_process_identifier: u32,
        monitored_object_identifier: bacnet_types::primitives::ObjectIdentifier,
    ) -> Result<(), Error> {
        use bacnet_services::cov::SubscribeCOVRequest;

        let request = SubscribeCOVRequest {
            subscriber_process_identifier,
            monitored_object_identifier,
            issue_confirmed_notifications: None,
            lifetime: None,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let _ = self
            .confirmed_request(destination_mac, ConfirmedServiceChoice::SUBSCRIBE_COV, &buf)
            .await?;

        Ok(())
    }

    /// Delete an object on a remote device.
    /// Get a receiver for incoming COV notifications. Each call returns a new
    /// independent receiver.
    pub fn cov_notifications(&self) -> broadcast::Receiver<COVNotificationRequest> {
        self.cov_tx.subscribe()
    }
}
