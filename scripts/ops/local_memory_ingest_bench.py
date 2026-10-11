#!/usr/bin/env python3
"""Soft-OPEN 370/371 T1h/T6a — portable local memory + ingest qualification harness.

Finite, host-aware controls. Never marks PASS from empty/no_data, HTTP 200
timeout, process uptime, or health-only probes. Soft-OPEN 371 T0b: strict typed
counts, incomplete-status rejection, ZIP content validation, durable readback,
unknown/explicit-stub phase FAIL, and CONTROL_ONLY vs FULL qualification exits.

Profiles:

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
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

GIB = 1024**3
DEFAULT_FIXTURE_ROOT = Path("/home/ben/Documents/buildings100_and_50")
TRUSTED_WINDOW = {
    "start": "2026-07-08T00:00:00Z",
    "end": "2026-07-15T00:00:00Z",
}

SMOKE_PHASES = frozenset(
    {"preflight", "fixture_hashes", "auth", "health_schema", "seed_append"}
)
LONG_PHASES = frozenset(
    {"concurrent_load", "pressure", "ot_continuity", "lifecycle_churn"}
)
KNOWN_PHASES = SMOKE_PHASES | LONG_PHASES
INCOMPLETE_TOKENS = frozenset(
    {
        "partial",
        "cancelled",
        "canceled",
        "timed_out",
        "timeout",
        "fail_closed",
        "failed",
        "error",
    }
)


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


def positive_int_count(value: Any, *, allow_zero: bool = False) -> int | None:
    """Strict nonnegative integer count. bool and numeric strings are never counts."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        if value < 0:
            return None
        if value == 0 and not allow_zero:
            return None
        return value
    return None


def response_incomplete(body: dict[str, Any]) -> str | None:
    status = body.get("status")
    if isinstance(status, str) and status.strip().lower() in INCOMPLETE_TOKENS:
        return f"status={status}"
    for flag in ("timed_out", "cancelled", "canceled", "fail_closed"):
        if body.get(flag) is True:
            return flag
    return None


def merges_positive_rows(merges: Any) -> int | None:
    if not isinstance(merges, list) or not merges:
        return None
    total = 0
    for item in merges:
        if not isinstance(item, dict):
            return None
        why = response_incomplete(item)
        if why is not None:
            return None
        rows = positive_int_count(item.get("rows_written"))
        if rows is None:
            return None
        total += rows
    return total if total > 0 else None


def durable_count_from_body(body: dict[str, Any]) -> tuple[int | None, str]:
    """Prefer total_rows, else equipment_written, else merges rows_written sum."""
    why = response_incomplete(body)
    if why is not None:
        return None, why
    for key in ("total_rows", "equipment_written"):
        n = positive_int_count(body.get(key))
        if n is not None:
            return n, key
    merge_rows = merges_positive_rows(body.get("merges"))
    if merge_rows is not None:
        return merge_rows, "merges.rows_written"
    return None, "no positive typed count"


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
    # Shared 32 GiB bench: enforce min(40% total, 50% available) for all services.
    if profile.name.startswith("bench32"):
        shared = min(
            int(0.40 * host.mem_total_bytes),
            int(0.50 * host.mem_available_bytes),
        )
        ceiling = min(ceiling, shared)
    if ceiling <= 0:
        return False, f"no headroom after reserve (available={host.mem_available_bytes})"
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
    digests: dict[str, str] = {}
    missing: list[str] = []
    for name in needed:
        path = root / name
        if not path.is_file():
            missing.append(name)
            continue
        digests[name] = sha256_file(path)
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile:
            return PhaseResult(
                "fixture_hashes",
                "FAIL",
                f"{name} is not a valid zip package",
                {"root": str(root), "sha256": digests},
            )
        if not any(n.endswith("history_wide.csv") for n in names):
            return PhaseResult(
                "fixture_hashes",
                "FAIL",
                f"{name} zip missing history_wide.csv member",
                {"root": str(root), "sha256": digests, "members": names[:20]},
            )
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
        "fixture digests frozen + zip contents validated",
        {"root": str(root), "sha256": digests, "trusted_window": TRUSTED_WINDOW},
    )


