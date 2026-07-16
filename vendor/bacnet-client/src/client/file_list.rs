use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    /// Get event information from a remote device.
    pub async fn get_event_information(
        &self,
        destination_mac: &[u8],
        last_received_object_identifier: Option<bacnet_types::primitives::ObjectIdentifier>,
    ) -> Result<Bytes, Error> {
        use bacnet_services::alarm_event::GetEventInformationRequest;

        let request = GetEventInformationRequest {
            last_received_object_identifier,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        self.confirmed_request(
            destination_mac,
            ConfirmedServiceChoice::GET_EVENT_INFORMATION,
            &buf,
        )
        .await
    }

    /// Acknowledge an alarm on a remote device.
    pub async fn acknowledge_alarm(
        &self,
        destination_mac: &[u8],
        acknowledging_process_identifier: u32,
        event_object_identifier: bacnet_types::primitives::ObjectIdentifier,
        event_state_acknowledged: u32,
        acknowledgment_source: &str,
    ) -> Result<(), Error> {
        use bacnet_services::alarm_event::AcknowledgeAlarmRequest;

        let request = AcknowledgeAlarmRequest {
            acknowledging_process_identifier,
            event_object_identifier,
            event_state_acknowledged,
            timestamp: bacnet_types::primitives::BACnetTimeStamp::SequenceNumber(0),
            acknowledgment_source: acknowledgment_source.to_string(),
            time_of_acknowledgment: bacnet_types::primitives::BACnetTimeStamp::SequenceNumber(0),
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf)?;

        let _ = self
            .confirmed_request(
                destination_mac,
                ConfirmedServiceChoice::ACKNOWLEDGE_ALARM,
                &buf,
            )
            .await?;

        Ok(())
    }

    /// Read a range of items from a list or log-buffer property.
    pub async fn read_range(
        &self,
        destination_mac: &[u8],
        object_identifier: bacnet_types::primitives::ObjectIdentifier,
        property_identifier: bacnet_types::enums::PropertyIdentifier,
        property_array_index: Option<u32>,
        range: Option<bacnet_services::read_range::RangeSpec>,
    ) -> Result<bacnet_services::read_range::ReadRangeAck, Error> {
        use bacnet_services::read_range::{ReadRangeAck, ReadRangeRequest};

        let request = ReadRangeRequest {
            object_identifier,
            property_identifier,
            property_array_index,
            range,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let response_data = self
            .confirmed_request(destination_mac, ConfirmedServiceChoice::READ_RANGE, &buf)
            .await?;

        ReadRangeAck::decode(&response_data)
    }

    /// Read file data from a remote device (stream or record access).
    pub async fn atomic_read_file(
        &self,
        destination_mac: &[u8],
        file_identifier: bacnet_types::primitives::ObjectIdentifier,
        access: bacnet_services::file::FileAccessMethod,
    ) -> Result<Bytes, Error> {
        use bacnet_services::file::AtomicReadFileRequest;

        let request = AtomicReadFileRequest {
            file_identifier,
            access,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        self.confirmed_request(
            destination_mac,
            ConfirmedServiceChoice::ATOMIC_READ_FILE,
            &buf,
        )
        .await
    }

    /// Write file data to a remote device (stream or record access).
    pub async fn atomic_write_file(
        &self,
        destination_mac: &[u8],
        file_identifier: bacnet_types::primitives::ObjectIdentifier,
        access: bacnet_services::file::FileWriteAccessMethod,
    ) -> Result<Bytes, Error> {
        use bacnet_services::file::AtomicWriteFileRequest;

        let request = AtomicWriteFileRequest {
            file_identifier,
            access,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        self.confirmed_request(
            destination_mac,
            ConfirmedServiceChoice::ATOMIC_WRITE_FILE,
            &buf,
        )
        .await
    }

    /// Add elements to a list property on a remote device.
    pub async fn add_list_element(
        &self,
        destination_mac: &[u8],
        object_identifier: bacnet_types::primitives::ObjectIdentifier,
        property_identifier: bacnet_types::enums::PropertyIdentifier,
        property_array_index: Option<u32>,
        list_of_elements: Vec<u8>,
    ) -> Result<(), Error> {
        use bacnet_services::list_manipulation::ListElementRequest;

        let request = ListElementRequest {
            object_identifier,
            property_identifier,
            property_array_index,
            list_of_elements,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let _ = self
            .confirmed_request(
                destination_mac,
                ConfirmedServiceChoice::ADD_LIST_ELEMENT,
                &buf,
            )
            .await?;

        Ok(())
    }

    /// Remove elements from a list property on a remote device.
    pub async fn remove_list_element(
        &self,
        destination_mac: &[u8],
        object_identifier: bacnet_types::primitives::ObjectIdentifier,
        property_identifier: bacnet_types::enums::PropertyIdentifier,
        property_array_index: Option<u32>,
        list_of_elements: Vec<u8>,
    ) -> Result<(), Error> {
        use bacnet_services::list_manipulation::ListElementRequest;

        let request = ListElementRequest {
            object_identifier,
            property_identifier,
            property_array_index,
            list_of_elements,
        };
        let mut buf = BytesMut::new();
        request.encode(&mut buf);

        let _ = self
            .confirmed_request(
                destination_mac,
                ConfirmedServiceChoice::REMOVE_LIST_ELEMENT,
                &buf,
            )
            .await?;

        Ok(())
    }
}
