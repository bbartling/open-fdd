# Open-FDD local BACnet server (diagnostics)

Open-FDD exposes a **small local BACnet device** so operators and BACnet tools can discover the edge runtime itself. This is separate from field controllers (AHUs, VAVs, bench devices, etc.).

## Identity

| Setting | Default |
| --- | --- |
| Device name | `OpenFDD` |
| Device instance | `599999` (`OPENFDD_BACNET_DEVICE_INSTANCE`) |

## Status objects

| Object | Instance | Purpose |
| --- | --- | --- |
| `binary-value` | 9001 | `openfdd-edge-online` — bridge/API health |
| `binary-value` | 9002 | `openfdd-commission-agent` — BACnet commission service health |
| `analog-value` | 9001 | `openfdd-poll-sample-count` — latest poll/historian sample count |
| `analog-value` | 9002 | `openfdd-devices-discovered` — discovered BACnet field devices |
| `analog-value` | 9003 | `openfdd-active-fault-count` — active/confirmed FDD faults |

## API

- `GET /api/bacnet/server/points` — local server point list + live metric values
- Included under **BACnet/IP → Local OpenFDD Server** in the unified driver tree (`GET /api/drivers/tree`)

## Driver tree placement

Field devices and the local OpenFDD server appear under separate nodes so operators do not confuse diagnostic points with OT controllers.

## Related

- [Drivers + FDD architecture](drivers-and-fdd.md)
- [BACnet override verification](../verification/bacnet-overrides.md)