def _hourly_append_chunk_from_zip(zip_path: Path) -> tuple[str, str, str]:
    """Build one new hourly CSV row from fixture zip (harness-only; not product).

    Returns (building_id, equipment_id, csv_text). Prefers typed AHU history.
    """
    from datetime import datetime, timedelta, timezone

    with zipfile.ZipFile(zip_path) as zf:
        candidates = [
            n
            for n in zf.namelist()
            if n.endswith("/history_wide.csv") and "/AHU_" in n
        ]
        if not candidates:
            candidates = [n for n in zf.namelist() if n.endswith("/history_wide.csv")]
        if not candidates:
            raise FileNotFoundError("no history_wide.csv in package zip")
        candidates.sort(key=lambda n: (n.count("/"), n))
        hist_name = candidates[0]
        parts = Path(hist_name).parts
        building_id = parts[0]
        equipment_id = parts[-2]
        lines = zf.read(hist_name).decode("utf-8", errors="replace").splitlines()
    if len(lines) < 2:
        raise ValueError(f"{hist_name} has no data rows")
    header = lines[0]
    last = lines[-1]
    cols = last.split(",")
    ts_raw = cols[0].strip()
    ts = None
    for fmt in (
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S+00:00",
    ):
        try:
            fixed = ts_raw.replace("+00:00", "+0000") if fmt.endswith("%z") else ts_raw
            ts = datetime.strptime(fixed, fmt)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    if ts is None:
        ts = datetime(2026, 7, 17, 11, 0, tzinfo=timezone.utc)
    new_ts = (ts + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S+00:00")
    cols[0] = new_ts
    csv_text = header + "\n" + ",".join(cols) + "\n"
    return building_id, equipment_id, csv_text


def _buildings_contain(body: Any, building_id: str) -> bool:
    if not isinstance(body, dict):
        return False
    buildings = body.get("buildings")
    if isinstance(buildings, list):
        for item in buildings:
            if item == building_id:
                return True
            if isinstance(item, dict) and item.get("building_id") == building_id:
                return True
            if isinstance(item, dict) and item.get("id") == building_id:
                return True
    return False


def _equipment_contain(body: Any, equipment_id: str) -> bool:
    if not isinstance(body, dict):
        return False
    for key in ("equipment", "items", "rows"):
        rows = body.get(key)
        if isinstance(rows, list):
            for item in rows:
                if item == equipment_id:
                    return True
                if isinstance(item, dict):
                    if item.get("equipment_id") == equipment_id:
                        return True
                    if item.get("id") == equipment_id:
                        return True
    return False


def independent_durable_readback(
    base: str, token: str, building_id: str, equipment_id: str
) -> tuple[bool, dict[str, Any]]:
    """Prove seed+append via GET surfaces — not the import response counters."""
    metrics: dict[str, Any] = {
        "building_id": building_id,
        "equipment_id": equipment_id,
        "calls": [],
    }
    code_b, body_b = http_json(
        "GET",
        f"{base.rstrip('/')}/api/csv/import/package/buildings",
        token=token,
        timeout=60,
    )
    metrics["calls"].append(
        {
            "path": "/api/csv/import/package/buildings",
            "code": code_b,
            "ok": isinstance(body_b, dict) and body_b.get("ok") is not False,
        }
    )
    if code_b != 200 or not _buildings_contain(body_b, building_id):
        metrics["fail"] = "building absent from package/buildings readback"
        return False, metrics

    q = urllib.parse.urlencode({"building_id": building_id})
    code_e, body_e = http_json(
        "GET",
        f"{base.rstrip('/')}/api/fdd/equipment?{q}",
        token=token,
        timeout=60,
    )
    metrics["calls"].append(
        {
            "path": f"/api/fdd/equipment?building_id={building_id}",
            "code": code_e,
            "ok": isinstance(body_e, dict),
        }
    )
    if code_e != 200 or not _equipment_contain(body_e, equipment_id):
        metrics["fail"] = "equipment absent from fdd/equipment readback"
        return False, metrics
    return True, metrics


def phase_seed_append(base: str, token: str, fixture_root: Path) -> PhaseResult:
    """Seed BUILDING_50 then JSON hourly append — typed counts + durable readback."""
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
    seed_n, seed_src = durable_count_from_body(body)
    if seed_n is None:
        return PhaseResult(
            "seed_append",
            "FAIL",
            f"seed returned ok without positive typed count ({seed_src})",
            {"body": body},
        )
    try:
        building_id, equipment_id, csv_chunk = _hourly_append_chunk_from_zip(zip_path)
    except Exception as exc:  # noqa: BLE001 — harness surface
        return PhaseResult(
            "seed_append",
            "FAIL",
            f"append chunk build failed: {exc}",
            {"seed": {"code": code, "total_rows": body.get("total_rows")}},
        )
    append_payload = {
        "confirm": True,
        "building_id": body.get("building_id") or building_id,
        "equipment_id": equipment_id,
        "csv": csv_chunk,
    }
    code_a, body_a = http_json(
        "POST",
        f"{base.rstrip('/')}/api/csv/import/package/append",
        token=token,
        body=json.dumps(append_payload).encode(),
        content_type="application/json",
        timeout=600,
    )
    metrics: dict[str, Any] = {
        "seed": {
            "code": code,
            "total_rows": body.get("total_rows"),
            "equipment_written": body.get("equipment_written"),
            "count_source": seed_src,
            "count": seed_n,
            "building_id": body.get("building_id") or building_id,
        },
        "append": {
            "code": code_a,
            "body_ok": isinstance(body_a, dict) and body_a.get("ok"),
            "equipment_id": equipment_id,
        },
        "trusted_window": TRUSTED_WINDOW,
        "qualification_scope": "CONTROL_ONLY",
    }
    if code_a == 0:
        return PhaseResult("seed_append", "FAIL", "append transport error", metrics)
    if not (code_a == 200 and isinstance(body_a, dict) and body_a.get("ok") is True):
        return PhaseResult(
            "seed_append",
            "FAIL",
            f"append not durable-ok code={code_a}",
            {**metrics, "append_body": body_a if isinstance(body_a, dict) else str(body_a)[:500]},
        )
    append_n, append_src = durable_count_from_body(body_a)
    metrics["append"]["count_source"] = append_src
    metrics["append"]["count"] = append_n
    metrics["append"]["total_rows"] = body_a.get("total_rows")
    metrics["append"]["equipment_written"] = body_a.get("equipment_written")
    metrics["append"]["merges"] = body_a.get("merges")
    if append_n is None:
        return PhaseResult(
            "seed_append",
            "FAIL",
            f"append ok without positive typed durable count ({append_src})",
            metrics,
        )

    bid = str(body.get("building_id") or building_id)
    ok_rb, rb_metrics = independent_durable_readback(base, token, bid, equipment_id)
    metrics["durable_readback"] = rb_metrics
    if not ok_rb:
        return PhaseResult(
            "seed_append",
            "FAIL",
            f"independent durable readback failed: {rb_metrics.get('fail')}",
            metrics,
        )
    return PhaseResult(
        "seed_append",
        "PASS",
        "seed+append typed counts + durable readback (CONTROL_ONLY)",
        metrics,
    )


def phase_health_honesty(
    base: str,
    token: str,
    *,
    expected_version_substr: str | None = None,
) -> PhaseResult:
    """Typed memory_budget schema smoke — never memory PASS."""
    code, body = http_json(
        "GET",
        f"{base.rstrip('/')}/api/health",
        token=token,
        timeout=30,
    )
    if code != 200 or not isinstance(body, dict):
        return PhaseResult("health_schema", "FAIL", f"health code={code}", {"body": body})
    version = body.get("version")
    if not isinstance(version, str) or not version.strip():
        return PhaseResult(
            "health_schema",
            "FAIL",
            "health version missing/non-string",
            {"version": version},
        )
    if expected_version_substr and expected_version_substr not in version:
        return PhaseResult(
            "health_schema",
            "FAIL",
            f"health version {version!r} missing expected {expected_version_substr!r}",
            {"version": version},
        )
    mb = body.get("memory_budget")
    if not isinstance(mb, dict):
        return PhaseResult(
            "health_schema",
            "FAIL",
            "memory_budget missing/non-object",
            {"memory_budget": mb},
        )
    required_int = ["hard_limit_bytes", "current_bytes", "peak_bytes", "sample_ms"]
    bad: list[str] = []
    for key in required_int:
        n = positive_int_count(mb.get(key), allow_zero=(key != "hard_limit_bytes"))
        if n is None:
            bad.append(key)
    source = mb.get("source")
    if not isinstance(source, str) or not source.strip():
        bad.append("source")
    if bad:
        return PhaseResult(
            "health_schema",
            "FAIL",
            f"invalid typed memory_budget fields: {bad}",
            {"memory_budget": mb},
        )
    hard = mb["hard_limit_bytes"]
    current = mb["current_bytes"]
    peak = mb["peak_bytes"]
    sample_ms = mb["sample_ms"]
    if not isinstance(hard, int) or hard <= 0:
        return PhaseResult(
            "health_schema", "FAIL", "hard_limit_bytes must be positive int", {"memory_budget": mb}
        )
    if current > hard:
        return PhaseResult(
            "health_schema",
            "FAIL",
            "current_bytes exceeds hard_limit_bytes",
            {"memory_budget": mb},
        )
    if peak < current:
        return PhaseResult(
            "health_schema",
            "FAIL",
            "peak_bytes below current_bytes",
            {"memory_budget": mb},
        )
    if sample_ms <= 0:
        return PhaseResult(
            "health_schema", "FAIL", "sample_ms must be positive", {"memory_budget": mb}
        )
    return PhaseResult(
        "health_schema",
        "PASS",
        "memory_budget typed schema present (not a memory qualify)",
        {"version": version, "memory_budget": mb},
    )


def phase_not_run(name: str, why: str) -> PhaseResult:
    return PhaseResult(name, "NOT_RUN", why)


def phase_unimplemented(name: str) -> PhaseResult:
    """Explicitly selected long phase that is still a stub — fails qualification."""
    return PhaseResult(
        name,
        "FAIL",
        "phase explicitly selected but unimplemented (Soft-OPEN 371 T0b; not a smoke NOT_RUN)",
        {"explicit": True, "implemented": False},
    )


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
    if not phases:
        return "FAIL"
    statuses = {p.status for p in phases}
    if "FAIL" in statuses:
        return "FAIL"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    selected_long = [p for p in phases if p.phase in LONG_PHASES and "not selected" not in p.detail]
    # Explicit long phases that remain NOT_RUN are incomplete (should be FAIL via stub).
    if any(p.status == "NOT_RUN" and p.phase in LONG_PHASES and "not selected" not in p.detail for p in phases):
        return "FAIL"
    if statuses <= {"PASS", "NOT_RUN"} and "PASS" in statuses:
        if any(p.status == "NOT_RUN" for p in phases) or selected_long:
            # Smoke-only: long phases not selected → CONTROL_ONLY, not FULL PASS.
            if all(
                p.status == "NOT_RUN" and "not selected" in p.detail
                for p in phases
                if p.phase in LONG_PHASES
            ):
                return "CONTROL_ONLY"
            return "PARTIAL"
        return "PASS"
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
        "--expected-version-substr",
        default=os.environ.get("OPENFDD_T6A_EXPECTED_VERSION", ""),
        help="optional health version substring (e.g. 3.5.71+b146d4c); empty = any non-empty",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("reports/local_memory_bench") / time.strftime("%Y%m%dT%H%M%SZ"),
    )
    ap.add_argument(
        "--phases",
        default="preflight,fixture_hashes,health_schema,seed_append",
        help="comma list; unknown names FAIL; explicit long soaks FAIL until implemented",
    )
    args = ap.parse_args()

    phases: list[PhaseResult] = []
    wanted = {p.strip() for p in args.phases.split(",") if p.strip()}
    unknown = sorted(wanted - KNOWN_PHASES)
    if unknown:
        phases.append(
            PhaseResult(
                "phase_validation",
                "FAIL",
                f"unknown phases: {unknown}",
                {"known": sorted(KNOWN_PHASES)},
            )
        )
        summary = write_summary(
            args.out,
            phases,
            {"profile": args.profile, "train": "Soft-OPEN 371 T0b", "error": "unknown_phase"},
        )
        print(json.dumps({"summary": str(summary), "verdict": "FAIL", "phases": [asdict(p) for p in phases]}, indent=2))
        return 2

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
        phases.append(
            phase_health_honesty(
                args.central_base,
                token,
                expected_version_substr=args.expected_version_substr or None,
            )
        )
    if token and "seed_append" in wanted:
        phases.append(phase_seed_append(args.central_base, token, args.fixture_root))

    for name in sorted(LONG_PHASES):
        if name in wanted:
            phases.append(phase_unimplemented(name))
        else:
            phases.append(phase_not_run(name, "not selected in --phases"))

    meta = {
        "profile": args.profile,
        "fixture_root": str(args.fixture_root),
        "central_base": args.central_base or None,
        "expected_version_substr": args.expected_version_substr or None,
        "train": "Soft-OPEN 371 T0b",
        "rules": [
            "no empty/timeout/uptime PASS",
            "strict typed nonnegative counts (bool/string rejected)",
            "independent durable readback required for seed_append",
            "explicit unimplemented long phases FAIL",
            "CONTROL_ONLY ≠ FULL qualification",
            "mintbench never 8 GiB central",
            "log FAIL before product fix",
        ],
    }
    summary = write_summary(args.out, phases, meta)
    verdict = aggregate_verdict(phases)
    print(
        json.dumps(
            {"summary": str(summary), "verdict": verdict, "phases": [asdict(p) for p in phases]},
            indent=2,
        )
    )
    if verdict == "FAIL":
        return 2
    if verdict == "BLOCKED":
        return 3
    if verdict == "CONTROL_ONLY":
        # Smoke/control path: exit 0 but never claim FULL_PASS.
        return 0
    if verdict == "PARTIAL":
        # Incomplete mandatory coverage — not a Soft-OPEN qualify.
        return 4
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
