---
title: BACnet validation
parent: NF operations
nav_order: 5
---

# Validate NF against the BACnet wire

Prove that what NF reports (API, dashboard, rules) equals what the devices actually answer on BACnet/IP.
[`nf_bacnet_validate.py`](https://github.com/bbartling/open-fdd/tree/master/scripts/nf/tools) does it with
[bacpypes3](https://github.com/JoelBender/BACpypes3), driven entirely by NF's own config and Haystack tags.

{: .warning }
Run it on a **PC on the BACnet LAN**, never on the NF box or a Raspberry Pi. NF owns UDP 47808 there, and a
Python BACnet stack is heavy for a 1 GB host. The tool is read-only: Who-Is and ReadProperty only, no writes.

## What it checks

1. **NF's BACnet server.** The device instance and local objects come from `/api/v1/bacnet/configuration` and
   `/api/v1/bacnet/local`. Over the wire: Who-Is finds the device, `object-list` equals the configured objects, and
   `object-name`, `units` and `present-value` match. If a Haystack point names the object in `bacnet_object`
   (for example `av.1`), its latest value must match too.
2. **Field devices.** Every trended point with `deviceRef` and the BACnet binding attrs NF stores (`device_id`,
   `object_id` such as `ai.12`) is read at that address, and the wire value must match NF's latest value within
   `--tolerance` (binary points exactly). Routed devices (MS/TP behind a router) work because Who-Is answers carry
   the route.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install bacpypes3 ifaddr
python3 scripts/nf/tools/nf_bacnet_validate.py --env ~/.secrets/nf_api.env --address 192.0.2.50/24
python3 scripts/nf/tools/nf_bacnet_validate.py --env ~/.secrets/nf_api.env --address 192.0.2.50/24 --tolerance 0.5
```

`--address` is the PC's own BACnet/IP address as `<ip>/<prefix>`. Find the right NIC with `ip -br addr` (Linux) or
`ipconfig` (Windows). The env file holds `NF_LAN_URL`, `NF_CLIENT_ID` and `NF_CLIENT_SECRET`
(see [`scripts/nf/tools/README.md`](https://github.com/bbartling/open-fdd/blob/master/scripts/nf/tools/README.md)).
Without bacpypes3 the script still prints `--help` and tells you what to install.

Output is one `PASS` / `FAIL` line per check and a summary; exit code 1 on any failure. Numbers can differ slightly
because NF polls on a period and the value moved since: widen `--tolerance` before suspecting a fault.

## Port 47808 must be free on the PC

BACnet/IP answers come back to UDP 47808. If another program on the PC holds that port, Who-Is replies never reach
bacpypes3 and you see "no I-Am". Common holders: BACnet discovery or explorer tools, a Niagara station,
another bacpypes3 shell, a vendor tool. Find and stop it:

```bash
sudo ss -ulpn | grep 47808 || echo "47808 free"       # Linux
lsof -iUDP:47808; fuser -v 47808/udp                  # Linux / macOS
netstat -ano | findstr 47808                           # Windows (then match the PID in Task Manager)
```

Close the tool, stop the service, or run from another machine. A program that runs elevated cannot be stopped from
a normal shell. As a workaround for **unicast** reads only, bind another port (`--address 192.0.2.50/24:47809`);
Who-Is and I-Am broadcasts still need 47808.

## Through the portal

An API key through the Normal Online portal gets **401 on `/api/v1/bacnet/*`**, so the server check cannot read NF's
BACnet configuration there. `--via portal` skips that part (with a note) and still validates the field points
against the portal's values. For the server check use the LAN path.

## BACnet server limits that affect what you can validate

- NF can serve analog, binary and multi-state values; **character-string, date and date-time values are rejected**
  (`unsupported object type`). Keep metadata (location, update times) in Haystack tags, not in BACnet objects.
- A multi-state present value must be written as `{"enumerated": N}` and is served with an Enumerated tag, so strict
  clients such as bacpypes3 cannot read it. Avoid multi-state values for anything an external client must read.

## Site scan (documentation, not validation)

To document every controller on a network (vendor, model, firmware, routers, commandable points and which
priority slot is active) and write CSV and RDF, use [`tools/bacnet-scan/`](https://github.com/bbartling/open-fdd/tree/master/tools/bacnet-scan).
Same rules: a PC, free port 47808, read-only.
