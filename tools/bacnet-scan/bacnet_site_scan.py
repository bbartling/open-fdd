#!/usr/bin/env python
"""
bacnet_site_scan.py - one-file, read-only BACnet/IP site scanner.

Finds every device (Who-Is) and every BACnet router (Who-Is-Router-To-Network),
reads each device's facts and objects, and writes:

  <out-dir>/<name>.csv           one row per object (device rows included), with who holds
                                 the command (active priority slot) on commandable objects
  <out-dir>/<name>_devices.csv   one row per device: model, firmware, app software, protocol
                                 revision, segmentation, max APDU, MS/TP max-master, ...
  <out-dir>/<name>.ttl           RDF Turtle via bacpypes3.rdf.BACnetGraph, plus the network
                                 layout, active priorities, reference links and scan provenance
  <out-dir>/<name>_topology.csv  routers, the networks they route to, and every device's network

Every run overwrites the last scan. Pass --stamp to keep a timestamped copy instead.
Reads only (Who-Is, Who-Is-Router-To-Network, ReadProperty, ReadPropertyMultiple).
It never writes to a device.

Quick start (see README.md for installing bacpypes3 with the RDF fixes):
  python bacnet_site_scan.py --check-fix
  python bacnet_site_scan.py --address 192.0.2.50/24 --discover-only
  python bacnet_site_scan.py --address 192.0.2.50/24
  python bacnet_site_scan.py --address 192.0.2.50/24 --stamp --console-table

UDP 47808 must be free on this machine (close YABE, BACnet Discovery Tool, Niagara, etc.).
"""

import asyncio
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rdflib import BNode, Graph, Literal, Namespace, URIRef, RDF  # type: ignore
from rdflib.namespace import PROV, XSD  # type: ignore

import bacpypes3
from bacpypes3.apdu import AbortPDU, ErrorRejectAbortNack, ErrorType
from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.basetypes import PriorityArray, PropertyIdentifier, StatusFlags
from bacpypes3.constructeddata import AnyAtomic, ArrayOf
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Real
from bacpypes3.rdf import BACnetGraph
from bacpypes3.vendor import get_vendor_info

MAX_INSTANCE = 4194303

# Device object facts: what a retrofit / RCx engineer writes down about each controller.
DEVICE_PROPS = [
    "object-name", "description", "location",
    "vendor-name", "vendor-identifier", "model-name", "serial-number",
    "firmware-revision", "application-software-version",
    "protocol-version", "protocol-revision",
    "protocol-services-supported", "protocol-object-types-supported",
    "segmentation-supported", "max-apdu-length-accepted", "max-segments-accepted",
    "apdu-timeout", "number-of-apdu-retries", "max-master", "max-info-frames",
    "system-status", "database-revision", "last-restart-reason", "time-of-device-restart",
    "utc-offset", "daylight-savings-status", "local-date", "local-time",
    "backup-and-restore-state", "configuration-files", "device-address-binding",
    "structured-object-list", "active-cov-subscriptions",
    "time-synchronization-recipients", "utc-time-synchronization-recipients",
]
# compact columns for <name>_devices.csv (long lists stay in the Turtle)
DEVICE_FIELDS = [
    "DeviceID", "Address", "Network", "VendorID", "Name", "Description", "Location",
    "VendorName", "ModelName", "SerialNumber", "FirmwareRevision", "ApplicationSoftwareVersion",
    "ProtocolVersion", "ProtocolRevision", "SegmentationSupported", "MaxApduLengthAccepted",
    "MaxSegmentsAccepted", "ApduTimeout", "NumberOfApduRetries", "MaxMaster", "MaxInfoFrames",
    "SystemStatus", "DatabaseRevision", "LastRestartReason", "UtcOffset", "DaylightSavingsStatus",
    "ServicesSupported", "ObjectTypesSupported", "AddressBindings", "ReadMethod", "PropsRead", "PropsMissing",
]
DEVICE_COLUMN = {
    "object-name": "Name", "description": "Description", "location": "Location",
    "vendor-name": "VendorName", "model-name": "ModelName", "serial-number": "SerialNumber",
    "firmware-revision": "FirmwareRevision", "application-software-version": "ApplicationSoftwareVersion",
    "protocol-version": "ProtocolVersion", "protocol-revision": "ProtocolRevision",
    "segmentation-supported": "SegmentationSupported", "max-apdu-length-accepted": "MaxApduLengthAccepted",
    "max-segments-accepted": "MaxSegmentsAccepted", "apdu-timeout": "ApduTimeout",
    "number-of-apdu-retries": "NumberOfApduRetries", "max-master": "MaxMaster",
    "max-info-frames": "MaxInfoFrames", "system-status": "SystemStatus",
    "database-revision": "DatabaseRevision", "last-restart-reason": "LastRestartReason",
    "utc-offset": "UtcOffset", "daylight-savings-status": "DaylightSavingsStatus",
}

