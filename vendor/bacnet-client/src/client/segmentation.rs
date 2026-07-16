use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    /// Handle a segmented ComplexAck: accumulate segments, send SegmentAcks,
    /// and reassemble when all segments are received.
    pub(super) async fn handle_segmented_complex_ack(
        tsm: &Arc<Mutex<Tsm>>,
        network: &Arc<NetworkLayer<T>>,
        seg_state: &mut HashMap<SegKey, SegmentedReceiveState>,
        source_mac: &[u8],
        source_network: &Option<NpduAddress>,
        ack: bacnet_encoding::apdu::ComplexAck,
        segmented_response_accepted: bool,
    ) {
        let seq = ack.sequence_number.unwrap_or(0);
        let tsm_mac = response_tsm_mac(source_mac, source_network);
        let key = (tsm_mac.clone(), ack.invoke_id);

        debug!(
            invoke_id = ack.invoke_id,
            seq = seq,
            more = ack.more_follows,
            "Received segmented ComplexAck"
        );

        // If client doesn't support segmented reception, send Abort per Clause 5.4.4.2
        if !segmented_response_accepted {
            let abort = Apdu::Abort(AbortPdu {
                sent_by_server: false,
                invoke_id: ack.invoke_id,
                abort_reason: bacnet_types::enums::AbortReason::SEGMENTATION_NOT_SUPPORTED,
            });
            let mut buf = BytesMut::with_capacity(4);
            if let Err(e) = encode_apdu(&mut buf, &abort) {
                warn!(error = %e, "Failed to encode segmentation-not-supported Abort");
                return;
            }
            let _ = network
                .send_apdu(&buf, source_mac, false, NetworkPriority::NORMAL)
                .await;
            return;
        }

        const MAX_CONCURRENT_SEG_SESSIONS: usize = 64;
        if !seg_state.contains_key(&key) && seg_state.len() >= MAX_CONCURRENT_SEG_SESSIONS {
            warn!(
                invoke_id = ack.invoke_id,
                sessions = seg_state.len(),
                "Max concurrent segmented sessions reached, dropping segment"
            );
            return;
        }

        let proposed_ws = ack.proposed_window_size.unwrap_or(1);
        let state = seg_state
            .entry(key.clone())
            .or_insert_with(|| SegmentedReceiveState {
                receiver: SegmentReceiver::new(),
                reply_mac: MacAddr::from_slice(source_mac),
                expected_next_seq: 0,
                last_activity: Instant::now(),
                window_position: 0,
                proposed_window_size: proposed_ws,
            });

        state.last_activity = Instant::now();

        if seq != state.expected_next_seq {
            // Check for duplicate (already received) vs true gap
            if seq < state.expected_next_seq {
                // Duplicate segment — discard silently and ack
                debug!(
                    invoke_id = ack.invoke_id,
                    seq, "Discarding duplicate segment"
                );
            } else {
                // True gap — send negative SegmentAck with last correctly received seq
                warn!(
                    invoke_id = ack.invoke_id,
                    expected = state.expected_next_seq,
                    received = seq,
                    "Segment gap detected, sending negative SegmentAck"
                );
            }
            let neg_ack = Apdu::SegmentAck(SegmentAckPdu {
                negative_ack: seq >= state.expected_next_seq,
                sent_by_server: false,
                invoke_id: ack.invoke_id,
                // Spec: sequence_number = last correctly received sequence number
                sequence_number: if state.expected_next_seq > 0 {
                    state.expected_next_seq.wrapping_sub(1)
                } else {
                    0
                },
                actual_window_size: proposed_ws,
            });
            let mut buf = BytesMut::with_capacity(4);
            if let Err(e) = encode_apdu(&mut buf, &neg_ack) {
                warn!(error = %e, "Failed to encode negative SegmentAck");
                return;
            }
            if let Err(e) = network
                .send_apdu(&buf, source_mac, false, NetworkPriority::NORMAL)
                .await
            {
                warn!(error = %e, "Failed to send SegmentAck");
            }
            return;
        }

        if let Err(e) = state.receiver.receive(seq, ack.service_ack) {
            warn!(error = %e, "Rejecting oversized segment");
            return;
        }
        state.expected_next_seq = seq.wrapping_add(1);
        state.window_position += 1;

        // Per-window SegmentAck: only ack at window boundary or final segment (Clause 5.2.2)
        let should_ack = !ack.more_follows || state.window_position >= state.proposed_window_size;

        if should_ack {
            state.window_position = 0;
            let seg_ack = Apdu::SegmentAck(SegmentAckPdu {
                negative_ack: false,
                sent_by_server: false,
                invoke_id: ack.invoke_id,
                sequence_number: seq,
                actual_window_size: proposed_ws,
            });
            let mut buf = BytesMut::with_capacity(4);
            if let Err(e) = encode_apdu(&mut buf, &seg_ack) {
                warn!(error = %e, "Failed to encode SegmentAck");
                return;
            }
            if let Err(e) = network
                .send_apdu(&buf, source_mac, false, NetworkPriority::NORMAL)
                .await
            {
                warn!(error = %e, "Failed to send SegmentAck");
            }
        }

        if !ack.more_follows {
            let state = seg_state.remove(&key).unwrap();
            let total = state.receiver.received_count();
            match state.receiver.reassemble(total) {
                Ok(service_data) => {
                    debug!(
                        invoke_id = ack.invoke_id,
                        segments = total,
                        bytes = service_data.len(),
                        "Reassembled segmented ComplexAck"
                    );
                    let mut tsm = tsm.lock().await;
                    tsm.complete_transaction(
                        &tsm_mac,
                        ack.invoke_id,
                        TsmResponse::ComplexAck {
                            service_data: Bytes::from(service_data),
                        },
                    );
                }
                Err(e) => {
                    warn!(error = %e, "Failed to reassemble segmented ComplexAck");
                }
            }
        }
    }
    /// Send a confirmed request using segmented transfer with windowed flow control.
    pub(super) async fn segmented_confirmed_request(
        &self,
        target: ConfirmedTarget<'_>,
        service_choice: ConfirmedServiceChoice,
        service_data: &[u8],
        remote_max_apdu: u16,
        remote_max_segments: Option<u32>,
    ) -> Result<Bytes, Error> {
        let tsm_mac = target.tsm_mac();
        let max_seg_size = max_segment_payload(remote_max_apdu, SegmentedPduType::ConfirmedRequest);
        let segments = split_payload(service_data, max_seg_size)?;
        let total_segments = segments.len();

        if let Some(max_seg) = remote_max_segments {
            if total_segments > max_seg as usize {
                return Err(Error::Segmentation(format!(
                    "request requires {} segments but remote accepts at most {}",
                    total_segments, max_seg
                )));
            }
        }

        debug!(
            total_segments,
            max_seg_size,
            service_data_len = service_data.len(),
            "Starting segmented confirmed request"
        );

        let (invoke_id, rx) = {
            let mut tsm = self.tsm.lock().await;
            let invoke_id = tsm.allocate_invoke_id(&tsm_mac).ok_or_else(|| {
                Error::Encoding("all invoke IDs exhausted for destination".into())
            })?;
            let rx = tsm.register_transaction(tsm_mac.clone(), invoke_id);
            (invoke_id, rx)
        };

        let (seg_ack_tx, mut seg_ack_rx) = mpsc::channel(16);
        {
            let key = (tsm_mac.clone(), invoke_id);
            self.seg_ack_senders.lock().await.insert(key, seg_ack_tx);
        }

        // Tseg: use APDU timeout for now (configurable via apdu_timeout_ms)
        let timeout_duration = Duration::from_millis(self.config.apdu_timeout_ms);
        let max_ack_retries = self.config.apdu_retries;
        let mut window_size = self.config.proposed_window_size.max(1) as usize;
        let mut next_seq: usize = 0;
        let mut neg_ack_retries: u32 = 0;
        const MAX_NEG_ACK_RETRIES: u32 = 10;

        let result = async {
            while next_seq < total_segments {
                let window_end = (next_seq + window_size).min(total_segments);

                for (seq, segment_data) in segments[next_seq..window_end]
                    .iter()
                    .enumerate()
                    .map(|(i, s)| (next_seq + i, s))
                {
                    let is_last = seq == total_segments - 1;
                    let pdu = Apdu::ConfirmedRequest(ConfirmedRequestPdu {
                        segmented: true,
                        more_follows: !is_last,
                        segmented_response_accepted: self.config.segmented_response_accepted,
                        max_segments: self.config.max_segments,
                        max_apdu_length: self.config.max_apdu_length,
                        invoke_id,
                        sequence_number: Some(seq as u8),
                        proposed_window_size: Some(self.config.proposed_window_size.max(1)),
                        service_choice,
                        service_request: segment_data.clone(),
                    });

                    let mut buf = BytesMut::with_capacity(remote_max_apdu as usize);
                    encode_apdu(&mut buf, &pdu)?;

                    self.send_confirmed_target_apdu(target, &buf).await?;

                    debug!(seq, is_last, "Sent segment");
                }

                let ack = {
                    let mut ack_retries: u8 = 0;
                    loop {
                        match timeout(timeout_duration, seg_ack_rx.recv()).await {
                            Ok(Some(ack)) => break ack,
                            Ok(None) => {
                                return Err(Error::Encoding("SegmentAck channel closed".into()));
                            }
                            Err(_timeout) => {
                                ack_retries += 1;
                                if ack_retries > max_ack_retries {
                                    return Err(Error::Timeout(timeout_duration));
                                }
                                warn!(
                                    attempt = ack_retries,
                                    "Retransmitting segmented request window"
                                );
                                for (seq, segment_data) in segments[next_seq..window_end]
                                    .iter()
                                    .enumerate()
                                    .map(|(i, s)| (next_seq + i, s))
                                {
                                    let is_last = seq == total_segments - 1;
                                    let pdu = Apdu::ConfirmedRequest(ConfirmedRequestPdu {
                                        segmented: true,
                                        more_follows: !is_last,
                                        segmented_response_accepted: self
                                            .config
                                            .segmented_response_accepted,
                                        max_segments: self.config.max_segments,
                                        max_apdu_length: self.config.max_apdu_length,
                                        invoke_id,
                                        sequence_number: Some(seq as u8),
                                        proposed_window_size: Some(
                                            self.config.proposed_window_size.max(1),
                                        ),
                                        service_choice,
                                        service_request: segment_data.clone(),
                                    });

                                    let mut buf = BytesMut::with_capacity(remote_max_apdu as usize);
                                    encode_apdu(&mut buf, &pdu)?;

                                    self.send_confirmed_target_apdu(target, &buf).await?;
                                }
                            }
                        }
                    }
                };

                debug!(
                    seq = ack.sequence_number,
                    negative = ack.negative_ack,
                    window = ack.actual_window_size,
                    "Received SegmentAck"
                );

                window_size = ack.actual_window_size.max(1) as usize;

                let ack_seq = ack.sequence_number as usize;
                if ack_seq >= total_segments {
                    return Err(Error::Segmentation(format!(
                        "SegmentAck sequence {} out of range (total {})",
                        ack_seq, total_segments
                    )));
                }

                if ack.negative_ack {
                    neg_ack_retries += 1;
                    if neg_ack_retries > MAX_NEG_ACK_RETRIES {
                        return Err(Error::Segmentation(
                            "too many negative SegmentAck retransmissions".into(),
                        ));
                    }
                    next_seq = ack_seq + 1;
                } else {
                    neg_ack_retries = 0;
                    next_seq = ack_seq + 1;
                }
            }

            timeout(timeout_duration, rx)
                .await
                .map_err(|_| Error::Timeout(timeout_duration))?
                .map_err(|_| Error::Encoding("TSM response channel closed".into()))
        }
        .await;

        {
            let key = (tsm_mac.clone(), invoke_id);
            self.seg_ack_senders.lock().await.remove(&key);
        }

        let response = match result {
            Ok(response) => response,
            Err(e) => {
                let mut tsm = self.tsm.lock().await;
                tsm.cancel_transaction(&tsm_mac, invoke_id);
                return Err(e);
            }
        };

        match response {
            TsmResponse::SimpleAck => Ok(Bytes::new()),
            TsmResponse::ComplexAck { service_data } => Ok(service_data),
            TsmResponse::Error { class, code } => Err(Error::Protocol { class, code }),
            TsmResponse::Reject { reason } => Err(Error::Reject { reason }),
            TsmResponse::Abort { reason } => Err(Error::Abort { reason }),
        }
    }
}
