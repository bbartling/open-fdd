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
# Default central historian retain_days (historian_limits.rs); qual windows stay well inside.
DEFAULT_HISTORIAN_RETAIN_DAYS = 365
SECURITY_SEED_GRID_MINUTES = 5
SECURITY_FDD_RULE_ID = "FC1"
SECURITY_OWN_OBJECT_CHECK_IDS = frozenset(
    {
        "y.authz.a_own_package_mapping_ttl",
        "y.authz.a_own_fdd_results",
        "y.authz.a_own_fdd_series",
        "y.authz.a_own_analytics_rcx_presets",
        "y.authz.a_own_analytics_ahu_health",
        "y.authz.a_own_analytics_boiler_health",
        "y.authz.a_own_analytics_chiller_health",
        "y.authz.a_own_analytics_cooling_tower_health",
        "y.authz.a_own_analytics_hp_health",
        "y.authz.a_own_analytics_rcx_ahu",
        "y.authz.a_own_analytics_sensor_faults",
        "y.authz.a_own_analytics_sensor_health",
        "y.authz.a_own_analytics_vav_health",
        "y.authz.a_own_analytics_zone_other_health",
    }
)
SECURITY_ANALYTICS_WARM_PATHS = (
    "/api/analytics/ahu-health",
    "/api/analytics/vav-health",
    "/api/analytics/sensor-faults",
    "/api/analytics/rcx/ahu",
    "/api/analytics/chiller-health",
    "/api/analytics/cooling-tower-health",
    "/api/analytics/boiler-health",
    "/api/analytics/hp-health",
    "/api/analytics/zone-other-health",
    "/api/analytics/sensor-health",
)
STEP_STATUSES = frozenset({"PASS", "FAIL", "ERROR", "BLOCKED", "SKIPPED", "NOT_APPLICABLE"})
REQUIRED_PORTAL_SERVICES = frozenset({"central", "timescale", "nf-emulator"})
VIEWER_WRITE_CHECK_IDS = frozenset(
    f"y.authz.viewer_{action}_{scope}_denied"
    for action in ("import", "append", "purge", "delete")
    for scope in ("own", "foreign")
)
LEGACY_VIEWER_MUTATION_CHECK_ID = "y.authz.viewer_mutation_denied"


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


