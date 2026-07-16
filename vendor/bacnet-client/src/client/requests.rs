use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    /// Send a confirmed request and wait for the response.
    ///
    /// Returns the service response data (empty for SimpleAck). Automatically
    /// uses segmented transfer when the payload exceeds the remote device's
    /// max APDU length.
    pub async fn confirmed_request(
        &self,
        destination_mac: &[u8],
        service_choice: ConfirmedServiceChoice,
        service_data: &[u8],
    ) -> Result<Bytes, Error> {
        self.confirmed_request_inner(
            ConfirmedTarget::Local {
                mac: destination_mac,
            },
            service_choice,
            service_data,
        )
        .await
    }

    /// Send a confirmed request routed through a BACnet router.
    ///
    /// The NPDU is sent as a unicast to `router_mac` with DNET/DADR set so
    /// the router forwards it to `dest_network`/`dest_mac`.
    pub async fn confirmed_request_routed(
        &self,
        router_mac: &[u8],
        dest_network: u16,
        dest_mac: &[u8],
        service_choice: ConfirmedServiceChoice,
        service_data: &[u8],
    ) -> Result<Bytes, Error> {
        self.confirmed_request_inner(
            ConfirmedTarget::Routed {
                router_mac,
                dest_network,
                dest_mac,
            },
            service_choice,
            service_data,
        )
        .await
    }

    pub(super) async fn confirmed_request_inner(
        &self,
        target: ConfirmedTarget<'_>,
        service_choice: ConfirmedServiceChoice,
        service_data: &[u8],
    ) -> Result<Bytes, Error> {
        let tsm_mac = target.tsm_mac();
        let unsegmented_apdu_size = 4 + service_data.len();

        match target {
            ConfirmedTarget::Local { mac } => {
                let (remote_max_apdu, remote_max_segments) = {
                    let dt = self.device_table.lock().await;
                    let device = dt.get_by_mac(mac);
                    let max_apdu = device
                        .map(|d| d.max_apdu_length as u16)
                        .unwrap_or(self.config.max_apdu_length);
                    let max_seg = device.and_then(|d| d.max_segments_accepted);
                    (max_apdu, max_seg)
                };
                if unsegmented_apdu_size > remote_max_apdu as usize {
                    return self
                        .segmented_confirmed_request(
                            target,
                            service_choice,
                            service_data,
                            remote_max_apdu,
                            remote_max_segments,
                        )
                        .await;
                }
            }
            ConfirmedTarget::Routed { .. } => {
                let remote_max_apdu = self.config.max_apdu_length;
                if unsegmented_apdu_size > remote_max_apdu as usize {
                    return self
                        .segmented_confirmed_request(
                            target,
                            service_choice,
                            service_data,
                            remote_max_apdu,
                            None,
                        )
                        .await;
                }
            }
        }

        let (invoke_id, rx) = {
            let mut tsm = self.tsm.lock().await;
            let invoke_id = tsm.allocate_invoke_id(&tsm_mac).ok_or_else(|| {
                Error::Encoding("all invoke IDs exhausted for destination".into())
            })?;
            let rx = tsm.register_transaction(tsm_mac.clone(), invoke_id);
            (invoke_id, rx)
        };

        // Guard cleans up invoke ID if this task is cancelled/aborted
        let mut guard =
            crate::tsm::TsmGuard::new(std::sync::Arc::clone(&self.tsm), tsm_mac.clone(), invoke_id);

        let pdu = Apdu::ConfirmedRequest(ConfirmedRequestPdu {
            segmented: false,
            more_follows: false,
            segmented_response_accepted: self.config.segmented_response_accepted,
            max_segments: self.config.max_segments,
            max_apdu_length: self.config.max_apdu_length,
            invoke_id,
            sequence_number: None,
            proposed_window_size: None,
            service_choice,
            service_request: Bytes::copy_from_slice(service_data),
        });

        let mut buf = BytesMut::with_capacity(6 + service_data.len());
        encode_apdu(&mut buf, &pdu)?;

        let timeout_duration = Duration::from_millis(self.config.apdu_timeout_ms);
        let max_retries = self.config.apdu_retries;
        let mut attempts: u8 = 0;
        let mut rx = rx;

        loop {
            let send_result = match &target {
                ConfirmedTarget::Local { mac } => {
                    self.network
                        .send_apdu(&buf, mac, true, NetworkPriority::NORMAL)
                        .await
                }
                ConfirmedTarget::Routed {
                    router_mac,
                    dest_network,
                    dest_mac,
                } => {
                    self.network
                        .send_apdu_routed(
                            &buf,
                            *dest_network,
                            dest_mac,
                            router_mac,
                            true,
                            NetworkPriority::NORMAL,
                        )
                        .await
                }
            };
            if let Err(e) = send_result {
                guard.mark_completed();
                let mut tsm = self.tsm.lock().await;
                tsm.cancel_transaction(&tsm_mac, invoke_id);
                return Err(e);
            }

            match timeout(timeout_duration, &mut rx).await {
                Ok(Ok(response)) => {
                    guard.mark_completed();
                    return match response {
                        TsmResponse::SimpleAck => Ok(Bytes::new()),
                        TsmResponse::ComplexAck { service_data } => Ok(service_data),
                        TsmResponse::Error { class, code } => Err(Error::Protocol { class, code }),
                        TsmResponse::Reject { reason } => Err(Error::Reject { reason }),
                        TsmResponse::Abort { reason } => Err(Error::Abort { reason }),
                    };
                }
                Ok(Err(_)) => {
                    guard.mark_completed();
                    return Err(Error::Encoding("TSM response channel closed".into()));
                }
                Err(_timeout) => {
                    attempts += 1;
                    if attempts > max_retries {
                        guard.mark_completed();
                        let mut tsm = self.tsm.lock().await;
                        tsm.cancel_transaction(&tsm_mac, invoke_id);
                        return Err(Error::Timeout(timeout_duration));
                    }
                    debug!(
                        invoke_id,
                        attempt = attempts,
                        max_retries,
                        "APDU timeout, retrying confirmed request"
                    );
                }
            }
        }
    }

    pub(super) async fn send_confirmed_target_apdu(
        &self,
        target: ConfirmedTarget<'_>,
        apdu: &[u8],
    ) -> Result<(), Error> {
        match target {
            ConfirmedTarget::Local { mac } => {
                self.network
                    .send_apdu(apdu, mac, true, NetworkPriority::NORMAL)
                    .await
            }
            ConfirmedTarget::Routed {
                router_mac,
                dest_network,
                dest_mac,
            } => {
                self.network
                    .send_apdu_routed(
                        apdu,
                        dest_network,
                        dest_mac,
                        router_mac,
                        true,
                        NetworkPriority::NORMAL,
                    )
                    .await
            }
        }
    }
    /// Send an unconfirmed request (fire-and-forget) to a specific destination.
    pub async fn unconfirmed_request(
        &self,
        destination_mac: &[u8],
        service_choice: UnconfirmedServiceChoice,
        service_data: &[u8],
    ) -> Result<(), Error> {
        let pdu = Apdu::UnconfirmedRequest(bacnet_encoding::apdu::UnconfirmedRequest {
            service_choice,
            service_request: Bytes::copy_from_slice(service_data),
        });

        let mut buf = BytesMut::with_capacity(2 + service_data.len());
        encode_apdu(&mut buf, &pdu)?;

        self.network
            .send_apdu(&buf, destination_mac, false, NetworkPriority::NORMAL)
            .await
    }

    /// Broadcast an unconfirmed request on the local network.
    pub async fn broadcast_unconfirmed(
        &self,
        service_choice: UnconfirmedServiceChoice,
        service_data: &[u8],
    ) -> Result<(), Error> {
        let pdu = Apdu::UnconfirmedRequest(bacnet_encoding::apdu::UnconfirmedRequest {
            service_choice,
            service_request: Bytes::copy_from_slice(service_data),
        });

        let mut buf = BytesMut::with_capacity(2 + service_data.len());
        encode_apdu(&mut buf, &pdu)?;

        self.network
            .broadcast_apdu(&buf, false, NetworkPriority::NORMAL)
            .await
    }

    /// Broadcast an unconfirmed request globally (DNET=0xFFFF).
    pub async fn broadcast_global_unconfirmed(
        &self,
        service_choice: UnconfirmedServiceChoice,
        service_data: &[u8],
    ) -> Result<(), Error> {
        let pdu = Apdu::UnconfirmedRequest(bacnet_encoding::apdu::UnconfirmedRequest {
            service_choice,
            service_request: Bytes::copy_from_slice(service_data),
        });

        let mut buf = BytesMut::with_capacity(2 + service_data.len());
        encode_apdu(&mut buf, &pdu)?;

        self.network
            .broadcast_global_apdu(&buf, false, NetworkPriority::NORMAL)
            .await
    }

    /// Broadcast an unconfirmed request to a specific remote network.
    pub async fn broadcast_network_unconfirmed(
        &self,
        service_choice: UnconfirmedServiceChoice,
        service_data: &[u8],
        dest_network: u16,
    ) -> Result<(), Error> {
        let pdu = Apdu::UnconfirmedRequest(bacnet_encoding::apdu::UnconfirmedRequest {
            service_choice,
            service_request: Bytes::copy_from_slice(service_data),
        });

        let mut buf = BytesMut::with_capacity(2 + service_data.len());
        encode_apdu(&mut buf, &pdu)?;

        self.network
            .broadcast_to_network(&buf, dest_network, false, NetworkPriority::NORMAL)
            .await
    }
}
