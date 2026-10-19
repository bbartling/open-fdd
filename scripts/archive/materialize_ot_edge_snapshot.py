#!/usr/bin/env python3
"""Materialize the unqualified OT edge source closure and its checksums.

The snapshot is not a verified 3.6.18 freeze. It records the OT dependency
closure present at SOURCE_COMMIT on this branch.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = "unqualified-cdaa4f15"
SOURCE_COMMIT = "cdaa4f15c662b8be242c5b0a9ebaed73fbbbc811"
DEST = ROOT / "archive" / "ot-edge" / SNAPSHOT
SOURCE = DEST / "source"

COPY_DIRS = [
    "services/fieldbus",
    "services/mqtt",
    "crates/fdd_core",
    "crates/openfdd_contracts",
    "crates/openfdd_connector_runtime",
    "crates/openfdd_mqtt",
    "config/fieldbus",
    "edge/src/drivers",
]

CLOSURE_DOCKERFILE = """# syntax=docker/dockerfile:1
# Closure Dockerfile. Build context is this snapshot's source/ directory.
# Targets match services/fieldbus/Dockerfile: bacnet-modbus, haystack, compatibility.
# The historical monorepo Dockerfile is preserved beside this file as
# Dockerfile.monorepo-context (it COPY's the full workspace, including edge and mcp).

FROM rust:1.95-bookworm AS builder
RUN apt-get update \\
  && apt-get install -y --no-install-recommends clang libclang-dev build-essential pkg-config libssl-dev \\
  && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY services ./services
COPY config ./config
RUN cargo build --release -p openfdd-fieldbus --bins

FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \\
    ca-certificates curl iproute2 libssl3 \\
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV OPENFDD_FIELDBUS_CONFIG_DIR=/app/config

FROM runtime AS bacnet-modbus
COPY config/fieldbus /app/config
COPY --from=builder /src/target/release/openfdd-bacnet-modbus /usr/local/bin/openfdd-bacnet-modbus
ENV OPENFDD_FIELDBUS_HTTP_HOST=0.0.0.0
ENV OPENFDD_FIELDBUS_HTTP_PORT=8081
EXPOSE 8081/tcp
EXPOSE 47808/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \\
  CMD curl -fsS http://127.0.0.1:8081/health || exit 1
ENTRYPOINT ["/usr/local/bin/openfdd-bacnet-modbus"]

FROM runtime AS haystack
COPY --from=builder /src/target/release/openfdd-haystack /usr/local/bin/openfdd-haystack
ENV OPENFDD_FIELDBUS_HTTP_HOST=0.0.0.0
ENV OPENFDD_FIELDBUS_HTTP_PORT=8082
EXPOSE 8082/tcp
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \\
  CMD curl -fsS http://127.0.0.1:8082/health || exit 1
ENTRYPOINT ["/usr/local/bin/openfdd-haystack"]

FROM runtime AS compatibility
COPY config/fieldbus /app/config
COPY --from=builder /src/target/release/openfdd-fieldbus /usr/local/bin/openfdd-fieldbus
ENV OPENFDD_FIELDBUS_HTTP_HOST=127.0.0.1
ENV OPENFDD_FIELDBUS_HTTP_PORT=8081
EXPOSE 8081/tcp
EXPOSE 47808/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \\
  CMD curl -fsS http://127.0.0.1:8081/health || exit 1
ENTRYPOINT ["/usr/local/bin/openfdd-fieldbus"]
"""

WORKSPACE_TOML = """[workspace]
resolver = "2"
members = [
    "crates/fdd_core",
    "crates/openfdd_contracts",
    "crates/openfdd_connector_runtime",
    "crates/openfdd_mqtt",
    "services/fieldbus",
]

[workspace.package]
edition = "2021"
license = "MIT"
repository = "https://github.com/bbartling/open-fdd"
version = "4.0.0"
rust-version = "1.80"

[workspace.dependencies]
anyhow = "1"
chrono = { version = "0.4", features = ["serde"] }
clap = { version = "4", features = ["derive"] }
csv = "1"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
thiserror = "2"
url = "2"
walkdir = "2"
"""

SAFE_HAYSTACK_USERS = """# Safe example. Generate an admin credential at restore time.
# This snapshot does not carry the in-tree lab hash.
#
# [users.admin]
# credential = "<generate-at-restore>"
# permissions = ["read"]
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def copy_tree(rel: str) -> None:
    src = ROOT / rel
    dst = SOURCE / rel
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("target", "*.pem", "*.key", ".env"),
    )


