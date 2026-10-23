#!/usr/bin/env python3
"""Pure helpers for the disposable portal qualification recipe.

The shell recipes own Docker. This module owns everything that can be tested
without Docker: run identifiers, the tenant/user plan, synthetic package
archives, the NF emulator provider config, the security harness config, and
the final verdict. It never prints secrets except through ``secret``, whose
stdout the caller captures into a variable.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import secrets
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
NF_FIXTURE = ROOT / "scripts" / "qualification" / "fixtures" / "nf_emulator" / "points.json"
NF_EMULATOR_ORIGIN = "http://127.0.0.1:18089"
PREFIX_RE = re.compile(r"^qa[0-9]{8}[a-z0-9]{4}$")
PROJECT_RE = re.compile(r"^openfdd-qual-[a-z0-9-]{4,48}$")
MIN_SECRET_CHARS = 32
JWT_SECRET_BYTES = 48
PACKAGE_START = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
STEP_STATUSES = frozenset({"PASS", "FAIL", "ERROR", "BLOCKED", "SKIPPED", "NOT_APPLICABLE"})


def new_secret(nbytes: int = JWT_SECRET_BYTES) -> str:
    if nbytes < 24:
        raise ValueError("secrets need at least 24 random bytes")
    value = secrets.token_urlsafe(nbytes)
    if len(value) < MIN_SECRET_CHARS:
        raise ValueError("generated secret too short")
    return value


def new_prefix(today: dt.date | None = None, suffix: str | None = None) -> str:
    day = (today or dt.datetime.now(dt.timezone.utc).date()).strftime("%Y%m%d")
    tail = suffix if suffix is not None else secrets.token_hex(2)
    prefix = f"qa{day}{tail}"
    if not PREFIX_RE.fullmatch(prefix):
        raise ValueError(f"bad qa prefix {prefix!r}")
    return prefix


def project_name(kind: str, prefix: str) -> str:
    name = f"openfdd-qual-{kind}-{prefix}"
    if not PROJECT_RE.fullmatch(name):
        raise ValueError(f"bad compose project name {name!r}")
    return name


def build_plan(prefix: str) -> dict[str, Any]:
    """Deterministic two-tenant fixture plan for one run prefix."""
    if not PREFIX_RE.fullmatch(prefix):
        raise ValueError(f"bad qa prefix {prefix!r}")
    up = prefix.upper()
    tenants = {}
    users = []
    for side in ("a", "b"):
        tenant_id = f"{prefix}_tenant_{side}"
        site = f"{up}_SITE_{side.upper()}"
        buildings = [site]
        if side == "a":
            buildings.append(f"{up}_NF_A")
        tenants[side] = {
            "id": tenant_id,
            "name": f"QA {prefix} tenant {side.upper()}",
            "building_ids": buildings,
            "site": site,
            "canary_equipment": f"AHU_{up}_{side.upper()}",
        }
        for role in ("operator", "viewer"):
            users.append(
                {
                    "alias": f"{role}_{side}",
                    "username": f"{prefix}-{side}-{role}",
                    "role": role,
                    "tenant_ids": [tenant_id],
                    "password_env": f"QA_{role.upper()}_{side.upper()}_PASSWORD",
                    "username_env": f"QA_{role.upper()}_{side.upper()}_USER",
                }
            )
    return {
        "schema": "openfdd_portal_qual_plan_v1",
        "prefix": prefix,
        "tenants": tenants,
        "users": users,
        "admin": {
            "alias": "admin",
            "username": "admin",
            "role": "admin",
            "username_env": "QA_ADMIN_USER",
            "password_env": "QA_ADMIN_PASSWORD",
            "note": "Hub admin is env-only; file users cannot be admin.",
        },
        "tenant_admin_probe": {
            "username": f"{prefix}-a-admin",
            "role": "admin",
            "tenant_ids": [tenants["a"]["id"]],
            "expected_status": 400,
        },
        "nf": {
            "building_id": f"{up}_NF_A",
            "tenant_id": tenants["a"]["id"],
            "origin": NF_EMULATOR_ORIGIN,
        },
    }


def package_rows(rows: int, start: dt.datetime = PACKAGE_START) -> list[tuple[str, float, float, float]]:
    if rows < 1 or rows > 10_000:
        raise ValueError("rows out of bounds")
    out = []
    for i in range(rows):
        ts = start + dt.timedelta(minutes=5 * i)
        fan = round(40.0 + (i * 7) % 50, 1)
        static = round(0.80 + ((i * 13) % 40) / 100.0, 2)
        out.append((ts.strftime("%Y-%m-%dT%H:%M:%SZ"), fan, static, 1.0))
    return out


def package_zip(building_id: str, equipment_id: str, rows: int = 48) -> bytes:
    """Synthetic AHU package in the shape the central import tests use."""
    for label, value in (("building_id", building_id), ("equipment_id", equipment_id)):
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", value):
            raise ValueError(f"bad {label} {value!r}")
    manifest = {
        "schema_version": "openfdd_package_v1",
        "building_id": building_id,
        "grid_minutes": 5,
        "timezone": "UTC",
    }
    point_map = {
        "equipType": "ahu",
        "points": {
            "fan-cmd": "SF_SPD",
            "duct-static-pressure": "DA_P",
            "duct-static-pressure-sp": "DA_P_SP",
        },
    }
    csv_lines = ["timestamp_utc,SF_SPD,DA_P,DA_P_SP"]
    csv_lines.extend(f"{ts},{fan},{static},{sp}" for ts, fan, static, sp in package_rows(rows))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in (
            ("manifest.json", json.dumps(manifest, sort_keys=True)),
            (f"{equipment_id}/history_wide.json", json.dumps(point_map, sort_keys=True)),
            (f"{equipment_id}/history_wide.csv", "\n".join(csv_lines) + "\n"),
        ):
            info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content)
    return buf.getvalue()


def provider_sites(plan: dict[str, Any], fixture_path: Path = NF_FIXTURE) -> list[dict[str, Any]]:
    """NF site config that can only reach the loopback emulator."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    nf = plan["nf"]
    return [
        {
            "building_id": nf["building_id"],
            "tenant_id": nf["tenant_id"],
            "provider_instance_id": f"nf-{plan['prefix']}-emulator",
            "provider": "nf",
            "endpoint": nf["origin"],
            "auth_mode": "anonymous",
            "allow_insecure_http": True,
            "network_scope": "private",
            "poll_secs": 15,
            "point_map": [
                {
                    "provider_point_id": point["uuid"],
                    "equipment_id": "AHU_NF_1" if i else "WEATHER_NF_1",
                    "role": role,
                    "equip_type": "ahu" if i else "weather",
                }
                for i, (point, role) in enumerate(
                    zip(
                        fixture["points"],
                        ("outside-air-temp", "fan-cmd", "duct-static-pressure"),
                    )
                )
            ],
        }
    ]


