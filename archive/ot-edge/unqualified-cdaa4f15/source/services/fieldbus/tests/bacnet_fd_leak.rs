//! Regression test for #535: `BACnetClient::stop()` must stop the transport so
//! the UDP socket fd is released. Before the vendored fix, every short-lived
//! client (one per poll/read operation) leaked one socket until EMFILE killed
//! HTTP and weather after a few hours of uptime.

#![cfg(target_os = "linux")]

use std::net::Ipv4Addr;

use bacnet_client::client::BACnetClient;

fn open_fd_count() -> usize {
    std::fs::read_dir("/proc/self/fd")
        .expect("read /proc/self/fd")
        .count()
}

#[tokio::test]
async fn client_stop_closes_transport_socket() {
    // Warm up runtime / lazy fds so the baseline is stable.
    for _ in 0..3 {
        let mut client = BACnetClient::bip_builder()
            .interface(Ipv4Addr::LOCALHOST)
            .port(0)
            .broadcast_address(Ipv4Addr::BROADCAST)
            .build()
            .await
            .expect("start client");
        client.stop().await.expect("stop client");
    }

    let baseline = open_fd_count();
    const ITERATIONS: usize = 50;
    for _ in 0..ITERATIONS {
        let mut client = BACnetClient::bip_builder()
            .interface(Ipv4Addr::LOCALHOST)
            .port(0)
            .broadcast_address(Ipv4Addr::BROADCAST)
            .build()
            .await
            .expect("start client");
        client.stop().await.expect("stop client");
    }
    let after = open_fd_count();

    assert!(
        after <= baseline + 3,
        "fd leak: baseline {baseline} -> {after} after {ITERATIONS} client start/stop cycles"
    );
}
