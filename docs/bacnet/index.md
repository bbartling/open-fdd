---
title: BACnet
nav_order: 58
has_children: true
---

# BACnet

BACpypes3 **commissioning**, **polling**, and **bridge APIs** for field BACnet/IP and MS/TP (via IP router). The PyPI `open-fdd` engine does not include BACnet — only this repo checkout.

| Doc | Content |
|-----|---------|
| **[Driver capabilities](capabilities)** | **Supported vs not** — discover, read, RPM, write, release, priority-array, poll, mapping |
| [BRICK + BACnet](../bacnet-rdf-and-brick) | Model import and `fdd_input` |
| [Getting started — bind](../getting_started#3-bacnet-lab-bind-see-devices-on-ot-nic) | `BACNET_BIND`, bench overlay |
| [Bridge API — BACnet](../appendix/bridge_api#bacnet) | REST table |

**Repo:** `bacnet_toolshed/README.md` for CLI (`discover`, `enable_points`, `poll_driver`, `commission_agent`).