def assert_emulator_only(sites: list[dict[str, Any]]) -> None:
    for site in sites:
        if site.get("endpoint") != NF_EMULATOR_ORIGIN:
            raise ValueError("provider endpoint is not the loopback NF emulator")
        if any(site.get(k) for k in ("client_id", "client_secret")):
            raise ValueError("qualification provider config must not carry credentials")


def probe_config(plan: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Security harness fixtures config: env-var references only."""
    identities: dict[str, Any] = {
        "admin": {
            "username_env": plan["admin"]["username_env"],
            "password_env": plan["admin"]["password_env"],
            "role": "admin",
            "tenant_ids": [],
        }
    }
    for user in plan["users"]:
        identities[user["alias"]] = {
            "username_env": user["username_env"],
            "password_env": user["password_env"],
            "role": user["role"],
            "tenant_ids": list(user["tenant_ids"]),
        }
    a, b = plan["tenants"]["a"], plan["tenants"]["b"]
    return {
        "schema_version": "openfdd_security_fixtures_v1",
        "notes": [
            f"Generated for disposable portal qualification run {plan['prefix']}.",
            "Credentials are environment-variable references only.",
        ],
        "origin_allowlist": [base_url],
        "tls": {"verify": True, "allow_http_loopback": True, "max_body_bytes": 1048576},
        "identities": identities,
        "fixtures": {
            "tenant_a": a["id"],
            "tenant_b": b["id"],
            "building_a": a["site"],
            "building_b": b["site"],
            "equipment_a": a["canary_equipment"],
            "equipment_b": b["canary_equipment"],
            "canary_a": a["canary_equipment"],
            "canary_b": b["canary_equipment"],
            "nonexistent_object": f"{plan['prefix'].upper()}_DOES_NOT_EXIST",
        },
    }


def read_steps(path: Path) -> list[dict[str, Any]]:
    steps = []
    if not path.is_file():
        return steps
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            steps.append(json.loads(line))
    return steps


def verdict(steps: list[dict[str, Any]], required: list[str], suite: str) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for step in steps:
        sid = step.get("id")
        status = step.get("status")
        if not isinstance(sid, str) or status not in STEP_STATUSES:
            problems.append(f"malformed step {step!r}")
            continue
        if sid in by_id:
            problems.append(f"duplicate step {sid}")
        by_id[sid] = step
    missing = [sid for sid in required if sid not in by_id]
    failed = [sid for sid in required if sid in by_id and by_id[sid]["status"] != "PASS"]
    if problems or missing or failed or not required:
        status = "FAIL" if failed or problems else "BLOCKED"
    else:
        status = "PASS"
    return {
        "suite": suite,
        "status": status,
        "pass": status == "PASS",
        "required_steps": required,
        "missing_steps": missing,
        "failed_steps": failed,
        "problems": problems,
        "steps": [by_id[k] for k in sorted(by_id)],
    }


def _cmd_secret(args: argparse.Namespace) -> int:
    sys.stdout.write(new_secret(args.bytes))
    return 0


def _cmd_prefix(_: argparse.Namespace) -> int:
    print(new_prefix())
    return 0


def _cmd_project(args: argparse.Namespace) -> int:
    print(project_name(args.kind, args.prefix))
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    print(json.dumps(build_plan(args.prefix), indent=2, sort_keys=True))
    return 0


def _cmd_package(args: argparse.Namespace) -> int:
    args.out.write_bytes(package_zip(args.building, args.equipment, args.rows))
    return 0


def _cmd_provider_sites(args: argparse.Namespace) -> int:
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    sites = provider_sites(plan)
    assert_emulator_only(sites)
    sys.stdout.write(json.dumps(sites, separators=(",", ":"), sort_keys=True))
    return 0


def _cmd_probe_config(args: argparse.Namespace) -> int:
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    args.out.write_text(json.dumps(probe_config(plan, args.base_url), indent=2) + "\n", encoding="utf-8")
    return 0


def _cmd_verdict(args: argparse.Namespace) -> int:
    result = verdict(read_steps(args.steps), list(args.required), args.suite)
    result["image_tag"] = args.image_tag
    result["artifact_dir"] = str(args.steps.parent)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("suite", "status", "missing_steps", "failed_steps")}))
    return 0 if result["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("secret")
    p.add_argument("--bytes", type=int, default=48)
    p.set_defaults(fn=_cmd_secret)
    sub.add_parser("prefix").set_defaults(fn=_cmd_prefix)
    p = sub.add_parser("project")
    p.add_argument("--kind", required=True)
    p.add_argument("--prefix", required=True)
    p.set_defaults(fn=_cmd_project)
    p = sub.add_parser("plan")
    p.add_argument("--prefix", required=True)
    p.set_defaults(fn=_cmd_plan)
    p = sub.add_parser("package")
    p.add_argument("--building", required=True)
    p.add_argument("--equipment", required=True)
    p.add_argument("--rows", type=int, default=48)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=_cmd_package)
    p = sub.add_parser("provider-sites")
    p.add_argument("--plan", type=Path, required=True)
    p.set_defaults(fn=_cmd_provider_sites)
    p = sub.add_parser("probe-config")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=_cmd_probe_config)
    p = sub.add_parser("verdict")
    p.add_argument("--steps", type=Path, required=True)
    p.add_argument("--suite", required=True)
    p.add_argument("--image-tag", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--required", nargs="+", required=True)
    p.set_defaults(fn=_cmd_verdict)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