OBJECT_PROPS = [
    "object-name", "description", "present-value", "units",
    "status-flags", "reliability", "out-of-service", "event-state",
    # command ownership on commandable objects
    "priority-array", "relinquish-default", "current-command-priority",
    "value-source", "last-command-time",
]
CSV_FIELDS = [
    "DeviceID", "IP", "Network", "VendorID", "ObjType", "ObjInst", "Name", "Description",
    "PresentValue", "Units", "StatusFlags", "Reliability", "OutOfService", "EventState",
    "PriorityArray", "RelinquishDefault", "ActivePriority", "Command",
]
TOPO_FIELDS = ["kind", "router_address", "network", "device_id", "device_address", "vendor_id", "device_name"]

# BACnet standard priority meanings (ASHRAE 135, Clause 19.2.1.1); others are "available"
PRIORITY_NAMES = {
    1: "manual-life-safety", 2: "automatic-life-safety", 5: "critical-equipment-control",
    6: "minimum-on-off", 8: "manual-operator",
}

BACNET = Namespace("http://data.ashrae.org/bacnet/")
SCAN = Namespace("urn:bacnet-site-scan:")
# bacpypes3 raises BACnet errors/rejects/aborts as BaseException subclasses, not Exception
READ_ERRORS = (ErrorRejectAbortNack, AbortPDU, Exception)


