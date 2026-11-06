# BACnet site scan

`bacnet_site_scan.py` is a one-file, **read-only** BACnet/IP site scanner (bacpypes3). It uses Who-Is,
Who-Is-Router-To-Network, ReadProperty and ReadPropertyMultiple; it never writes to a device. Use it to
document a building's controllers before you model them in NF, or to look for supervisory commands
and operator overrides on commandable points.

Run it from a PC on the BACnet LAN, **never on the NF box or a Raspberry Pi** (NF owns UDP 47808 there, and
the scan needs tens of MB of RAM).

```bash
python -m venv env && env/bin/pip install bacpypes3 ifaddr rdflib
env/bin/python tools/bacnet-scan/bacnet_site_scan.py --check-fix                              # which bacpypes3 RDF fixes you have
env/bin/python tools/bacnet-scan/bacnet_site_scan.py --address 192.0.2.50/24 --discover-only  # list devices and routers only
env/bin/python tools/bacnet-scan/bacnet_site_scan.py --address 192.0.2.50/24 --out-dir scans   # full scan
env/bin/python tools/bacnet-scan/bacnet_site_scan.py --address 192.0.2.50/24 --stamp --console-table
```

`--low` / `--high` limit the device-instance range (default 0 to 4194303). Every run overwrites the last one
unless you pass `--stamp`.

## Output

| File | What |
|---|---|
| `<name>.csv` | one row per object: name, description, present value, units, reliability, status flags, priority-array command and active priority |
| `<name>_devices.csv` | one row per device: vendor, model, firmware, application software, protocol revision, segmentation, max APDU, MS/TP max-master, network, router |
| `<name>_topology.csv` | routers, the networks behind them, and every device's network |
| `<name>.ttl` | RDF Turtle from `bacpypes3.rdf.BACnetGraph` (standard `bacnet:` terms) plus our derived facts under `scan:` (`urn:bacnet-site-scan:`): topology, active priority, reference links, scan provenance |

The script self-checks what it wrote (skip with `--no-validate`). Drop the `scan:` terms and the Turtle is plain
bacpypes3 BACnet RDF.

## Prerequisites and gotchas

- **UDP 47808 must be free** on the scanning PC. Who-Is answers are broadcast to 47808, so a client on another
  port sees nothing. Close BACnet explorers and discovery tools, and Niagara stations, or scan from another host.
  See [BACnet validation](../../docs/operations/nf/bacnet-validate.md).
- Install bacpypes3 with the RDF fixes (JoelBender/BACpypes3 pull request 181, merged; and ideally 183 for
  Any/AnyAtomic/DateTime values). `--check-fix` tells you which you have. The script unwraps AnyAtomic itself, so it
  still runs on a release without 183.
- BACnet does not record **who wrote** a priority-array slot. The scan shows which slot is active (priority 8 is a
  manual operator override; others are automatic or supervisory); finding the writer needs inference or the
  vendor's tools.
- Everything the scan reports comes from the network. To model the points in NF use the NF scan and the
  [Haystack tagging guide](../../docs/operations/nf/haystack-tagging.md); the scan is for documentation and audit.
