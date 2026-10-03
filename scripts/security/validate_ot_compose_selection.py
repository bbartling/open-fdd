#!/usr/bin/env python3
"""Astra A01/A02 — fail-closed OT Compose recipe selection checks (static).

Does not start containers or claim live OT qualification.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OT_BACNET = ROOT / "docker" / "compose.ot_local_bacnet_modbus.yml"
OT_HAYSTACK = ROOT / "docker" / "compose.ot_local_haystack.yml"
EDGE_SPLIT = ROOT / "docker" / "compose.edge.split.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_ot_bacnet(text: str) -> list[str]:
    errs: list[str] = []
    for needle in (
        "OPENFDD_MQTT_ENABLED: \"0\"",
        "bacnet-modbus:",
        "web:",
        "central:",
        "OPENFDD_LOCAL_INGEST_TOKEN",
    ):
        if needle not in text:
            errs.append(f"ot_local_bacnet_modbus missing {needle!r}")
    if re.search(r"^\s*haystack:", text, re.M):
        errs.append("ot_local_bacnet_modbus must not define haystack service")
    if "openfdd-mqtt" in text or re.search(r"^\s*mqtt:", text, re.M):
        errs.append("ot_local_bacnet_modbus must not start a broker")
    return errs


def check_ot_haystack(text: str) -> list[str]:
    errs: list[str] = []
    for needle in (
        "OPENFDD_MQTT_ENABLED: \"0\"",
        "haystack:",
        "web:",
        "central:",
        "OPENFDD_LOCAL_INGEST_TOKEN",
    ):
        if needle not in text:
            errs.append(f"ot_local_haystack missing {needle!r}")
    if re.search(r"^\s*bacnet-modbus:", text, re.M):
        errs.append("ot_local_haystack must not define bacnet-modbus service")
    if "openfdd-mqtt" in text or re.search(r"^\s*mqtt:", text, re.M):
        errs.append("ot_local_haystack must not start a broker")
    return errs


def check_edge_split(text: str) -> list[str]:
    errs: list[str] = []
    if 'profiles: ["bacnet_modbus"]' not in text:
        errs.append("edge.split bacnet-modbus must use profiles: [bacnet_modbus]")
    if 'profiles: ["haystack"]' not in text:
        errs.append("edge.split haystack must use profiles: [haystack]")
    if "OPENFDD_FIELDBUS_HTTP_HOST: 0.0.0.0" in text:
        errs.append("edge.split management must bind 127.0.0.1, not 0.0.0.0")
    if "OPENFDD_LOCAL_INGEST_TOKEN" not in text:
        errs.append("edge.split must wire local ingest token env")
    return errs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    errs: list[str] = []
    errs.extend(check_ot_bacnet(_text(OT_BACNET)))
    errs.extend(check_ot_haystack(_text(OT_HAYSTACK)))
    errs.extend(check_edge_split(_text(EDGE_SPLIT)))
    if args.selftest or not errs:
        for e in errs:
            print(f"FAIL: {e}", file=sys.stderr)
        if errs:
            return 1
        print("ok: ot compose selection contracts hold")
        return 0
    for e in errs:
        print(f"FAIL: {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
