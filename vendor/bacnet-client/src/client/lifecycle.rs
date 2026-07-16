use super::*;

impl<T: TransportPort + 'static> BACnetClient<T> {
    /// Start the client: bind transport, start network layer, spawn dispatch.
    pub async fn start(mut config: ClientConfig, transport: T) -> Result<Self, Error> {
        let transport_max = transport.max_apdu_length();
        config.max_apdu_length = config.max_apdu_length.min(transport_max);
        validate_max_apdu_length(config.max_apdu_length)?;
        if !(1..=127).contains(&config.proposed_window_size) {
            return Err(Error::Encoding(format!(
                "invalid proposed-window-size {}; expected 1..=127",
                config.proposed_window_size
            )));
        }

        let mut network = NetworkLayer::new(transport);
        let mut apdu_rx = network.start().await?;
        let local_mac = MacAddr::from_slice(network.local_mac());

        let network = Arc::new(network);

        let tsm_config = TsmConfig {
            apdu_timeout_ms: config.apdu_timeout_ms,
            apdu_segment_timeout_ms: config.apdu_timeout_ms,
            apdu_retries: config.apdu_retries,
        };
        let tsm = Arc::new(Mutex::new(Tsm::new(tsm_config)));
        let tsm_dispatch = Arc::clone(&tsm);
        let device_table = Arc::new(Mutex::new(DeviceTable::new()));
        let device_table_dispatch = Arc::clone(&device_table);
        let network_dispatch = Arc::clone(&network);
        let (cov_tx, _) = broadcast::channel::<COVNotificationRequest>(64);
        let cov_tx_dispatch = cov_tx.clone();
        let seg_ack_senders: Arc<Mutex<HashMap<SegKey, mpsc::Sender<SegmentAckPdu>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let seg_ack_senders_dispatch = Arc::clone(&seg_ack_senders);
        let segmented_response_accepted = config.segmented_response_accepted;

        let dispatch_task = tokio::spawn(async move {
            let mut seg_state: HashMap<SegKey, SegmentedReceiveState> = HashMap::new();
            let mut last_device_purge = Instant::now();
            const DEVICE_PURGE_INTERVAL: Duration = Duration::from_secs(300);
            const DEVICE_MAX_AGE: Duration = Duration::from_secs(600);

            while let Some(received) = apdu_rx.recv().await {
                let now = Instant::now();

                // Periodically purge stale device table entries
                if now.duration_since(last_device_purge) >= DEVICE_PURGE_INTERVAL {
                    device_table_dispatch
                        .lock()
                        .await
                        .purge_stale(DEVICE_MAX_AGE);
                    last_device_purge = now;
                }
                // Reap stale segmented sessions and send Abort to the server
                let stale_keys: Vec<SegKey> = seg_state
                    .iter()
                    .filter(|(_, state)| {
                        now.duration_since(state.last_activity) >= SEG_RECEIVER_TIMEOUT
                    })
                    .map(|(key, _)| key.clone())
                    .collect();
                for key in &stale_keys {
                    if let Some(state) = seg_state.remove(key) {
                        let abort = Apdu::Abort(AbortPdu {
                            sent_by_server: false,
                            invoke_id: key.1,
                            abort_reason: bacnet_types::enums::AbortReason::TSM_TIMEOUT,
                        });
                        let mut buf = BytesMut::with_capacity(4);
                        if let Err(e) = encode_apdu(&mut buf, &abort) {
                            warn!(error = %e, "Failed to encode segmented receive timeout Abort");
                            continue;
                        }
                        let _ = network_dispatch
                            .send_apdu(&buf, &state.reply_mac, false, NetworkPriority::NORMAL)
                            .await;
                    }
                }

                match apdu::decode_apdu(received.apdu.clone()) {
                    Ok(decoded) => {
                        Self::dispatch_apdu(
                            &tsm_dispatch,
                            &device_table_dispatch,
                            &network_dispatch,
                            &cov_tx_dispatch,
                            &mut seg_state,
                            &seg_ack_senders_dispatch,
                            &received.source_mac,
                            &received.source_network,
                            decoded,
                            segmented_response_accepted,
                        )
                        .await;
                    }
                    Err(e) => {
                        warn!(error = %e, "Failed to decode received APDU");
                    }
                }
            }
        });

        Ok(Self {
            config,
            network,
            tsm,
            device_table,
            cov_tx,
            dispatch_task: Some(dispatch_task),
            seg_ack_senders,
            local_mac,
        })
    }
    /// Get the client's local MAC address.
    pub fn local_mac(&self) -> &[u8] {
        &self.local_mac
    }
    /// Stop the client, aborting the dispatch task.
    pub async fn stop(&mut self) -> Result<(), Error> {
        if let Some(task) = self.dispatch_task.take() {
            task.abort();
            let _ = task.await;
        }
        Ok(())
    }
}
