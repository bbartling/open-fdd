# Vendored bacnet-client 0.9.0 (from crates.io) with one Open-FDD patch:
# `BACnetClient::add_routed_device` — seeds MS/TP devices with source_network +
# source_address so RPM/ReadProperty route through the BIP router (bench device 5007).
#
# Open-FDD also patches `DeviceTable::upsert` to preserve routing metadata when a
# later I-Am arrives without NPDU source routing (ephemeral client ports).
#
# Remove this vendor + `[patch.crates-io]` in the workspace Cargo.toml when
# https://github.com/jscott3201/rusty-bacnet publishes an equivalent API.
