#!/usr/bin/env python3
"""Shared Open-FDD bench test utilities (API auth, checks, artifacts)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CANONICAL_OA_SQL = """SELECT
  timestamp,
  equipment_id,
  oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 THEN true
    WHEN oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:validation'"""

RULE_ID = os.environ.get("OPENFDD_FAULT_RULE_ID", "oa_temp_out_of_range")
SITE_ID = os.environ.get("OPENFDD_BENCH_SITE_ID", "site:local")
EQUIP_ID = os.environ.get("OPENFDD_BENCH_EQUIP_ID", "equip:validation")


@dataclass
class Check:
    name: str
    status: str  # PASS | FAIL | SKIP
    detail: str
    product_bug: bool = False
    artifact: str | None = None

    def line(self) -> str:
        return f"{self.status}  {self.name} — {self.detail}"


@dataclass
class RunResult:
    checks: list[Check] = field(default_factory=list)
    artifact_dir: str = ""
    started_at: str = ""
    finished_at: str = ""
    pass_count: int = 0
    fail_count: int = 0
    skip_count: int = 0
    ok: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def add(self, check: Check) -> None:
        self.checks.append(check)
        if check.status == "PASS":
            self.pass_count += 1
        elif check.status == "SKIP":
            self.skip_count += 1
        else:
            self.fail_count += 1

    def finalize(self) -> None:
        self.finished_at = utc_now()
        self.ok = self.fail_count == 0

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = out_dir / "summary.txt"
        summary.write_text(
            "\n".join(c.line() for c in self.checks)
            + f"\n\nResult: pass={self.pass_count} fail={self.fail_count} skip={self.skip_count} artifact={out_dir}\n",
            encoding="utf-8",
        )
        payload = asdict(self)
        payload["checks"] = [asdict(c) for c in self.checks]
        (out_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bench_root() -> Path:
    env = os.environ.get("OPENFDD_BENCH_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


def load_toml_simple(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    out: dict[str, Any] = {}
    section = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            out.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if val.isdigit():
            parsed: Any = int(val)
        elif val in ("true", "false"):
            parsed = val == "true"
        else:
            parsed = val
        if section:
            out[section][key] = parsed
        else:
            out[key] = parsed
    return out


def bench_config(root: Path) -> dict[str, Any]:
    profile = root / "workspace/bench/bench_profile.toml"
    cfg = load_toml_simple(profile) if profile.exists() else {}
    api = cfg.get("api", {})
    run = cfg.get("run", {})
    disc = cfg.get("discovery", {})
    return {
        "bridge": os.environ.get("OPENFDD_API_BASE", api.get("bridge", "http://127.0.0.1:8080")),
        "commission": os.environ.get("OPENFDD_COMMISSION_BASE", api.get("commission", "http://127.0.0.1:9091")),
        "poll_interval_sec": int(os.environ.get("OPENFDD_DRIVER_POLL_INTERVAL_SEC", run.get("driver_poll_interval_sec", 60))),
        "fault_rule_id": os.environ.get("OPENFDD_FAULT_RULE_ID", run.get("fault_rule_id", RULE_ID)),
        "bacnet_device": int(os.environ.get("OPENFDD_SMOKE_DEVICE_INSTANCE", "5007")),
        "modbus_host": os.environ.get("OPENFDD_MODBUS_HOST", "192.168.204.14"),
        "modbus_port": int(os.environ.get("OPENFDD_MODBUS_PORT", "1502")),
        "site_id": os.environ.get("OPENFDD_BENCH_SITE_ID", SITE_ID),
        "equip_id": os.environ.get("OPENFDD_BENCH_EQUIP_ID", EQUIP_ID),
        "expect_version": os.environ.get("OPENFDD_EXPECT_VERSION", cfg.get("expect", {}).get("version", "")),
    }


def resolve_password(root: Path, role: str = "integrator") -> tuple[str, str]:
    role_upper = role.upper()
    env_key = f"OPENFDD_{role_upper}_PASSWORD"
    if os.environ.get(env_key):
        pw = os.environ[env_key]
    else:
        handoff = root / "workspace/bootstrap_credentials.once.txt"
        pw = ""
        if handoff.exists():
            for line in handoff.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{role}:"):
                    pw = line.split(":", 1)[1].strip()
                    break
        if not pw or pw.startswith("$2b$"):
            auth = root / "workspace/auth.env.local"
            if auth.exists():
                for line in auth.read_text(encoding="utf-8").splitlines():
                    if line.startswith(f"OFDD_{role_upper}_PASSWORD="):
                        candidate = line.split("=", 1)[1].strip()
                        if candidate and not candidate.startswith("$2b$"):
                            pw = candidate
                        break
    auth = root / "workspace/auth.env.local"
    user = role
    if auth.exists():
        for line in auth.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"OFDD_{role_upper}_USER="):
                user = line.split("=", 1)[1].strip()
                break
    if not pw or pw.startswith("$2b$"):
        raise RuntimeError(f"No plaintext password for role {role}; see bootstrap_credentials.once.txt")
    return user, pw


class OpenFddClient:
    def __init__(self, base: str, token: str = "", verify_tls: bool = True) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.verify_tls = verify_tls

    @classmethod
    def login(cls, base: str, username: str, password: str, verify_tls: bool = True) -> OpenFddClient:
        body = json.dumps({"username": username, "password": password}).encode()
        req = urllib.request.Request(
            f"{base.rstrip('/')}/api/auth/login",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        ctx = None
        if base.startswith("https://") and not verify_tls:
            import ssl

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read().decode())
        token = data.get("token") or data.get("access_token")
        if not token:
            raise RuntimeError(f"login ok but no token: {data}")
        return cls(base, token, verify_tls=verify_tls)

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        url = f"{self.base}{path}"
        hdrs = {"Content-Type": "application/json"}
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        if headers:
            hdrs.update(headers)
        data = raw_body
        if body is not None:
            data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        ctx = None
        if self.base.startswith("https://") and not self.verify_tls:
            import ssl

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                raw = resp.read()
                if not raw:
                    return resp.status, {}
                try:
                    return resp.status, json.loads(raw.decode())
                except json.JSONDecodeError:
                    return resp.status, raw.decode(errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"error": raw, "http_status": exc.code}

    def get(self, path: str) -> tuple[int, Any]:
        return self._request("GET", path)

    def post(self, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        return self._request("POST", path, body=body)

    def save_json(self, path: Path, status: int, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"http_status": status, "body": data}, indent=2), encoding="utf-8")


def read_data_env(root: Path) -> dict[str, str]:
    env_file = root / "workspace/data.env.local"
    out: dict[str, str] = {}
    if not env_file.exists():
        return out
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def json_api_poll_body(root: Path) -> dict[str, str]:
    env = read_data_env(root)
    url = env.get("OPENFDD_JSON_API_TEST_URL", "https://httpbin.org/get")
    source = env.get("OPENFDD_JSON_API_TEST_SOURCE", "httpbin-health")
    return {"url": url, "source": source}


def build_agent_commissioning_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    site = cfg["site_id"]
    equip = cfg["equip_id"]
    rule_id = cfg["fault_rule_id"]
    bacnet_dev = cfg.get("bacnet_device", 5007)
    return {
        "sites": [{"site_id": site, "name": "Field bench"}],
        "equipment": [
            {
                "id": equip,
                "equipment_id": equip,
                "name": "Validation AHU",
                "site_id": site,
                "equipment_type": "ahu",
            }
        ],
        "points": [
            {
                "point_id": "point:oa-t",
                "name": "Outside Air Temp",
                "site_id": site,
                "equip_ref": equip,
                "fdd_input": "oa_t",
                "bacnet_ref": f"bacnet:{bacnet_dev}:analog-input:1173",
            },
            {
                "point_id": "point:modbus-zn-t",
                "name": "Modbus Zone Temp",
                "site_id": site,
                "equip_ref": equip,
                "fdd_input": "zn_t",
            },
        ],
        "assignments": [
            {
                "haystack_id": "point:oa-t",
                "dis": "Outside Air Temp",
                "kind": "sensor",
                "equip_ref": equip,
                "fdd_input": "oa_t",
                "unit": "°F",
                "driver_bindings": [
                    {
                        "driver": "bacnet",
                        "priority": 1,
                        "ref": f"bacnet:{bacnet_dev}:analog-input:1173",
                    }
                ],
            },
            {
                "haystack_id": "point:modbus-zn-t",
                "dis": "Modbus Zone Temp",
                "kind": "sensor",
                "equip_ref": equip,
                "fdd_input": "zn_t",
                "unit": "°F",
                "driver_bindings": [
                    {
                        "driver": "modbus",
                        "priority": 1,
                        "ref": "modbus:input_register:30001",
                    }
                ],
            },
        ],
        "fdd_rules": [
            {
                "rule_id": rule_id,
                "name": "OA Temperature Out Of Range",
                "sql": CANONICAL_OA_SQL.replace("equip:validation", equip),
                "equipment_id": equip,
                "site_id": site,
                "confirmation_seconds": 300,
                "severity": "medium",
                "output_fault_code": "OA_TEMP_OUT_OF_RANGE",
                "review_status": "approved",
            }
        ],
    }


def historian_snapshot(client: OpenFddClient) -> dict[str, Any]:
    _, data = client.get("/api/historian/validation/status")
    if isinstance(data, dict):
        return data
    return {}


def wait_for_historian_growth(
    client: OpenFddClient,
    baseline_rows: int,
    timeout_sec: int = 180,
    poll_sec: int = 15,
) -> tuple[bool, dict[str, Any]]:
    deadline = time.time() + timeout_sec
    last = historian_snapshot(client)
    while time.time() < deadline:
        time.sleep(poll_sec)
        cur = historian_snapshot(client)
        rows = int(cur.get("row_count") or 0)
        if rows > baseline_rows:
            return True, cur
        last = cur
    return False, last


def write_sql_artifact(out_dir: Path, sql: str, meta: dict[str, Any]) -> None:
    path = out_dir / "agent_fdd_sql.sql"
    path.write_text(
        f"-- Open-FDD agent bootstrap FDD SQL ({utc_now()})\n"
        f"-- rule_id={meta.get('rule_id')} site={meta.get('site_id')} equip={meta.get('equip_id')}\n\n"
        f"{sql.strip()}\n",
        encoding="utf-8",
    )


def log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def classify_product_bug(name: str, detail: str) -> bool:
    patterns = [
        r"site:import",
        r"csv_dev_model",
        r"samples=0",
        r"Too many open files",
        r"device 599999 not in device table",
        r"Haystack is disabled",
        r"configured=false",
        r"commissioning import rejected",
        r"no numeric columns",
        r"stale CSV",
        r"host crashed",
        r"sql-fdd crashed",
        r"stats\.ollama",
        r"reading 'api_ok'",
        r"sqlLanguage",
        r"external-agents",
    ]
    blob = f"{name} {detail}".lower()
    return any(re.search(p.lower(), blob) for p in patterns)
