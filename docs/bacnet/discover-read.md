---
title: Discover and read
parent: BACnet
nav_order: 2
---

# Discover and read

The **commission** container exposes HTTP APIs for discovery and read-property workflows used by the dashboard BACnet tools.

| Capability | Notes |
|------------|-------|
| Who-Is / I-Am | Device discovery on OT subnet |
| Read property | Present value, object name, units |
| RPM | Bulk reads for inventory export |
| Write property | **Gated** — see [Write safety](write-safety) |

Exported inventory feeds `points_discovered.csv` and the Brick point registry.

## Operator workflow

1. Confirm [network setup](network-setup).
2. Run discover from dashboard or API.
3. Review discovered objects; enable points for poll profiles.
4. Sync model bindings for FDD inputs.
