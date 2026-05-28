---
name: diy-bacnet-bench-sidecar
description: "Runs DIY BACnet server JSON-RPC as an optional bench sidecar behind Caddy. Use for BACnet integration testing with generated stacks."
---

# DIY BACnet bench sidecar

Service on 8080; Caddy `/api/diy/*`; protect with `BACNET_RPC_API_KEY`.

Ansible role `diy_bacnet`; vars `diy_bacnet_port`, `diy_bacnet_instance`, `diy_bacnet_name`.
