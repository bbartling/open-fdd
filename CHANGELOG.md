# Changelog

## Unreleased

- Archive the BACnet, Modbus, Haystack field containers, MQTT broker, MQTT client (`crates/openfdd_mqtt`), connector runtime, and edge process under `archive/ot-edge/unmaintained/`. They are not workspace members, not built by CI, and not published to GHCR.
- Product ingest is the Normal Framework portal and CSV only. Central no longer subscribes to MQTT, does not serve edge, command, or field-protocol routes, and `/api/health` reports portal provider count plus CSV ingest instead of edge and MQTT counters. The compiled Parquet micro-batch writer is gone; the historian is Timescale.
- Retire the BACnet/MQTT CI workflow, Wave C isolated workflow, standalone MQTTS smoke, MQTT/BACnet guard gates, the broker ACL / field-exposure security checks, and the OT compose-selection checker. `openfdd_health_check.sh` stays for the portal.
