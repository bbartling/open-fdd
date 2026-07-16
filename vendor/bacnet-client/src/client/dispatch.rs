use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    /// Dispatch a received APDU to the appropriate handler.
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn dispatch_apdu(
        tsm: &Arc<Mutex<Tsm>>,
        device_table: &Arc<Mutex<DeviceTable>>,
        network: &Arc<NetworkLayer<T>>,
        cov_tx: &broadcast::Sender<COVNotificationRequest>,
        seg_state: &mut HashMap<SegKey, SegmentedReceiveState>,
        seg_ack_senders: &Arc<Mutex<HashMap<SegKey, mpsc::Sender<SegmentAckPdu>>>>,
        source_mac: &[u8],
        source_network: &Option<NpduAddress>,
        apdu: Apdu,
        segmented_response_accepted: bool,
    ) {
        let tsm_mac = response_tsm_mac(source_mac, source_network);
        match apdu {
            Apdu::SimpleAck(ack) => {
                debug!(invoke_id = ack.invoke_id, "Received SimpleAck");
                let mut tsm = tsm.lock().await;
                tsm.complete_transaction(&tsm_mac, ack.invoke_id, TsmResponse::SimpleAck);
            }
            Apdu::ComplexAck(ack) => {
                if ack.segmented {
                    Self::handle_segmented_complex_ack(
                        tsm,
                        network,
                        seg_state,
                        source_mac,
                        source_network,
                        ack,
                        segmented_response_accepted,
                    )
                    .await;
                } else {
                    debug!(invoke_id = ack.invoke_id, "Received ComplexAck");
                    let mut tsm = tsm.lock().await;
                    tsm.complete_transaction(
                        &tsm_mac,
                        ack.invoke_id,
                        TsmResponse::ComplexAck {
                            service_data: ack.service_ack,
                        },
                    );
                }
            }
            Apdu::Error(err) => {
                debug!(invoke_id = err.invoke_id, "Received Error PDU");
                let mut tsm = tsm.lock().await;
                tsm.complete_transaction(
                    &tsm_mac,
                    err.invoke_id,
                    TsmResponse::Error {
                        class: err.error_class.to_raw() as u32,
                        code: err.error_code.to_raw() as u32,
                    },
                );
            }
            Apdu::Reject(rej) => {
                debug!(invoke_id = rej.invoke_id, "Received Reject PDU");
                let mut tsm = tsm.lock().await;
                tsm.complete_transaction(
                    &tsm_mac,
                    rej.invoke_id,
                    TsmResponse::Reject {
                        reason: rej.reject_reason.to_raw(),
                    },
                );
            }
            Apdu::Abort(abt) => {
                debug!(invoke_id = abt.invoke_id, "Received Abort PDU");
                let mut tsm = tsm.lock().await;
                tsm.complete_transaction(
                    &tsm_mac,
                    abt.invoke_id,
                    TsmResponse::Abort {
                        reason: abt.abort_reason.to_raw(),
                    },
                );
            }
            Apdu::ConfirmedRequest(req) => {
                if req.service_choice == ConfirmedServiceChoice::CONFIRMED_COV_NOTIFICATION {
                    match COVNotificationRequest::decode(&req.service_request) {
                        Ok(notification) => {
                            debug!(
                                object = ?notification.monitored_object_identifier,
                                "Received ConfirmedCOVNotification"
                            );
                            let _ = cov_tx.send(notification);

                            let ack = Apdu::SimpleAck(SimpleAck {
                                invoke_id: req.invoke_id,
                                service_choice: req.service_choice,
                            });
                            let mut buf = BytesMut::with_capacity(4);
                            if let Err(e) = encode_apdu(&mut buf, &ack) {
                                warn!(error = %e, "Failed to encode SimpleAck for COV notification");
                                return;
                            }
                            if let Err(e) = network
                                .send_apdu(&buf, source_mac, false, NetworkPriority::NORMAL)
                                .await
                            {
                                warn!(error = %e, "Failed to send SimpleAck for COV notification");
                            }
                        }
                        Err(e) => {
                            warn!(error = %e, "Failed to decode ConfirmedCOVNotification");
                        }
                    }
                } else {
                    debug!(
                        service = req.service_choice.to_raw(),
                        "Ignoring ConfirmedRequest (client mode)"
                    );
                }
            }
            Apdu::UnconfirmedRequest(req) => {
                if req.service_choice == UnconfirmedServiceChoice::I_AM {
                    match bacnet_services::who_is::IAmRequest::decode(&req.service_request) {
                        Ok(i_am) => {
                            debug!(
                                device = i_am.object_identifier.instance_number(),
                                vendor = i_am.vendor_id,
                                "Received IAm"
                            );
                            let (src_net, src_addr) = match source_network {
                                Some(npdu_addr) if !npdu_addr.mac_address.is_empty() => {
                                    (Some(npdu_addr.network), Some(npdu_addr.mac_address.clone()))
                                }
                                _ => (None, None),
                            };
                            let device = DiscoveredDevice {
                                object_identifier: i_am.object_identifier,
                                mac_address: MacAddr::from_slice(source_mac),
                                max_apdu_length: i_am.max_apdu_length,
                                segmentation_supported: i_am.segmentation_supported,
                                max_segments_accepted: None,
                                vendor_id: i_am.vendor_id,
                                last_seen: std::time::Instant::now(),
                                source_network: src_net,
                                source_address: src_addr,
                            };
                            device_table.lock().await.upsert(device);
                        }
                        Err(e) => {
                            warn!(error = %e, "Failed to decode IAm");
                        }
                    }
                } else if req.service_choice
                    == UnconfirmedServiceChoice::UNCONFIRMED_COV_NOTIFICATION
                {
                    match COVNotificationRequest::decode(&req.service_request) {
                        Ok(notification) => {
                            debug!(
                                object = ?notification.monitored_object_identifier,
                                "Received UnconfirmedCOVNotification"
                            );
                            let _ = cov_tx.send(notification);
                        }
                        Err(e) => {
                            warn!(error = %e, "Failed to decode UnconfirmedCOVNotification");
                        }
                    }
                } else {
                    debug!(
                        service = req.service_choice.to_raw(),
                        "Ignoring unconfirmed service in client dispatch"
                    );
                }
            }
            Apdu::SegmentAck(sa) => {
                let key = (tsm_mac, sa.invoke_id);
                let senders = seg_ack_senders.lock().await;
                if let Some(tx) = senders.get(&key) {
                    let _ = tx.try_send(sa);
                } else {
                    debug!(
                        invoke_id = sa.invoke_id,
                        "Ignoring SegmentAck for unknown transaction"
                    );
                }
            }
        }
    }
}