def _align_grid_floor(instant: dt.datetime, grid_minutes: int) -> dt.datetime:
    if instant.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    aligned = instant.replace(second=0, microsecond=0)
    minute_floor = (aligned.minute // grid_minutes) * grid_minutes
    return aligned.replace(minute=minute_floor)


def security_seed_history_window(
    rows: int,
    *,
    now: dt.datetime | None = None,
    grid_minutes: int = SECURITY_SEED_GRID_MINUTES,
) -> tuple[dt.datetime, dt.datetime]:
    """UTC span for tenant-A security seed CSV and analytics warm POST.

    Ends on the last completed grid slot before *now* so samples exist before warm
    runs. The span is far shorter than default historian retain_days so
    ``gate_analytics`` / ``clamp_start`` never advances start past end.
    """
    if rows < 1 or rows > 10_000:
        raise ValueError("rows out of bounds")
    if grid_minutes < 1:
        raise ValueError("grid_minutes out of bounds")
    anchor = now or dt.datetime.now(dt.timezone.utc)
    if anchor.tzinfo is None:
        raise ValueError("now must be timezone-aware UTC")
    end = _align_grid_floor(anchor, grid_minutes) - dt.timedelta(minutes=grid_minutes)
    start = end - dt.timedelta(minutes=grid_minutes * (rows - 1))
    retain_floor = anchor - dt.timedelta(days=DEFAULT_HISTORIAN_RETAIN_DAYS)
    if start < retain_floor:
        raise ValueError("security seed window would fall outside default retain_days")
    return start, end


def _grid_timestamps(rows: int, start: dt.datetime = PACKAGE_START) -> list[str]:
    if rows < 1 or rows > 10_000:
        raise ValueError("rows out of bounds")
    return [
        (start + dt.timedelta(minutes=SECURITY_SEED_GRID_MINUTES * i)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        for i in range(rows)
    ]


def _history_csv(
    columns: list[str],
    rows: int,
    values_for_row: Any,
    start: dt.datetime = PACKAGE_START,
) -> str:
    stamps = _grid_timestamps(rows, start)
    lines = ["timestamp_utc," + ",".join(columns)]
    for i, ts in enumerate(stamps):
        vals = values_for_row(i)
        if len(vals) != len(columns):
            raise ValueError("column/value length mismatch")
        lines.append(ts + "," + ",".join(str(v) for v in vals))
    return "\n".join(lines) + "\n"


def security_seed_equipment(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Plant-shaped equipment for tenant-A security own-object positive controls."""
    if not PREFIX_RE.fullmatch(plan["prefix"]):
        raise ValueError(f"bad qa prefix {plan['prefix']!r}")
    up = plan["prefix"].upper()
    canary = plan["tenants"]["a"]["canary_equipment"]
    return [
        {
            "equipment_id": canary,
            "equipType": "ahu",
            "points": {
                "fan-cmd": "fan_cmd",
                "fan-status": "fan_st",
                "duct-static-pressure": "da_p",
                "duct-static-pressure-sp": "da_p_sp",
                "outside-air-temp": "oat",
                "return-air-temp": "rat",
                "mixed-air-temp": "mat",
                "discharge-air-temp": "sat",
                "outdoor-air-damper-position": "oa_damper",
            },
            "values": lambda i: (
                round(55.0 + (i * 3) % 20, 1),
                1 if i % 3 else 0,
                round(0.80 + ((i * 13) % 40) / 100.0, 2),
                round(1.0 + ((i * 7) % 20) / 100.0, 2),
                round(18.0 + (i % 12) * 0.5, 1),
                round(21.0 + (i % 8) * 0.4, 1),
                round(20.0 + (i % 10) * 0.3, 1),
                round(16.0 + (i % 6) * 0.2, 1),
                round(30.0 + (i * 5) % 70, 1),
            ),
        },
        {
            "equipment_id": f"{up}_SEC_VAV",
            "equipType": "vav",
            "points": {"zone-air-temp": "zone_t", "zone-airflow": "zone_flow"},
            "values": lambda i: (round(21.0 + (i % 9) * 0.25, 2), round(200 + (i * 11) % 400, 1)),
        },
        {
            "equipment_id": f"{up}_SEC_CHW",
            "equipType": "chwPlant",
            "points": {
                "chiller-status": "ch_st",
                "compressor-status": "comp_st",
                "chw-pump-status": "pump_st",
            },
            "values": lambda i: (1 if i % 4 else 0, 1 if i % 5 else 0, 1 if i % 2 else 0),
        },
        {
            "equipment_id": f"{up}_SEC_BLR",
            "equipType": "boiler",
            "points": {"boiler-status": "blr_st", "boiler-cmd": "blr_cmd"},
            "values": lambda i: (1 if i % 6 else 0, 1 if i % 7 else 0),
        },
        {
            "equipment_id": f"{up}_SEC_HP",
            "equipType": "heatPump",
            "points": {"compressor-status": "hp_comp", "fan-status": "hp_fan"},
            "values": lambda i: (1 if i % 5 else 0, 1 if i % 3 else 0),
        },
        {
            "equipment_id": f"{up}_SEC_CT",
            "equipType": "cooling_tower",
            "points": {"fan-status": "ct_fan", "fan-cmd": "ct_cmd"},
            "values": lambda i: (1 if i % 4 else 0, round(40.0 + (i * 9) % 60, 1)),
        },
        {
            "equipment_id": f"{up}_SEC_ZN",
            "equipType": "zone_other",
            "points": {"zone-air-temp": "zone_t", "zone-airflow": "zone_flow"},
            "values": lambda i: (round(20.5 + (i % 11) * 0.2, 2), round(150 + (i * 3) % 250, 1)),
        },
    ]


def security_seed_package_zip(
    plan: dict[str, Any],
    rows: int = 96,
    *,
    now: dt.datetime | None = None,
) -> bytes:
    """Multi-equipment tenant-A package for security harness own-object controls."""
    building_id = plan["tenants"]["a"]["site"]
    seed_start, _seed_end = security_seed_history_window(rows, now=now)
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", building_id):
        raise ValueError(f"bad building_id {building_id!r}")
    manifest = {
        "schema_version": "openfdd_package_v1",
        "building_id": building_id,
        "grid_minutes": SECURITY_SEED_GRID_MINUTES,
        "timezone": "UTC",
    }
    weather_map = {
        "equipType": "weather",
        "points": {
            "web-outside-air-temp": "web_oat",
            "web-outside-air-humidity": "web_rh",
        },
    }
    weather_csv = _history_csv(
        ["web_oat", "web_rh"],
        rows,
        lambda i: (round(18.0 + (i % 24) * 0.4, 1), round(40.0 + (i % 20), 1)),
        start=seed_start,
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        entries: list[tuple[str, str]] = [
            ("manifest.json", json.dumps(manifest, sort_keys=True)),
            ("weather/history_wide.json", json.dumps(weather_map, sort_keys=True)),
            ("weather/history_wide.csv", weather_csv),
        ]
        for equip in security_seed_equipment(plan):
            eid = equip["equipment_id"]
            cols = list(equip["points"].values())
            point_map = {"equipType": equip["equipType"], "points": equip["points"]}
            csv_body = _history_csv(cols, rows, equip["values"], start=seed_start)
            entries.append((f"{eid}/history_wide.json", json.dumps(point_map, sort_keys=True)))
            entries.append((f"{eid}/history_wide.csv", csv_body))
        for name, content in entries:
            info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content)
    return buf.getvalue()


def security_fdd_run_body(plan: dict[str, Any]) -> dict[str, Any]:
    site = plan["tenants"]["a"]["site"]
    equip = plan["tenants"]["a"]["canary_equipment"]
    return {
        "mode": "registry",
        "building_id": site,
        "equipment_id": equip,
        "rule_ids": [SECURITY_FDD_RULE_ID],
        "force_new_data": True,
    }


def security_analytics_warm_body(
    plan: dict[str, Any],
    rows: int = 96,
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    start, end = security_seed_history_window(rows, now=now)
    return {
        "building_id": plan["tenants"]["a"]["site"],
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "refresh": True,
    }


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
            "fdd_rule_id": SECURITY_FDD_RULE_ID,
            "nonexistent_object": f"{plan['prefix'].upper()}_DOES_NOT_EXIST",
        },
    }


def validate_identity(
    identity: Any, expected_role: str, expected_tenant_id: str
) -> tuple[bool, str]:
    """Require the authenticated identity to have exactly the planned role and tenant."""
    if not isinstance(identity, dict):
        return False, "identity response must be an object"
    if identity.get("ok") is not True or identity.get("multi_tenant") is not True or identity.get("hub_admin") is not False:
        return False, "identity must be successful, multi-tenant and non-hub-admin"
    role = identity.get("role")
    if not isinstance(role, str) or role.lower() != expected_role.lower():
        return False, f"role mismatch (expected {expected_role})"
    tenant_ids = identity.get("tenant_ids")
    if not isinstance(tenant_ids, list) or tenant_ids != [expected_tenant_id]:
        return False, f"tenant_ids mismatch (expected exactly [{expected_tenant_id}])"
    return True, "identity role and single-tenant scope match"


def validate_viewer_write_assertions(checks: Any) -> tuple[bool, str]:
    """Require every viewer write assertion exactly once and PASS each one."""
    if not isinstance(checks, list):
        return False, "checks must be a list"
    observed: dict[str, list[Any]] = {}
    for check in checks:
        if not isinstance(check, dict):
            continue
        check_id = check.get("check_id")
        # The security producer still emits this separate agent-token denial
        # probe. It is accounted for by the security report verdict, but it is
        # not one of the eight viewer-write matrix cells validated here.
        if check_id == LEGACY_VIEWER_MUTATION_CHECK_ID:
            continue
        if isinstance(check_id, str) and check_id.startswith("y.authz.viewer_"):
            observed.setdefault(check_id, []).append(check.get("status"))

    missing = sorted(VIEWER_WRITE_CHECK_IDS - observed.keys())
    unexpected = sorted(observed.keys() - VIEWER_WRITE_CHECK_IDS)
    duplicates = sorted(check_id for check_id, statuses in observed.items() if len(statuses) != 1)
    non_pass = sorted(
        check_id for check_id, statuses in observed.items()
        if check_id in VIEWER_WRITE_CHECK_IDS and statuses != ["PASS"]
    )
    problems = []
    if missing:
        problems.append("missing: " + ", ".join(missing))
    if unexpected:
        problems.append("unexpected: " + ", ".join(unexpected))
    if duplicates:
        problems.append("duplicate: " + ", ".join(duplicates))
    if non_pass:
        problems.append("not PASS: " + ", ".join(non_pass))
    if problems:
        return False, "; ".join(problems)
    return True, f"all {len(VIEWER_WRITE_CHECK_IDS)} viewer write assertions PASS exactly once"


def validate_required_services(service_names: Any) -> tuple[bool, str]:
    """Require exactly the known service tokens in the disposable portal stack."""
    if isinstance(service_names, str):
        names = service_names.split()
    elif isinstance(service_names, (list, tuple, set, frozenset)):
        names = list(service_names)
    else:
        return False, "service names must be a string or sequence"
    if any(not isinstance(name, str) or not name for name in names):
        return False, "service names contain an invalid token"
    actual = set(names)
    duplicates = sorted(name for name in actual if names.count(name) > 1)
    missing = sorted(REQUIRED_PORTAL_SERVICES - actual)
    unexpected = sorted(actual - REQUIRED_PORTAL_SERVICES)
    if duplicates or missing or unexpected:
        problems = []
        if missing:
            problems.append("missing: " + ", ".join(missing))
        if unexpected:
            problems.append("unexpected: " + ", ".join(unexpected))
        if duplicates:
            problems.append("duplicate: " + ", ".join(duplicates))
        return False, "; ".join(problems)
    return True, "exact required service set present"


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
    failed = [
        sid for sid in required if sid in by_id and by_id[sid]["status"] not in ("PASS", "BLOCKED")
    ]
    blocked = [sid for sid in required if sid in by_id and by_id[sid]["status"] == "BLOCKED"]
    if failed or problems:
        status = "FAIL"
    elif missing or blocked or not required:
        status = "BLOCKED"
    else:
        status = "PASS"
    return {
        "suite": suite,
        "status": status,
        "pass": status == "PASS",
        "required_steps": required,
        "missing_steps": missing,
        "failed_steps": failed,
        "blocked_steps": blocked,
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


def _cmd_security_seed_package(args: argparse.Namespace) -> int:
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    args.out.write_bytes(security_seed_package_zip(plan, args.rows))
    return 0


def _cmd_security_fdd_run_body(args: argparse.Namespace) -> int:
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    print(json.dumps(security_fdd_run_body(plan), sort_keys=True))
    return 0


def _cmd_security_analytics_warm_body(args: argparse.Namespace) -> int:
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    print(json.dumps(security_analytics_warm_body(plan), sort_keys=True))
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


def _cmd_validate_identity(args: argparse.Namespace) -> int:
    try:
        identity = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid /api/auth/me JSON: {exc}", file=sys.stderr)
        return 1
    valid, detail = validate_identity(identity, args.role, args.tenant_id)
    print(detail)
    return 0 if valid else 1


def _cmd_validate_viewer_write_matrix(args: argparse.Namespace) -> int:
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read security report: {exc}", file=sys.stderr)
        return 1
    if not isinstance(report, dict):
        print("security report must be an object", file=sys.stderr)
        return 1
    valid, detail = validate_viewer_write_assertions(report.get("checks"))
    print(detail)
    return 0 if valid else 1


def _cmd_validate_services(args: argparse.Namespace) -> int:
    valid, detail = validate_required_services(args.services)
    print(detail)
    return 0 if valid else 1


def _cmd_verdict(args: argparse.Namespace) -> int:
    result = verdict(read_steps(args.steps), list(args.required), args.suite)
    result["image_tag"] = args.image_tag
    result["artifact_dir"] = str(args.steps.parent)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("suite", "status", "missing_steps", "failed_steps", "blocked_steps")}))
    return {"PASS": 0, "BLOCKED": 2}.get(result["status"], 1)


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
    p = sub.add_parser("security-seed-package")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--rows", type=int, default=96)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=_cmd_security_seed_package)
    p = sub.add_parser("security-fdd-run-body")
    p.add_argument("--plan", type=Path, required=True)
    p.set_defaults(fn=_cmd_security_fdd_run_body)
    p = sub.add_parser("security-analytics-warm-body")
    p.add_argument("--plan", type=Path, required=True)
    p.set_defaults(fn=_cmd_security_analytics_warm_body)
    p = sub.add_parser("provider-sites")
    p.add_argument("--plan", type=Path, required=True)
    p.set_defaults(fn=_cmd_provider_sites)
    p = sub.add_parser("probe-config")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=_cmd_probe_config)
    p = sub.add_parser("validate-identity")
    p.add_argument("--role", required=True)
    p.add_argument("--tenant-id", required=True)
    p.set_defaults(fn=_cmd_validate_identity)
    p = sub.add_parser("validate-viewer-write-matrix")
    p.add_argument("--report", type=Path, required=True)
    p.set_defaults(fn=_cmd_validate_viewer_write_matrix)
    p = sub.add_parser("validate-services")
    p.add_argument("services", nargs="+")
    p.set_defaults(fn=_cmd_validate_services)
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
