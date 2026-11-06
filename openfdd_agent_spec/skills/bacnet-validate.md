---
name: bacnet-validate
description: Prove NF's values equal what the BACnet devices answer on the wire (read-only, from a PC, never from the NF box).
---
# Validate NF against the BACnet wire

Tool: `scripts/nf/tools/nf_bacnet_validate.py` (needs `pip install bacpypes3 ifaddr`). Runbook: `docs/operations/nf/bacnet-validate.md`.

1. Run it on a PC on the BACnet LAN. **Never on the NF box or a Pi**: NF owns UDP 47808 there. Never write to field devices.
2. Put `NF_LAN_URL`, `NF_CLIENT_ID`, `NF_CLIENT_SECRET` (read-only key) in an env file outside git; pass `--env FILE`.
3. Free UDP 47808 on the PC first (`ss -ulpn | grep 47808`, `netstat -ano | findstr 47808`): close BACnet discovery
   tools and Niagara stations, or no I-Am will arrive.
4. `python3 scripts/nf/tools/nf_bacnet_validate.py --env <env file> --address <pc-ip>/<prefix>`.
   It checks NF's BACnet server (config vs wire, `bacnet_object` links) and every trended point with
   `deviceRef` + `device_id` + `object_id` (wire value vs NF latest, `--tolerance`, binary exact).
5. Through the portal use `--via portal`: the server check is skipped (401 on `/api/v1/bacnet/*` for API keys).
6. A FAIL is a finding to report, not something to "fix" by renaming points: check tags and polling first.

Never hard-code a device, point or IP in the tool; everything comes from NF's model. For documenting a whole network
use `tools/bacnet-scan/bacnet_site_scan.py` (same rules). Known NF limits: `docs/operations/nf/nf-gotchas.md`.
