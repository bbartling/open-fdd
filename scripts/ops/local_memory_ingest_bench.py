#!/usr/bin/env python3
"""Soft-OPEN 370 T1h/T6a — portable local memory + ingest qualification harness.

Finite, host-aware controls. Never marks PASS from empty/no_data, HTTP 200
timeout, process uptime, or health-only probes. Profiles:

  bench32-4g / bench32-8g     — 32 GB class host, sequential central caps
  mintbench-3g                — ≤3 GiB combined (required first on mintbench)
  mintbench-4g-central        — 4 GiB central only if aggregate fit; NEVER 8 GiB

Fixtures default to /home/ben/Documents/buildings100_and_50 (caller override).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

GIB = 1024**3
DEFAULT_FIXTURE_ROOT = Path("/home/ben/Documents/buildings100_and_50")
TRUSTED_WINDOW = {
    "start": "2026-07-08T00:00:00Z",
    "end": "2026-07-15T00:00:00Z",
}


@dataclass
class HostSnapshot:
    hostname: str
    mem_total_bytes: int
    mem_available_bytes: int
    cpus: int


@dataclass
class Profile:
    name: str
    central_bytes: int
    combined_bytes: int
    allow_8g_central: bool


@dataclass
class PhaseResult:
    phase: str
    status: str  # PASS | FAIL | BLOCKED | NOT_RUN
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


PROFILES = {
    "bench32-4g": Profile("bench32-4g", 4 * GIB, 6 * GIB, True),
    "bench32-8g": Profile("bench32-8g", 8 * GIB, 10 * GIB, True),
    "mintbench-3g": Profile("mintbench-3g", 2 * GIB, 3 * GIB, False),
    "mintbench-4g-central": Profile("mintbench-4g-central", 4 * GIB, 5 * GIB, False),
}


def read_host() -> HostSnapshot:
    mem_total = mem_available = 0
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            mem_total = int(line.split()[1]) * 1024
        elif line.startswith("MemAvailable:"):
            mem_available = int(line.split()[1]) * 1024
    cpus = os.cpu_count() or 1
    hostname = Path("/etc/hostname").read_text(encoding="utf-8").strip()
    return HostSnapshot(hostname, mem_total, mem_available, cpus)


def profile_fit(host: HostSnapshot, profile: Profile) -> tuple[bool, str]:
    if profile.central_bytes >= 8 * GIB and not profile.allow_8g_central:
        return False, "8 GiB central forbidden on this profile class (mintbench never 8 GiB)"
    reserve = int(0.20 * host.mem_total_bytes)
    ceiling = min(
        int(0.70 * host.mem_total_bytes),
        host.mem_available_bytes - reserve,
    )
    if ceiling <= 0:
        return False, f"no headroom after 20% reserve (available={host.mem_available_bytes})"
    if profile.combined_bytes > ceiling:
        return (
            False,
            f"combined {profile.combined_bytes} exceeds fit ceiling {ceiling}",
        )
    if profile.central_bytes > profile.combined_bytes:
        return False, "central bytes cannot exceed combined budget"
    return True, f"fit ok (ceiling={ceiling}, reserve={reserve})"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120.0,
) -> tuple[int, Any]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        raw = e.read()
        code = e.code
    except Exception as e:  # noqa: BLE001 — harness records BLOCKED/FAIL
        return 0, {"ok": False, "error": str(e)}
    try:
        return code, json.loads(raw.decode("utf-8") or "null")
    except json.JSONDecodeError:
        return code, {"ok": False, "error": "non-json", "raw": raw[:200].decode("utf-8", "replace")}


def login(base: str, user: str, password: str) -> str | None:
    code, body = http_json(
        "POST",
        f"{base.rstrip('/')}/api/auth/login",
        body=json.dumps({"username": user, "password": password}).encode(),
        content_type="application/json",
        timeout=30,
    )
    if code != 200:
        return None
    if not isinstance(body, dict):
        return None
    tok = body.get("token") or body.get("access_token")
    return tok if isinstance(tok, str) and tok else None


def phase_preflight(profile_name: str) -> PhaseResult:
    if profile_name not in PROFILES:
        return PhaseResult("preflight", "FAIL", f"unknown profile {profile_name}")
    profile = PROFILES[profile_name]
    host = read_host()
    ok, detail = profile_fit(host, profile)
    metrics = {
        "host": asdict(host),
        "profile": asdict(profile),
        "fit_detail": detail,
    }
    if not ok:
        return PhaseResult("preflight", "BLOCKED", detail, metrics)
    # Docker/cgroup check when docker available
    try:
        out = subprocess.check_output(
            ["docker", "info", "--format", "{{.CgroupVersion}}"],
            text=True,
            timeout=20,
        ).strip()
        metrics["docker_cgroup_version"] = out
        if out not in {"1", "2"}:
            return PhaseResult(
                "preflight", "BLOCKED", f"unexpected cgroup version {out!r}", metrics
            )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return PhaseResult("preflight", "BLOCKED", f"docker/cgroup unavailable: {e}", metrics)
    return PhaseResult("preflight", "PASS", detail, metrics)


def phase_fixture_hashes(root: Path) -> PhaseResult:
    needed = ["BUILDING_100_openfdd.zip", "BUILDING_50_openfdd.zip"]
    digests = {}
    missing = []
    for name in needed:
        path = root / name
        if not path.is_file():
            missing.append(name)
            continue
        digests[name] = sha256_file(path)
    if missing:
        return PhaseResult(
            "fixture_hashes",
            "BLOCKED",
            f"missing fixtures: {missing}",
            {"root": str(root)},
        )
    return PhaseResult(
        "fixture_hashes",
        "PASS",
        "fixture digests frozen",
        {"root": str(root), "sha256": digests, "trusted_window": TRUSTED_WINDOW},
    )


def phase_seed_append(base: str, token: str, fixture_root: Path) -> PhaseResult:
    """Seed BUILDING_50 then append — require nonempty ok + durable counts."""
    zip_path = fixture_root / "BUILDING_50_openfdd.zip"
    if not zip_path.is_file():
        return PhaseResult("seed_append", "BLOCKED", f"missing {zip_path}")
    raw = zip_path.read_bytes()
    code, body = http_json(
        "POST",
        f"{base.rstrip('/')}/api/csv/import/package",
        token=token,
        body=raw,
        content_type="application/zip",
        timeout=600,
    )
    if code != 200 or not isinstance(body, dict) or body.get("ok") is not True:
        return PhaseResult(
            "seed_append",
            "FAIL",
            f"seed failed code={code}",
            {"body": body if isinstance(body, dict) else str(body)[:500]},
        )
    rows = body.get("total_rows") or body.get("equipment_written")
    if not rows:
        return PhaseResult(
            "seed_append",
            "FAIL",
            "seed returned ok without positive equipment_written/total_rows (empty PASS banned)",
            {"body": body},
        )
    # Append same zip again (hourly append path may reject; treat structural ok)
    code_a, body_a = http_json(
        "POST",
        f"{base.rstrip('/')}/api/csv/import/package/append",
        token=token,
        body=raw,
        content_type="application/zip",
        timeout=600,
    )
    metrics = {
        "seed": {"code": code, "total_rows": body.get("total_rows"), "equipment_written": body.get("equipment_written")},
        "append": {"code": code_a, "body_ok": isinstance(body_a, dict) and body_a.get("ok")},
        "trusted_window": TRUSTED_WINDOW,
    }
    if code_a == 0:
        return PhaseResult("seed_append", "FAIL", "append transport error", metrics)
    # Append may be 200 ok or structured fail; empty timeout banned above
    if code_a == 200 and isinstance(body_a, dict) and body_a.get("ok") is True:
        if not (body_a.get("total_rows") or body_a.get("equipment_written") or body_a.get("merges")):
            return PhaseResult(
                "seed_append",
                "FAIL",
                "append ok without merges/rows (empty PASS banned)",
                metrics,
            )
        return PhaseResult("seed_append", "PASS", "seed+append nonempty", metrics)
    # Structured rejection with reason is FAIL for this control (log before fix)
    return PhaseResult(
        "seed_append",
        "FAIL",
        f"append not durable-ok code={code_a}",
        {**metrics, "append_body": body_a if isinstance(body_a, dict) else str(body_a)[:500]},
    )


def phase_health_honesty(base: str, token: str) -> PhaseResult:
    """Schema smoke only — never memory PASS."""
    code, body = http_json(
        "GET",
        f"{base.rstrip('/')}/api/health",
        token=token,
        timeout=30,
    )
    if code != 200 or not isinstance(body, dict):
        return PhaseResult("health_schema", "FAIL", f"health code={code}", {"body": body})
    mb = body.get("memory_budget") or {}
    required = ["hard_limit_bytes", "current_bytes", "peak_bytes", "sample_ms", "source"]
    missing = [k for k in required if mb.get(k) is None]
    if missing:
        return PhaseResult(
            "health_schema",
            "FAIL",
            f"null/missing memory_budget fields: {missing} (gate47 honesty)",
            {"memory_budget": mb},
        )
    return PhaseResult(
        "health_schema",
        "PASS",
        "memory_budget schema present (not a memory qualify)",
        {"version": body.get("version"), "memory_budget": mb},
    )


def phase_not_run(name: str, why: str) -> PhaseResult:
    return PhaseResult(name, "NOT_RUN", why)


def write_summary(out_dir: Path, phases: list[PhaseResult], meta: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "SUMMARY.json"
    payload = {
        "meta": meta,
        "phases": [asdict(p) for p in phases],
        "verdict": aggregate_verdict(phases),
        "generated_at_unix": int(time.time()),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def aggregate_verdict(phases: list[PhaseResult]) -> str:
    statuses = {p.status for p in phases}
    if "FAIL" in statuses:
        return "FAIL"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if statuses <= {"PASS", "NOT_RUN"} and "PASS" in statuses:
        return "PARTIAL" if "NOT_RUN" in statuses else "PASS"
    return "NOT_RUN"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--profile",
        required=True,
        choices=sorted(PROFILES),
        help="resource profile (mintbench never 8g central)",
    )
    ap.add_argument(
        "--fixture-root",
        type=Path,
        default=Path(os.environ.get("OPENFDD_BENCH_FIXTURE_ROOT", DEFAULT_FIXTURE_ROOT)),
    )
    ap.add_argument("--central-base", default=os.environ.get("OPENFDD_CENTRAL_BASE", ""))
    ap.add_argument("--user", default=os.environ.get("OPENFDD_BENCH_USER", "agent"))
    ap.add_argument("--password", default=os.environ.get("OPENFDD_AGENT_PASSWORD", ""))
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("reports/local_memory_bench") / time.strftime("%Y%m%dT%H%M%SZ"),
    )
    ap.add_argument(
        "--phases",
        default="preflight,fixture_hashes,health_schema,seed_append",
        help="comma list; soak/pressure/ot default NOT_RUN until explicitly listed",
    )
    args = ap.parse_args()

    phases: list[PhaseResult] = []
    wanted = {p.strip() for p in args.phases.split(",") if p.strip()}

    if "preflight" in wanted:
        phases.append(phase_preflight(args.profile))
    if "fixture_hashes" in wanted:
        phases.append(phase_fixture_hashes(args.fixture_root))

    token = None
    if any(p in wanted for p in ("health_schema", "seed_append")):
        if not args.central_base or not args.password:
            phases.append(
                PhaseResult(
                    "auth",
                    "BLOCKED",
                    "OPENFDD_CENTRAL_BASE and OPENFDD_AGENT_PASSWORD required for live phases",
                )
            )
        else:
            token = login(args.central_base, args.user, args.password)
            if not token:
                phases.append(PhaseResult("auth", "FAIL", "login failed"))
            else:
                phases.append(PhaseResult("auth", "PASS", "jwt acquired"))

    if token and "health_schema" in wanted:
        phases.append(phase_health_honesty(args.central_base, token))
    if token and "seed_append" in wanted:
        phases.append(phase_seed_append(args.central_base, token, args.fixture_root))

    for name in ("concurrent_load", "pressure", "ot_continuity", "lifecycle_churn"):
        if name in wanted:
            phases.append(phase_not_run(name, "explicit long soak not requested in this invocation"))
        else:
            phases.append(phase_not_run(name, "not selected in --phases"))

    meta = {
        "profile": args.profile,
        "fixture_root": str(args.fixture_root),
        "central_base": args.central_base or None,
        "train": "Soft-OPEN 370 T1h/T6a",
        "rules": [
            "no empty/timeout/uptime PASS",
            "mintbench never 8 GiB central",
            "log FAIL before product fix",
        ],
    }
    summary = write_summary(args.out, phases, meta)
    verdict = aggregate_verdict(phases)
    print(json.dumps({"summary": str(summary), "verdict": verdict, "phases": [asdict(p) for p in phases]}, indent=2))
    if verdict == "FAIL":
        return 2
    if verdict == "BLOCKED":
        return 3
    if verdict == "PARTIAL":
        return 0
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