def log(msg: str = "", end: str = "\n") -> None:
    print(msg, end=end, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- fix checks
def _proxy() -> Tuple[Graph, Any]:
    g = Graph()
    obj = BACnetGraph(g).create_device(Address("192.0.2.10"), ObjectIdentifier("device,1")) \
        .create_object(ObjectIdentifier("analog-value,1"))
    return g, obj


def rdf_fix_present() -> bool:
    """True when bacpypes3.rdf has the ObjectProxy fix (JoelBender/BACpypes3#181):
    status flags with a bit set and an ArrayOf become RDF lists, not an error or Python text."""
    g, obj = _proxy()
    try:
        obj.statusFlags = StatusFlags([0, 0, 1, 0])
        obj.stateText = ArrayOf(CharacterString)(["Off", "On"])
        ttl = g.serialize(format="turtle")
        return "StatusFlags.overridden" in ttl and "['Off'" not in ttl
    except AttributeError:
        return False


def anyvalue_fix_present() -> bool:
    """True when bacpypes3.rdf also encodes AnyAtomic values (relinquish-default,
    schedule-default, ...) as literals instead of Python text (the follow-up to #181)."""
    g, obj = _proxy()
    try:
        obj.relinquishDefault = AnyAtomic(Real(72.0))
        return " object at 0x" not in g.serialize(format="turtle")
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- formatting
def plain(val: Any) -> Any:
    """Unwrap AnyAtomic so older bacpypes3 builds don't write Python text into the Turtle."""
    if isinstance(val, AnyAtomic):
        try:
            return val.get_value()
        except Exception:  # noqa: BLE001
            return val
    return val


def priority_slots(pa: Optional[PriorityArray]) -> Dict[int, str]:
    """{priority: value} for the non-empty slots (1-based)."""
    out: Dict[int, str] = {}
    if not pa:
        return out
    for i, slot in enumerate(pa):
        if slot is None:
            continue
        choice = slot._choice
        # newer bacpypes3 returns empty slots as the `null` choice, not None
        if choice and choice != "null":
            out[i + 1] = str(plain(getattr(slot, choice)))
    return out


def fmt_priority_array(slots: Dict[int, str]) -> str:
    return "{" + ", ".join(f"{k}: {v}" for k, v in slots.items()) + "}"


def fmt_status_flags(sf: Any) -> str:
    names = ["in-alarm", "fault", "overridden", "out-of-service"]
    try:
        bits = list(sf)
    except TypeError:
        return str(sf)
    return ",".join(n for n, b in zip(names, bits) if b) or "normal"


def fmt_bits(bs: Any) -> str:
    """Names of the set bits in a BitString (services / object types supported)."""
    try:
        names = {v: k for k, v in bs._bitstring_names.items()}
        return " ".join(names.get(i, str(i)) for i, b in enumerate(bs) if b)
    except Exception:  # noqa: BLE001
        return str(bs)


def command_note(slots: Dict[int, str], flags: str, has_pa: bool) -> str:
    """What the priority array says about who is commanding the object.
    Observed facts only; the analyze-writes.py step does the inference."""
    if slots:
        p = min(slots)
        name = PRIORITY_NAMES.get(p, "available")
        note = f"P{p} {name}"
        if len(slots) > 1:
            note += " over " + ",".join(f"P{q}" for q in sorted(slots)[1:])
        return note
    if "overridden" in flags:
        # e.g. JCI FEC internal logic objects: flag set by local logic / HOA, no BACnet command
        return "overridden flag, no priority slot" if has_pa else "overridden flag (not commandable)"
    return "relinquished" if has_pa else ""


def network_of(addr: Address) -> str:
    """'local' for a device on this IP subnet, else its BACnet network number."""
    s = str(addr)
    return s.split(":", 1)[0] if ":" in s and not s.count(".") == 3 else "local"


# ---------------------------------------------------------------- reads
async def read_object_list(app: Application, addr: Address, dev_id: ObjectIdentifier) -> List[ObjectIdentifier]:
    """Read the whole object-list, falling back to index-by-index for small-APDU devices."""
    try:
        val = await app.read_property(addr, dev_id, "object-list")
        if isinstance(val, list):
            return val
    except (AbortPDU, ErrorRejectAbortNack):
        pass
    except Exception as e:  # noqa: BLE001
        log(f"    [object-list read error: {e}]")

    log("    (falling back to index-by-index)", end="")
    out: List[ObjectIdentifier] = []
    try:
        n = await app.read_property(addr, dev_id, "object-list", array_index=0)
        for i in range(n):
            out.append(await app.read_property(addr, dev_id, "object-list", array_index=i + 1))
            if i % 10 == 0:
                log(".", end="")
        log(" done")
    except READ_ERRORS as e:
        log(f" failed: {e}")
    return out


async def safe_read(app: Application, addr: Address, oid: Any, prop: str) -> Any:
    try:
        return await app.read_property(addr, oid, prop)
    except READ_ERRORS:
        return None


async def read_props(app: Application, addr: Address, oid: ObjectIdentifier, props: List[str],
                     chunk: int = 8) -> Tuple[Dict[str, Any], Dict[str, str], str]:
    """Read many properties of one object: ReadPropertyMultiple in small chunks (MS/TP-friendly),
    falling back to one ReadProperty per property when the device doesn't do RPM.
    Returns (values, errors, method) where errors maps a property to 'unknown-property', etc."""
    values: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    method = "rpm"
    for i in range(0, len(props), chunk):
        part = props[i:i + chunk]
        try:
            res = await app.read_property_multiple(addr, [oid, part])
        except READ_ERRORS as e:
            res = e
        if isinstance(res, list):
            for _oid, pid, _idx, val in res:
                key = str(PropertyIdentifier(pid))
                if isinstance(val, ErrorType):
                    errors[key] = str(val.errorCode)
                else:
                    values[key] = val
            continue
        method = "rp"
        for p in part:
            try:
                values[p] = await app.read_property(addr, oid, p)
            except ErrorRejectAbortNack as e:
                errors[p] = str(getattr(e, "errorCode", None) or e)
            except READ_ERRORS as e:
                errors[p] = type(e).__name__
    return values, errors, method


# ---------------------------------------------------------------- RDF post-pass
def link_references(g: Graph) -> int:
    """Give every reference (DeviceObjectPropertyReference, DeviceObjectReference, ...) in the graph
    a real edge to the object it names: [bacnet:object-identifier "analog-value,1"] gets
    scan:refersTo <bacnet://<device>/analog-value,1>. The device is the reference's own
    device-identifier, else the device that owns the object holding the reference.
    This is what makes "which schedule / trend log / loop points at which field object" queryable."""
    owner: Dict[Any, Any] = {}
    for dev, obj in g.subject_objects(BACNET.contains):
        owner[obj] = dev

    def owning_device(node: Any, seen: set) -> Any:
        if node in owner:
            return owner[node]
        if node in seen:
            return None
        seen.add(node)
        for s in g.subjects(None, node):
            d = owning_device(s, seen)
            if d is not None:
                return d
        return None

    n = 0
    for ref, oid in list(g.subject_objects(BACNET["object-identifier"])):
        if not isinstance(ref, BNode):
            continue  # an object's own identifier, not a reference
        dev_id = g.value(ref, BACNET["device-identifier"])
        if dev_id is not None:
            dev = URIRef(f"bacnet://{str(dev_id).split(',')[1]}")
        else:
            dev = owning_device(ref, set())
        if dev is None:
            continue
        g.add((ref, SCAN.refersTo, URIRef(f"{dev}/{oid}")))
        n += 1
    # device-only references (device-address-binding, recipients): link to the device itself
    for ref, dev_id in list(g.subject_objects(BACNET["device-identifier"])):
        if isinstance(ref, BNode) and g.value(ref, BACNET["object-identifier"]) is None:
            g.add((ref, SCAN.refersTo, URIRef(f"bacnet://{str(dev_id).split(',')[1]}")))
            n += 1
    return n


# ---------------------------------------------------------------- self-check
def validate(csv_path: Path, ttl_path: Path, topo_path: Path, dev_path: Path,
             n_devices: int, n_routers: int, fixed: bool) -> bool:
    """Re-read what was written and check it is complete and clean."""
    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        log(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
        ok = ok and cond

    log("\nSelf-check:")
    text = ttl_path.read_text(encoding="utf-8")
    try:
        g = Graph().parse(str(ttl_path), format="turtle")
        check(True, f"Turtle parses ({len(g)} triples)")
    except Exception as e:  # noqa: BLE001
        check(False, f"Turtle parses: {e}")
        return False
    reprs = text.count(" object at 0x") + text.count('"[\'') + text.count('"[<')
    check(reprs == 0, f"no Python object text in the Turtle ({reprs} found)")
    devs = set(g.subjects(RDF.type, SCAN.Router))
    check(len(devs) == n_routers, f"all {n_routers} routers in the Turtle")
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    dev_rows = [r for r in rows if r["ObjType"] == "device"]
    check(len(dev_rows) == n_devices, f"one device row per device in the CSV ({len(dev_rows)}/{n_devices})")
    contains = len(list(g.triples((None, BACNET.contains, None))))
    check(contains >= len(rows) - len(dev_rows), f"every CSV object is in the Turtle ({contains} objects, {len(rows) - len(dev_rows)} CSV object rows)")
    with open(dev_path, encoding="utf-8") as f:
        drows = list(csv.DictReader(f))
    check(len(drows) == n_devices, f"one row per device in the devices CSV ({len(drows)}/{n_devices})")
    with open(topo_path, encoding="utf-8") as f:
        topo = list(csv.DictReader(f))
    check(sum(r["kind"] == "device" for r in topo) == n_devices, "every device is in the topology CSV")
    check(len({r["router_address"] for r in topo if r["kind"] == "router"}) == n_routers, "every router is in the topology CSV")
    if fixed:
        lists = text.count("bacnet:null") + text.count("rdf:first")
        has_pa = any(r["PriorityArray"] for r in rows)
        check(lists > 0 or not has_pa, "priority arrays written as RDF lists (#181)")
    held = [r for r in rows if r["ActivePriority"]]
    in_ttl = len(list(g.triples((None, SCAN.activePriority, None))))
    check(in_ttl == len(held), f"every held priority is in the Turtle ({in_ttl}/{len(held)})")
    log("Self-check " + ("PASSED" if ok else "FAILED"))
    return ok


# ---------------------------------------------------------------- main
def build_parser() -> SimpleArgumentParser:
    p = SimpleArgumentParser()
    p.add_argument("--low", type=int, default=0, help="lowest device instance (default 0, so routers at device 0 are found)")
    p.add_argument("--high", type=int, default=MAX_INSTANCE, help=f"highest device instance (default {MAX_INSTANCE})")
    p.add_argument("--out-dir", default=".", help="output folder (default: current folder)")
    p.add_argument("--filename", default="site_scan", help="base filename (default site_scan)")
    p.add_argument("--stamp", action="store_true", help="keep this scan: add _YYYYMMDD-HHMMSS to the filenames instead of overwriting")
    p.add_argument("--discover-only", action="store_true", help="just list devices and routers, write nothing")
    p.add_argument("--console-table", action="store_true", help="print each object as it is read")
    p.add_argument("--check-fix", action="store_true", help="report whether the bacpypes3 RDF fixes are installed, then exit")
    p.add_argument("--verbose", action="store_true", help="print property read errors")
    p.add_argument("--no-validate", action="store_true", help="skip the self-check of the written files")
    return p


async def main() -> int:
    args = build_parser().parse_args()

    fixed = rdf_fix_present()
    any_fixed = anyvalue_fix_present()
    log(f"bacpypes3 {bacpypes3.__version__} from {bacpypes3.__file__}")
    log("RDF fix present (#181)" if fixed else
        "RDF fix NOT present: priority arrays become Python text and set status flags break the Turtle. See README.")
    log("RDF any-value fix present" if any_fixed else
        "RDF any-value fix not present (this script unwraps AnyAtomic itself; schedules/logs may lose values). See README.")
    if args.check_fix:
        print(f"RDF fix {'present' if fixed else 'NOT present'}; any-value fix {'present' if any_fixed else 'NOT present'}")
        return 0 if fixed else 1

    app = Application.from_args(args)
    started = datetime.now(timezone.utc)
    try:
        log("--- Who-Is-Router-To-Network ---")
        routers = []
        try:
            for _adapter, iam_rtn in await app.nse.who_is_router_to_network():
                routers.append((iam_rtn.pduSource, [int(n) for n in iam_rtn.iartnNetworkList]))
        except Exception as e:  # noqa: BLE001
            log(f"  router discovery failed: {e}")

        log(f"--- Who-Is {args.low} - {args.high} ---")
        i_ams = await app.who_is(args.low, args.high)

        log(f"\nRouters: {len(routers)}")
        for raddr, nets in routers:
            log(f"  {str(raddr):<22} routes to networks {nets}")
        log(f"Devices: {len(i_ams)}")
        for i in i_ams:
            log(f"  device {i.iAmDeviceIdentifier[1]:<9} {str(i.pduSource):<24} network {network_of(i.pduSource):<6} vendor id {i.vendorID}")
        if args.discover_only or not i_ams:
            if not i_ams:
                log("No devices answered. Is UDP 47808 free and --address on the right NIC?")
            return 0

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        base = args.filename + (f"_{datetime.now():%Y%m%d-%H%M%S}" if args.stamp else "")
        csv_path = out_dir / f"{base}.csv"
        ttl_path = out_dir / f"{base}.ttl"
        topo_path = out_dir / f"{base}_topology.csv"
        dev_path = out_dir / f"{base}_devices.csv"

        g = Graph()
        bg = BACnetGraph(g)
        g.bind("scan", SCAN)
        g.bind("prov", PROV)
        topo_rows: List[Dict[str, Any]] = []
        dev_rows: List[Dict[str, Any]] = []
        router_iris: Dict[str, URIRef] = {}

        # provenance: one node for this scan; each device says when it was read
        scan_iri = SCAN[f"scan/{started:%Y%m%dT%H%M%SZ}"]
        g.add((scan_iri, RDF.type, PROV.Activity))
        g.add((scan_iri, PROV.startedAtTime, Literal(started.isoformat(timespec="seconds"), datatype=XSD.dateTime)))
        g.add((scan_iri, SCAN.tool, Literal(f"bacnet_site_scan.py, bacpypes3 {bacpypes3.__version__}")))

        for raddr, nets in routers:
            r_iri = SCAN[f"router/{raddr}"]
            router_iris[str(raddr)] = r_iri
            g.add((r_iri, RDF.type, SCAN.Router))
            g.add((r_iri, SCAN.address, Literal(str(raddr))))
            for n in nets:
                n_iri = SCAN[f"network/{n}"]
                g.add((n_iri, RDF.type, SCAN.Network))
                g.add((n_iri, SCAN.networkNumber, Literal(n)))
                g.add((r_iri, SCAN.routesToNetwork, n_iri))
                topo_rows.append({"kind": "router", "router_address": str(raddr), "network": n})

        with open(csv_path, "w", newline="", encoding="utf-8") as fcsv:
            w = csv.DictWriter(fcsv, fieldnames=CSV_FIELDS)
            w.writeheader()
            total = 0
            for i_am in i_ams:
                addr, dev_id = i_am.pduSource, i_am.iAmDeviceIdentifier
                inst, net = dev_id[1], network_of(i_am.pduSource)
                vendor = get_vendor_info(i_am.vendorID)
                log(f"\n-> device {inst} @ {addr}")

                dev = bg.create_device(addr, dev_id)
                d_iri = dev.device_iri
                dev_proxy = dev.create_object(dev_id)

                # device facts
                facts, missing, method = await read_props(app, addr, dev_id, DEVICE_PROPS)
                log(f"    device facts: {len(facts)} read, {len(missing)} not supported ({method})")
                for prop, val in facts.items():
                    try:
                        setattr(dev_proxy, prop, plain(val))
                    except Exception as e:  # noqa: BLE001
                        if args.verbose:
                            log(f"      RDF skip device {prop}: {e}")
                name = str(facts.get("object-name", "") or "")
                desc = str(facts.get("description", "") or "")
                for prop, val in (("object-name", name), ("description", desc)):
                    if val:
                        setattr(dev, prop, val)
                g.add((d_iri, PROV.wasGeneratedBy, scan_iri))
                g.add((d_iri, SCAN.readAt, Literal(datetime.now(timezone.utc).isoformat(timespec="seconds"), datatype=XSD.dateTime)))
                for prop in missing:
                    g.add((d_iri, SCAN.propertyNotRead, Literal(f"{prop}: {missing[prop]}")))

                drow: Dict[str, Any] = {"DeviceID": inst, "Address": str(addr), "Network": net,
                                        "VendorID": int(i_am.vendorID), "ReadMethod": method,
                                        "PropsRead": len(facts), "PropsMissing": " ".join(sorted(missing))}
                for prop, col in DEVICE_COLUMN.items():
                    if prop in facts:
                        drow[col] = str(plain(facts[prop]))
                if "protocol-services-supported" in facts:
                    drow["ServicesSupported"] = fmt_bits(facts["protocol-services-supported"])
                if "protocol-object-types-supported" in facts:
                    drow["ObjectTypesSupported"] = fmt_bits(facts["protocol-object-types-supported"])
                if "device-address-binding" in facts:
                    drow["AddressBindings"] = len(facts["device-address-binding"] or [])
                dev_rows.append(drow)

                # topology: which network the device is on and which router reaches it
                g.add((d_iri, SCAN.address, Literal(str(addr))))
                g.add((d_iri, SCAN.vendorId, Literal(int(i_am.vendorID))))
                if net != "local":
                    g.add((d_iri, SCAN.onNetwork, SCAN[f"network/{net}"]))
                    for raddr, nets in routers:
                        if int(net) in nets:
                            g.add((d_iri, SCAN.reachedVia, router_iris[str(raddr)]))
                topo_rows.append({"kind": "device", "network": net, "device_id": inst,
                                  "device_address": str(addr), "vendor_id": int(i_am.vendorID), "device_name": name})

                w.writerow({"DeviceID": inst, "IP": str(addr), "Network": net, "VendorID": int(i_am.vendorID),
                            "ObjType": "device", "ObjInst": inst, "Name": name, "Description": desc})
                total += 1

                objs = await read_object_list(app, addr, dev_id)
                if args.console_table:
                    log(f"    {'Type':<20} {'Inst':<8} {'Name':<30} {'Value':<15} Command")
                for oid in objs:
                    if oid == dev_id:
                        continue  # already written as the device row
                    proxy = dev.create_object(oid)
                    row: Dict[str, Any] = {"DeviceID": inst, "IP": str(addr), "Network": net,
                                           "VendorID": int(i_am.vendorID), "ObjType": str(oid[0]), "ObjInst": oid[1]}
                    cls = vendor.get_object_class(oid[0])
                    if cls:
                        props = [p for p in OBJECT_PROPS if cls.get_property_type(PropertyIdentifier(p))]
                    else:
                        # proprietary / unknown object type: still record that it exists
                        props = ["object-name", "description"]
                        g.add((proxy._object_iri, SCAN.unknownObjectType, Literal(True)))
                    vals, errs, _m = await read_props(app, addr, oid, props)
                    if args.verbose and errs:
                        log(f"      {oid}: not read {errs}")
                    for prop, val in vals.items():
                        try:
                            setattr(proxy, prop, plain(val))
                        except Exception as e:  # noqa: BLE001
                            if args.verbose:
                                log(f"      RDF skip {oid} {prop}: {e}")

                    row["Name"] = vals.get("object-name", "")
                    row["Description"] = vals.get("description", "")
                    if "present-value" in vals:
                        row["PresentValue"] = str(plain(vals["present-value"]))
                    if "units" in vals:
                        row["Units"] = str(vals["units"])
                    flags = fmt_status_flags(vals["status-flags"]) if "status-flags" in vals else ""
                    row["StatusFlags"] = flags
                    if "reliability" in vals:
                        row["Reliability"] = str(vals["reliability"])
                    if "out-of-service" in vals:
                        row["OutOfService"] = 1 if vals["out-of-service"] else 0
                    if "event-state" in vals:
                        row["EventState"] = str(vals["event-state"])
                    has_pa = "priority-array" in vals
                    slots = priority_slots(vals.get("priority-array"))
                    if has_pa:
                        row["PriorityArray"] = fmt_priority_array(slots)
                    if "relinquish-default" in vals:
                        row["RelinquishDefault"] = str(plain(vals["relinquish-default"]))
                    if slots:
                        active = min(slots)
                        row["ActivePriority"] = active
                        g.add((proxy._object_iri, SCAN.activePriority, Literal(active)))
                        g.add((proxy._object_iri, SCAN.activePriorityName, Literal(PRIORITY_NAMES.get(active, "available"))))
                    row["Command"] = command_note(slots, flags, has_pa)

                    w.writerow(row)
                    total += 1
                    if args.console_table:
                        nm, pv = str(row.get("Name", "")), str(row.get("PresentValue", ""))
                        log(f"    {str(oid[0]):<20} {oid[1]:<8} {nm[:30]:<30} {pv[:15]:<15} {row['Command']}")

        refs = link_references(g)
        g.add((scan_iri, PROV.endedAtTime, Literal(datetime.now(timezone.utc).isoformat(timespec="seconds"), datatype=XSD.dateTime)))

        with open(ttl_path, "wb") as f:
            g.serialize(f, format="turtle")
        with open(topo_path, "w", newline="", encoding="utf-8") as f:
            tw = csv.DictWriter(f, fieldnames=TOPO_FIELDS)
            tw.writeheader()
            tw.writerows(topo_rows)
        with open(dev_path, "w", newline="", encoding="utf-8") as f:
            dw = csv.DictWriter(f, fieldnames=DEVICE_FIELDS)
            dw.writeheader()
            dw.writerows(dev_rows)

        log(f"\n{len(i_ams)} devices, {len(routers)} routers, {total} CSV rows, {len(g)} triples, {refs} reference links")
        log(f"  {csv_path}\n  {dev_path}\n  {ttl_path}\n  {topo_path}")
        if args.no_validate:
            return 0
        return 0 if validate(csv_path, ttl_path, topo_path, dev_path, len(i_ams), len(routers), fixed) else 2
    finally:
        app.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
