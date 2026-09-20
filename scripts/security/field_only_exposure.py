#!/usr/bin/env python3
"""Field-only OT exposure lint (UA-08) — no Docker required."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXPOSURE = ROOT / "scripts" / "security" / "exposure" / "field_only_ot.json"
EDGE_COMPOSE = ROOT / "docker" / "compose.edge.yml"


def lint_exposure(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    if data.get("schema_version") != "openfdd_exposure_manifest_v1":
        errs.append("bad exposure schema_version")
    if data.get("profile") != "field_only_ot":
        errs.append("exposure profile must be field_only_ot")
    if data.get("requires_local"):
        errs.append("field-only must not require local central/web/broker")
    forbids = set(data.get("forbids_local") or [])
    for name in ("central", "web", "mqtt"):
        if name not in forbids:
            errs.append(f"forbids_local must include {name}")
    services = data.get("services") or []
    mgmt_loopback = False
    mqtt_outbound = False
    for svc in services:
        name = svc.get("service")
        iface = svc.get("interface")
        for port in svc.get("ports") or []:
            p = port.get("port")
            auth = str(port.get("auth") or "")
            if name == "fieldbus" and p == 8081:
                if iface != "127.0.0.1":
                    errs.append("fieldbus management must be interface 127.0.0.1")
                else:
                    mgmt_loopback = True
                denied = [d.lower() for d in (svc.get("denied") or [])]
                if not any("management" in d for d in denied):
                    errs.append("fieldbus:8081 must deny remote management without protection")
            if name == "mqtt_client" and p == 8883:
                if "mtls" not in auth:
                    errs.append("mqtt_client:8883 auth must include mtls")
                if "outbound" not in str(iface).lower() and "wan" not in str(iface).lower():
                    errs.append("mqtt_client must be WAN/outbound interface")
                mqtt_outbound = True
    if not mgmt_loopback:
        errs.append("exposure missing loopback fieldbus:8081")
    if not mqtt_outbound:
        errs.append("exposure missing outbound mqtt_client:8883")
    return errs


def lint_edge_compose(text: str) -> list[str]:
    errs: list[str] = []
    if "fieldbus:" not in text:
        errs.append("compose.edge.yml missing fieldbus service")
    for forbidden in ("openfdd-central", "openfdd-web", "openfdd-mqtt", "caddy:"):
        if forbidden in text:
            errs.append(f"field-only compose must not include {forbidden}")
    if "network_mode: host" not in text:
        errs.append("field-only fieldbus expects host networking for BACnet/IP")
    if "OPENFDD_FIELDBUS_HTTP_HOST: 127.0.0.1" not in text and \
            'OPENFDD_FIELDBUS_HTTP_HOST: "127.0.0.1"' not in text:
        # YAML may quote or not
        if not re.search(r"OPENFDD_FIELDBUS_HTTP_HOST:\s*['\"]?127\.0\.0\.1", text):
            errs.append("fieldbus management host must default to 127.0.0.1")
    if "OPENFDD_MQTT_HOST" not in text:
        errs.append("field-only must require remote OPENFDD_MQTT_HOST")
    return errs


def run_config_lint() -> dict[str, Any]:
    exposure = json.loads(EXPOSURE.read_text(encoding="utf-8"))
    compose_text = EDGE_COMPOSE.read_text(encoding="utf-8")
    checks = [
        {"id": "exposure_field_only_ot", "ok": True, "errors": lint_exposure(exposure)},
        {"id": "compose_edge_field_only", "ok": True, "errors": lint_edge_compose(compose_text)},
    ]
    for c in checks:
        c["ok"] = not c["errors"]
    ok = all(c["ok"] for c in checks)
    return {
        "schema_version": "openfdd_field_only_exposure_v1",
        "ok": ok,
        "verdict": "PASS" if ok else "FAIL",
        "checks": checks,
        "assets": {
            "exposure": str(EXPOSURE.relative_to(ROOT)),
            "compose": str(EDGE_COMPOSE.relative_to(ROOT)),
        },
    }


def main() -> int:
    report = run_config_lint()
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
