#!/usr/bin/env python3
"""Verify the unqualified OT edge snapshot closure. Does not boot images."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "archive" / "ot-edge" / "unqualified-cdaa4f15"
SOURCE = SNAP / "source"
TARGETS = ("bacnet-modbus", "haystack", "compatibility")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def check_checksums() -> None:
    listing = (SNAP / "CHECKSUMS.sha256").read_text().splitlines()
    if not listing:
        fail("empty checksums")
    seen = set()
    for line in listing:
        digest, rel = line.split("  ", 1)
        path = SOURCE / rel
        if not path.is_file():
            fail(f"missing {rel}")
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != digest:
            fail(f"checksum mismatch {rel}")
        seen.add(rel)
    for path in SOURCE.rglob("*"):
        if path.is_file() and path.relative_to(SOURCE).as_posix() not in seen:
            fail(f"unlisted file {path.relative_to(SOURCE)}")


def check_dockerfiles() -> None:
    for name in (
        "services/fieldbus/Dockerfile.closure",
        "services/fieldbus/Dockerfile.monorepo-context",
    ):
        text = (SOURCE / name).read_text()
        for target in TARGETS:
            if f"AS {target}" not in text:
                fail(f"{name} missing target {target}")
    mqtt = SOURCE / "services/mqtt/Dockerfile"
    if not mqtt.is_file():
        fail("mqtt Dockerfile missing")
    if "eclipse-mosquitto" not in mqtt.read_text():
        fail("mqtt base image not recorded")


def check_secrets() -> None:
    for path in SOURCE.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in {".pem", ".key"} or path.name.startswith(".env"):
            fail(f"secret-like file {path}")
    users = (SOURCE / "config/fieldbus/haystack_users.toml").read_text()
    if "password_hash" in users:
        fail("archive haystack_users.toml still has a password hash")


def check_manifest() -> None:
    manifest = json.loads((SNAP / "MANIFEST.json").read_text())
    if manifest.get("qualification") != "unqualified-snapshot":
        fail("manifest must stay unqualified until a freeze is verified")
    if manifest.get("claimed_freeze_tag") not in (None,):
        fail("do not claim a freeze tag")
    if "3.6.18" in json.dumps(manifest):
        fail("manifest must not invent a 3.6.18 freeze")
    if set(manifest.get("docker_targets") or []) != set(TARGETS):
        fail("manifest docker targets")
    missing = manifest.get("missing_evidence") or []
    if len(missing) < 4:
        fail("missing evidence list is incomplete")


def check_portal_compose() -> None:
    text = (ROOT / "docker/compose.portal.yml").read_text()
    for banned in ("openfdd-mqtt", "openfdd-fieldbus", "fieldbus:", "mqtt:", "47808"):
        if banned in text:
            fail(f"portal compose contains {banned}")
    if 'OPENFDD_MQTT_ENABLED: "0"' not in text:
        fail("portal compose must disable MQTT")
    if "OPENFDD_OT_ARCHIVE_RESTORE" in text:
        fail("portal compose must not opt into the OT restore lane")


def check_cargo() -> None:
    proc = subprocess.run(
        [
            "cargo",
            "metadata",
            "--no-deps",
            "--format-version",
            "1",
            "--manifest-path",
            str(SOURCE / "Cargo.toml"),
        ],
        cwd=SOURCE,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or "cargo metadata failed")
    names = {pkg["name"] for pkg in json.loads(proc.stdout)["packages"]}
    for required in ("openfdd-fieldbus", "openfdd_mqtt", "fdd_core", "openfdd_contracts"):
        if required not in names:
            fail(f"closure missing package {required}")
    if "openfdd-central" in names or "open_fdd_edge_prototype" in names:
        fail("closure must not vendor central or the full edge crate")


def check_semantic_boundary() -> None:
    edge = (ROOT / "edge/Cargo.toml").read_text()
    central = (ROOT / "services/central/Cargo.toml").read_text()
    if 'default = ["ot-transport"]' not in edge:
        fail("edge default feature must be ot-transport")
    if "optional = true" not in edge or "rusty-modbus-client" not in edge:
        fail("modbus client must be optional")
    if "default-features = false" not in central:
        fail("central must not enable edge ot-transport")


def main() -> None:
    check_checksums()
    check_dockerfiles()
    check_secrets()
    check_manifest()
    check_portal_compose()
    check_cargo()
    check_semantic_boundary()
    print("OK ot-edge unqualified snapshot")


if __name__ == "__main__":
    main()
