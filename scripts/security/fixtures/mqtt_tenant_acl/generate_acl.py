#!/usr/bin/env python3
"""Generate synthetic Wave L tenant Mosquitto ACL (no live credentials)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent
TENANTS_JSON = FIXTURE_DIR / "tenants.json"
DEFAULT_ACL = FIXTURE_DIR / "acl"

HEADER = """\
# Generated Open-FDD Wave L tenant ACL fixture (synthetic).
# Source: scripts/security/fixtures/mqtt_tenant_acl/tenants.json
# Do not commit live Railway / OT credentials here.
#
# Matrix (P2c / Kali O2c folded into mqtt-key-mode-tenant-acl):
# - Edge A/B: write own tenant/building/edge tree; read own commands only.
# - Deny: foreign tenant topics, openfdd/v1/tenants/+/… for edges, cross-tenant #.
# - Central: read tenant trees it serves; write commands to owned edges only.
"""


def load_tenants(path: Path | None = None) -> dict[str, Any]:
    p = path or TENANTS_JSON
    return json.loads(p.read_text(encoding="utf-8"))


def edge_topic_prefix(tenant_id: str, building_id: str, edge_id: str) -> str:
    return (
        f"openfdd/v1/tenants/{tenant_id}/buildings/{building_id}/edges/{edge_id}"
    )


def product_edge_user(tenant_id: str, edge_id: str) -> str:
    """Production CN grammar: edge:{tenant}:{edge_id} (no building in CN)."""
    return f"edge:{tenant_id}:{edge_id}"


def render_product_acl(cfg: dict[str, Any] | None = None) -> str:
    """ACL matching TopicBuilder::edge_acl_patterns / central_acl_patterns.

    Used by the live product-image observer. Static fixture lint keeps
    ``render_acl`` (broader write grant) for historical fixture honesty.
    """
    data = cfg or load_tenants()
    lines = [
        "# Generated Open-FDD product-shaped tenant ACL (provisioner twin).",
        "# CN: edge:{tenant}:{edge_id}; writes: telemetry/metadata/discovery/status/acks only.",
        "",
    ]
    for t in data["tenants"]:
        prefix = edge_topic_prefix(t["tenant_id"], t["building_id"], t["edge_id"])
        user = product_edge_user(t["tenant_id"], t["edge_id"])
        lines.append(f"user {user}")
        lines.append(f"topic write {prefix}/telemetry/#")
        lines.append(f"topic write {prefix}/metadata/#")
        lines.append(f"topic write {prefix}/discovery/#")
        lines.append(f"topic write {prefix}/status")
        lines.append(f"topic write {prefix}/acks/#")
        lines.append(f"topic read {prefix}/commands/#")
        lines.append("")
    central = data.get("central_user") or "central:ci"
    lines.append(f"user {central}")
    for t in data["tenants"]:
        tid = t["tenant_id"]
        bid = t["building_id"]
        eid = t["edge_id"]
        tree = f"openfdd/v1/tenants/{tid}/buildings/{bid}/#"
        cmd = f"openfdd/v1/tenants/{tid}/buildings/{bid}/edges/{eid}/commands/#"
        lines.append(f"topic read {tree}")
        lines.append(f"topic write {cmd}")
    lines.append("")
    return "\n".join(lines)


def render_acl(cfg: dict[str, Any] | None = None) -> str:
    data = cfg or load_tenants()
    lines = [HEADER.rstrip(), ""]
    for t in data["tenants"]:
        prefix = edge_topic_prefix(t["tenant_id"], t["building_id"], t["edge_id"])
        lines.append(f"user {t['edge_user']}")
        lines.append(f"topic write {prefix}/#")
        lines.append(f"topic read {prefix}/commands/#")
        lines.append("")
    central = data.get("central_user") or "central:ci"
    lines.append(f"user {central}")
    for t in data["tenants"]:
        tid = t["tenant_id"]
        bid = t["building_id"]
        eid = t["edge_id"]
        tree = f"openfdd/v1/tenants/{tid}/buildings/{bid}/#"
        cmd = (
            f"openfdd/v1/tenants/{tid}/buildings/{bid}/edges/{eid}/commands/#"
        )
        lines.append(f"topic read {tree}")
        lines.append(f"topic write {cmd}")
    lines.append("")
    return "\n".join(lines)


def write_acl(out: Path | None = None, cfg: dict[str, Any] | None = None) -> Path:
    path = out or DEFAULT_ACL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_acl(cfg), encoding="utf-8")
    return path


def parse_acl_users(text: str) -> dict[str, list[tuple[str, str]]]:
    """Map username -> list of (access, topic) where access is read|write|readwrite."""
    users: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("user "):
            current = line[5:].strip()
            users.setdefault(current, [])
            continue
        if line.startswith("topic ") and current:
            rest = line[6:].strip()
            parts = rest.split(None, 1)
            if len(parts) == 2 and parts[0] in ("read", "write", "readwrite"):
                users[current].append((parts[0], parts[1]))
            elif len(parts) == 1:
                users[current].append(("readwrite", parts[0]))
    return users


def semantic_errors(text: str, cfg: dict[str, Any] | None = None) -> list[str]:
    """Return ACL content violations (empty = OK)."""
    data = cfg or load_tenants()
    users = parse_acl_users(text)
    errs: list[str] = []
    if not data.get("tenants") or len(data["tenants"]) < 2:
        return ["fixture requires at least two tenants"]

    for t in data["tenants"]:
        u = t["edge_user"]
        if u not in users:
            errs.append(f"missing user block for {u}")
            continue
        prefix = edge_topic_prefix(t["tenant_id"], t["building_id"], t["edge_id"])
        grants = users[u]
        writes = [topic for access, topic in grants if access in ("write", "readwrite")]
        reads = [topic for access, topic in grants if access in ("read", "readwrite")]
        if not any(topic.startswith(prefix) for topic in writes):
            errs.append(f"{u}: missing write grant under {prefix}")
        if not any("/commands" in topic and topic.startswith(prefix) for topic in reads):
            errs.append(f"{u}: missing read grant for own commands under {prefix}")
        for access, topic in grants:
            if "tenants/+/" in topic or topic.endswith("tenants/#") or "/tenants/#" in topic:
                errs.append(f"{u}: forbidden wildcard tenant topic {topic}")
            for other in data["tenants"]:
                if other["tenant_id"] == t["tenant_id"]:
                    continue
                foreign = f"/tenants/{other['tenant_id']}/"
                if foreign in topic:
                    errs.append(
                        f"{u}: foreign-tenant grant {access} {topic}"
                    )

    central = data.get("central_user") or "central:ci"
    if central not in users:
        errs.append(f"missing central user {central}")
    else:
        for t in data["tenants"]:
            tid = t["tenant_id"]
            needle = f"/tenants/{tid}/"
            reads = [
                topic
                for access, topic in users[central]
                if access in ("read", "readwrite") and needle in topic
            ]
            if not reads:
                errs.append(f"central missing read of tenant {tid}")

    # Cross-tenant: no edge may appear in another's write set
    for t in data["tenants"]:
        u = t["edge_user"]
        for other in data["tenants"]:
            if other["edge_user"] == u:
                continue
            foreign_prefix = edge_topic_prefix(
                other["tenant_id"], other["building_id"], other["edge_id"]
            )
            for access, topic in users.get(u, []):
                if access in ("write", "readwrite") and topic.startswith(
                    foreign_prefix
                ):
                    errs.append(f"{u}: write to foreign edge tree {topic}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_ACL,
        help="ACL output path",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="validate existing ACL (or --output) without rewriting",
    )
    args = ap.parse_args()
    if args.check:
        text = args.output.read_text(encoding="utf-8")
        errs = semantic_errors(text)
        if errs:
            for e in errs:
                print(f"FAIL: {e}")
            return 1
        print(f"PASS: ACL semantics OK ({args.output})")
        return 0
    path = write_acl(args.output)
    errs = semantic_errors(path.read_text(encoding="utf-8"))
    if errs:
        for e in errs:
            print(f"FAIL: {e}")
        return 1
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