def sanitize() -> None:
    users = SOURCE / "config/fieldbus/haystack_users.toml"
    users.write_text(SAFE_HAYSTACK_USERS)
    gateway = SOURCE / "config/fieldbus/gateway.toml"
    text = gateway.read_text()
    text = text.replace('password = "changeme"', 'password = ""  # set via env at restore; do not commit a password')
    gateway.write_text(text)


def write_checksums() -> str:
    rows = []
    for path in sorted(SOURCE.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(SOURCE).as_posix()
        rows.append(f"{sha256_file(path)}  {rel}")
    body = "\n".join(rows) + "\n"
    (DEST / "CHECKSUMS.sha256").write_text(body)
    return hashlib.sha256(body.encode()).hexdigest()


def cargo_metadata() -> dict:
    proc = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1", "--manifest-path", str(SOURCE / "Cargo.toml")],
        cwd=SOURCE,
        check=True,
        capture_output=True,
        text=True,
    )
    meta = json.loads(proc.stdout)
    pkgs = sorted(pkg["name"] for pkg in meta["packages"])
    return {"packages": pkgs}


def main() -> None:
    if SOURCE.exists():
        shutil.rmtree(SOURCE)
    SOURCE.mkdir(parents=True)
    (DEST / "recipes").mkdir(exist_ok=True)
    (DEST / "evidence").mkdir(exist_ok=True)
    for rel in COPY_DIRS:
        copy_tree(rel)
    shutil.copy2(ROOT / "services/fieldbus/Dockerfile", SOURCE / "services/fieldbus/Dockerfile.monorepo-context")
    (SOURCE / "services/fieldbus/Dockerfile.closure").write_text(CLOSURE_DOCKERFILE)
    (SOURCE / "Cargo.toml").write_text(WORKSPACE_TOML)
    shutil.copy2(ROOT / "Cargo.lock", SOURCE / "Cargo.lock")
    sanitize()
    # Protocol tree is a snapshot, not a cargo member. Drop any accidental target.
    meta = cargo_metadata()
    tree_hash = write_checksums()
    manifest = {
        "schema_version": "openfdd.ot-edge-archive.v1",
        "archive_id": SNAPSHOT,
        "qualification": "unqualified-snapshot",
        "archive_date": "2026-10-19",
        "source_commit": SOURCE_COMMIT,
        "source_tree_sha256": tree_hash,
        "product_version_on_source_commit": "4.0.0",
        "claimed_freeze_tag": None,
        "components": [
            "openfdd-fieldbus",
            "openfdd-bacnet-modbus",
            "openfdd-haystack",
            "openfdd-mqtt",
        ],
        "docker_targets": ["bacnet-modbus", "haystack", "compatibility"],
        "dockerfiles": {
            "fieldbus_closure": "source/services/fieldbus/Dockerfile.closure",
            "fieldbus_closure_context": "source/",
            "fieldbus_monorepo_context": "source/services/fieldbus/Dockerfile.monorepo-context",
            "mqtt": "source/services/mqtt/Dockerfile",
            "mqtt_context": "source/services/mqtt",
        },
        "rust_image": "rust:1.95-bookworm",
        "runtime_image": "debian:bookworm-slim",
        "mqtt_base_image": "eclipse-mosquitto:2",
        "timescale_image": "unpinned — not part of this closure",
        "cargo_packages": meta["packages"],
        "protocol_tree": "source/edge/src/drivers",
        "semantic_extraction": "edge ot-transport feature; central default-features=false",
        "env_names": [
            "OPENFDD_FIELDBUS_API_KEY",
            "OPENFDD_FIELDBUS_HTTP_HOST",
            "OPENFDD_FIELDBUS_HTTP_PORT",
            "OPENFDD_FIELDBUS_CONFIG_DIR",
            "OPENFDD_MQTT_ENABLED",
            "OPENFDD_OT_ARCHIVE_RESTORE",
            "OPENFDD_MQTT_HOST",
            "OPENFDD_MQTT_PORT",
            "HAYSTACK_BASE_URL",
            "HAYSTACK_USER",
            "HAYSTACK_PASS",
            "HAYSTACK_AUTH_MODE",
            "HAYSTACK_TLS_VERIFY",
        ],
        "missing_evidence": [
            "No git tag ot-mqtt-fieldbus-last-good-* or other verified OT freeze tag was present.",
            "No per-platform OCI image digest was resolved for a qualified freeze.",
            "Isolated boot of old central/web/mqtt/fieldbus/DB was not run.",
            "Read→ingest→persist→replay was not executed.",
            "4.0 Timescale schema compatibility with archived binaries was not proven.",
            "Security support for archived images is not claimed.",
        ],
    }
    (DEST / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"materialized {DEST}")
    print("packages:", ", ".join(meta["packages"]))


if __name__ == "__main__":
    main()
