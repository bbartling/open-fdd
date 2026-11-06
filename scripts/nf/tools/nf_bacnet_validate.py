#!/usr/bin/env python3
"""Validate NF over BACnet with bacpypes3: what is on the wire vs what NF's API says.

Run it from a PC on the BACnet LAN, never on the NF box (NF owns UDP 47808 there). Needs
`pip install bacpypes3 ifaddr` (optional dependency; --help works without it). Two checks, both
driven by NF's own config and Haystack tags, nothing hard-coded:

  1. NF's BACnet server. Device instance and local objects come from /api/v1/bacnet/configuration
     and /api/v1/bacnet/local; then Who-Is and ReadProperty over the wire: object-list must equal
     the configured objects, and object-name / units / present-value must match. Present values are
     also compared with any Haystack point whose `bacnet_object` attr names the object (for example
     av.1). Skipped (with a note) when the API refuses the config read, e.g. an API key through the
     portal, which answers 401 on /api/v1/bacnet/*.
  2. Field devices. Every trended Haystack point that has `deviceRef` and BACnet binding attrs
     (`device_id`, `object_id` such as ai.12) is read at that address; the wire value must match
     NF's latest value within --tolerance (binary points must match exactly).

Port 47808 on this PC must be free: close BACnet explorers/discovery tools and Niagara stations first,
or bind another port for unicast reads (`--address <ip>/<prefix>:47809`; Who-Is replies are broadcast
to 47808, so a non-standard port may not see I-Am).

Settings are the same as nf_portal_sensors.py (NF_LAN_URL, NF_CLIENT_ID, NF_CLIENT_SECRET, ...,
or --env FILE), plus the local BACnet/IP address bacpypes3 binds to:

  python3 scripts/nf/tools/nf_bacnet_validate.py --env ~/.secrets/nf_api.env --address 192.0.2.50/24
  python3 scripts/nf/tools/nf_bacnet_validate.py --address 192.0.2.50/24 --via portal --tolerance 0.5

Exit code 1 if anything mismatches or a device does not answer.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import nf_common as nf

try:  # optional: only the wire checks need it
    from bacpypes3.app import Application
    from bacpypes3.argparse import SimpleArgumentParser
    from bacpypes3.primitivedata import ObjectIdentifier
    HAVE_BACPYPES3 = True
except ImportError:  # pragma: no cover - exercised on machines without bacpypes3
    HAVE_BACPYPES3 = False

# NF's short object-type prefixes (attrs.object_id like "ai.1192") -> BACnet names.
OBJECT_TYPES = {
    "ai": "analog-input", "ao": "analog-output", "av": "analog-value",
    "bi": "binary-input", "bo": "binary-output", "bv": "binary-value",
    "msi": "multi-state-input", "mso": "multi-state-output", "msv": "multi-state-value",
}
# NF /bacnet/local object types -> (BACnet name, NF short prefix).
API_TYPES = {
    "OBJECT_ANALOG_VALUE": ("analog-value", "av"),
    "OBJECT_BINARY_VALUE": ("binary-value", "bv"),
    "OBJECT_MULTI_STATE_VALUE": ("multi-state-value", "msv"),
}
TIMEOUT = 8


def api_get(base: str, token: str, path: str) -> dict:
    return nf.request(f"{base}{path}", None, token)


def prop(obj: dict, name: str):
    for p in obj.get("props") or []:
        if p.get("property") == name:
            v = p.get("value") or {}
            for key in ("real", "double", "unsigned", "signed", "enumerated", "boolean", "characterString"):
                if key in v:
                    return v[key]
    return None


def as_number(value) -> float:
    """bacpypes3 Real / Enumerated / BinaryPV -> float (active=1, inactive=0)."""
    if isinstance(value, (int, float)):
        return float(value)
    return float(int(value))


class Report:
    def __init__(self) -> None:
        self.passed = self.failed = 0

    def check(self, ok: bool, label: str, detail: str) -> None:
        self.passed += bool(ok)
        self.failed += not ok
        print(f"   {'PASS' if ok else 'FAIL'}  {label:38} {detail}")


async def read(app, addr, oid: str, prop_id: str):
    return await asyncio.wait_for(app.read_property(addr, ObjectIdentifier(oid), prop_id), TIMEOUT)


async def find_device(app, instance: int):
    i_ams = await asyncio.wait_for(app.who_is(instance, instance), TIMEOUT)
    if not i_ams:
        raise SystemExit(f"no I-Am from device {instance}")
    return i_ams[0].pduSource


async def check_server(app, base: str, token: str, report: Report) -> None:
    cfg = api_get(base, token, "/api/v1/bacnet/configuration")
    local = api_get(base, token, "/api/v1/bacnet/local").get("objects") or []
    dev = int(cfg["deviceInstance"])
    addr = await find_device(app, dev)
    print(f"\n== NF BACnet server: device {dev} \"{cfg.get('deviceName')}\" I-Am from {addr}")

    name = await read(app, addr, f"device,{dev}", "object-name")
    report.check(str(name) == cfg.get("deviceName"), "device object-name",
                 f"wire {name!r} api {cfg.get('deviceName')!r}")
    served = await read(app, addr, f"device,{dev}", "object-list")
    served_ids = {f"{t},{i}" for t, i in served if str(t) not in ("device", "network-port")}

    def api_oid(obj: dict) -> tuple[str, str]:
        oid = obj["objectId"]
        name, short = API_TYPES.get(oid["objectType"], (oid["objectType"], oid["objectType"]))
        return f"{name},{oid['instance']}", f"{short}.{oid['instance']}"

    configured = {api_oid(o)[0] for o in local}
    report.check(served_ids == configured, "object-list == /bacnet/local",
                 f"{len(served_ids)} served, {len(configured)} configured"
                 + ("" if served_ids == configured
                    else f"  extra {served_ids - configured} missing {configured - served_ids}"))

    # Haystack points that say which server object they feed (bacnet_object attr, e.g. av.1).
    linked = {(p.get("attrs") or {}).get("bacnet_object"): p
              for p in nf.query(base, token, "default", nf.field("markers", "point"))
              if (p.get("attrs") or {}).get("bacnet_object")}
    for obj in local:
        oid, short = api_oid(obj)
        wire_name = await read(app, addr, oid, "object-name")
        wire_units = await read(app, addr, oid, "units")
        wire_pv = await read(app, addr, oid, "present-value")
        report.check(str(wire_name) == prop(obj, "PROP_OBJECT_NAME"), f"{oid} object-name", repr(str(wire_name)))
        report.check(int(wire_units) == prop(obj, "PROP_UNITS"), f"{oid} units", f"{wire_units} ({int(wire_units)})")
        cfg_pv = prop(obj, "PROP_PRESENT_VALUE")
        report.check(cfg_pv is not None and abs(as_number(wire_pv) - cfg_pv) < 0.01, f"{oid} present-value vs config",
                     f"wire {as_number(wire_pv):.2f} api {cfg_pv}")
        point = linked.get(short)
        if point:
            hv = nf.latest_number(point)
            dis = (point.get("attrs") or {}).get("dis") or point.get("name")
            report.check(hv is not None and abs(as_number(wire_pv) - hv) < 0.01, f"{oid} PV vs Haystack point",
                         f"wire {as_number(wire_pv):.2f} point {hv} ({dis})")


async def check_field_points(app, base: str, token: str, tolerance: float, report: Report) -> None:
    points = [p for p in nf.query(base, token, "default", nf.field("markers", "point"), nf.field("markers", "his"))
              if (p.get("attrs") or {}).get("deviceRef") and (p.get("attrs") or {}).get("object_id")
              and (p.get("attrs") or {}).get("device_id")]
    by_device: dict[str, list[dict]] = {}
    for p in points:
        by_device.setdefault(p["attrs"]["device_id"], []).append(p)
    if not by_device:
        print("\n== Field devices: no trended points with deviceRef + device_id + object_id attrs")
    for device_id, members in sorted(by_device.items()):
        try:
            addr = await find_device(app, int(device_id))
        except SystemExit as exc:
            report.check(False, f"device {device_id}", str(exc))
            continue
        ref = members[0]["attrs"]["deviceRef"]
        print(f"\n== Field device {device_id} (deviceRef {ref}) I-Am from {addr}: {len(members)} tagged points")
        for p in sorted(members, key=lambda p: p["attrs"]["object_id"]):
            a = p["attrs"]
            prefix, _, inst = a["object_id"].partition(".")
            label = f"{a['object_id']} {' '.join(m for m in nf.markers(p) if m not in nf.GENERIC_MARKERS)}"
            if prefix not in OBJECT_TYPES:
                report.check(False, label[:38], f"unknown object type prefix {prefix!r}")
                continue
            oid = f"{OBJECT_TYPES[prefix]},{inst}"
            try:
                wire = as_number(await read(app, addr, oid, "present-value"))
            except Exception as exc:  # noqa: BLE001 - report and keep going
                report.check(False, label[:38], f"read failed: {exc!r}")
                continue
            api_v = nf.latest_number(p)
            tol = 0 if a.get("kind") == "Bool" else tolerance
            ok = api_v is not None and abs(wire - api_v) <= tol + 1e-9
            latest = p.get("latestValue") or {}
            report.check(ok, label[:38], f"wire {wire:.2f} api {api_v if api_v is None else round(api_v, 2)} "
                         f"{a.get('unit', '')} @ {latest.get('ts', '')[:19]}")


def build_parser() -> argparse.ArgumentParser:
    if HAVE_BACPYPES3:
        parser = SimpleArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    else:  # enough to print --help and explain what is missing
        parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--address", help="local BACnet/IP address as <ip>/<prefix> (needs bacpypes3)")
    parser.add_argument("--via", choices=tuple(nf.PATHS), default="lan", help="API path for the reference values")
    parser.add_argument("--tolerance", type=float, default=1.0,
                        help="allowed |wire - api| for numeric field points (NF polls every period, values drift)")
    nf.add_env_arg(parser)
    return parser


async def amain(args: argparse.Namespace) -> int:
    nf.console_utf8()
    client_id, client_secret = nf.load_settings(args.env)
    base = nf.base_url(args.via)
    token = nf.bearer_token(base, client_id, client_secret)
    print(f"API reference: {args.via.upper()} {base} - bacpypes3 bound to {args.address}")

    app = Application.from_args(args)
    report = Report()
    try:
        try:
            await check_server(app, base, token, report)
        except SystemExit as exc:
            # Through the portal, API-key tokens get 401 on /api/v1/bacnet/* (point APIs pass); LAN works.
            print(f"\n== NF BACnet server: SKIPPED, {exc}\n"
                  f"   (a 401 means API keys can't read /api/v1/bacnet/* through the portal: use --via lan.)")
        await check_field_points(app, base, token, args.tolerance, report)
    finally:
        app.close()
    print(f"\n== {report.passed} passed, {report.failed} failed")
    return 0 if report.failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not HAVE_BACPYPES3:
        print("this tool needs bacpypes3 on a PC on the BACnet LAN: pip install bacpypes3 ifaddr", file=sys.stderr)
        return 2
    if not args.address:
        print("--address <ip>/<prefix> is required (the BACnet/IP address of this PC)", file=sys.stderr)
        return 2
    try:
        return asyncio.run(amain(args))
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
