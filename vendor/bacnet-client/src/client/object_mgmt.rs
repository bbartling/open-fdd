use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    pub async fn delete_object(
        &self,
        destination_mac: &[u8],
        object_identifier: bacnet_types::primitives::ObjectIdentifier,
    ) -> Result<(), Error> {
        use bacnet_services::object_mgmt::DeleteObjectRequest;

        let request = DeleteObjectRequest { object_identifier };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let _ = self
            .confirmed_request(destination_mac, ConfirmedServiceChoice::DELETE_OBJECT, &buf)
            .await?;

        Ok(())
    }

    /// Create an object on a remote device.
    pub async fn create_object(
        &self,
        destination_mac: &[u8],
        object_specifier: bacnet_services::object_mgmt::ObjectSpecifier,
        initial_values: Vec<bacnet_services::common::BACnetPropertyValue>,
    ) -> Result<Bytes, Error> {
        use bacnet_services::object_mgmt::CreateObjectRequest;

        let request = CreateObjectRequest {
            object_specifier,
            list_of_initial_values: initial_values,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        self.confirmed_request(destination_mac, ConfirmedServiceChoice::CREATE_OBJECT, &buf)
            .await
    }
}
